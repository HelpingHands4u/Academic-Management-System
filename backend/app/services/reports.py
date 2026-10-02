from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from typing import Any, Callable

from app.core.errors import AcademicForbiddenError, AcademicNotFoundError, AcademicValidationError
from app.schemas.attendance import AttendanceSummaryItem
from app.schemas.courses import Course
from app.schemas.exams import ExamScheduleView
from app.schemas.people import Enrollment, EnrollmentStatus, Faculty, Student
from app.schemas.reports import Report
from app.schemas.results import Result, ResultStatus
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services import attendance, courses, enrollments, exams, faculty, results, students
from app.services.academic_common import Viewer, drain
from app.services.departments_programs import slug

ADMIN, FACULTY, STUDENT = UserRole.ADMIN.value, UserRole.FACULTY.value, UserRole.STUDENT.value


def _require(viewer: Viewer, *roles: str) -> None:
    if viewer.role not in roles:
        raise AcademicForbiddenError("You do not have access to this report.")


def _page(items: list, limit: int, cursor: str | None, key: Callable[[Any], str]) -> tuple[list, str | None]:
    """In-memory cursor pagination over an already scope-limited, bounded list (same cursor convention)."""
    limit = max(1, min(limit, common.MAX_PAGE_SIZE))
    start = next((i + 1 for i, x in enumerate(items) if key(x) == cursor), 0) if cursor else 0
    page = items[start:start + limit]
    return page, (key(page[-1]) if page and start + limit < len(items) else None)


def _report(summary: dict[str, Any], items: list, limit: int, cursor: str | None, key) -> Report:
    page, nxt = _page(items, limit, cursor, key)
    return Report(summary=summary, items=page, next_cursor=nxt)


def _faculty_uid(faculty_id: str | None) -> str | None:
    if not faculty_id:
        return None
    return faculty.get_faculty(slug(faculty_id)).uid  # 404 if unknown


def _day_bounds(from_date: date | None, to_date: date | None) -> None:
    if from_date and to_date and from_date > to_date:
        from app.core.errors import UnprocessableAcademicError
        raise UnprocessableAcademicError("from_date must not be after to_date.")


def _by(rows, field: str) -> dict[str, int]:
    def label(v):
        return str(getattr(v, "value", v))

    return dict(sorted(Counter(label(getattr(r, field, None)) for r in rows).items()))


# ---- Students / faculty (ADMIN only) --------------------------------------
def student_report(viewer: Viewer, *, department_id, program_id, semester_id, section, batch, is_active,
                   limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN)
    rows = drain(students.list_students, department_id=department_id, program_id=program_id,
                 semester_id=semester_id, section=section.upper() if section else None, batch=batch, is_active=is_active)
    summary = {"total": len(rows), "active": sum(1 for r in rows if r.is_active),
               "by_department": _by(rows, "department_id"), "by_program": _by(rows, "program_id"),
               "by_semester": _by(rows, "current_semester_id")}
    return _report(summary, rows, limit, cursor, lambda r: r.id)


def faculty_report(viewer: Viewer, *, department_id, designation, is_active, limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN)
    rows = drain(faculty.list_faculty, department_id=department_id, designation=designation, is_active=is_active)
    summary = {"total": len(rows), "active": sum(1 for r in rows if r.is_active),
               "by_department": _by(rows, "department_id"), "by_designation": _by(rows, "designation")}
    return _report(summary, rows, limit, cursor, lambda r: r.id)


# ---- Courses (ADMIN: all; FACULTY: courses of assigned offerings) ----------
def course_report(viewer: Viewer, *, department_id, program_id, semester_number, course_type, is_active,
                  limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN, FACULTY)
    if viewer.role == ADMIN:
        rows = drain(courses.list_courses, department_id=department_id, program_id=program_id,
                     semester_number=semester_number, course_type=course_type, is_active=is_active, code_prefix=None)
    else:
        ids = sorted({o["course_id"] for o in exams._faculty_offerings(viewer.uid)})
        rows = [Course(**r) for r in (common.fetch("courses", i) for i in ids) if r]
        rows = [c for c in rows if (not department_id or c.department_id == department_id)
                and (not program_id or c.program_id == program_id)
                and (semester_number is None or c.semester_number == semester_number)
                and (course_type is None or c.course_type == course_type)
                and (is_active is None or c.is_active == is_active)]
    summary = {"total": len(rows), "total_credits": float(sum(c.credits for c in rows)),
               "by_type": _by(rows, "course_type"), "by_program": _by(rows, "program_id")}
    return _report(summary, rows, limit, cursor, lambda r: r.id)


# ---- Attendance (ADMIN / FACULTY scoped / STUDENT own) ---------------------
def attendance_report(viewer: Viewer, *, academic_session_id, semester_id, course_id, course_offering_id,
                      student_id, faculty_id, from_date: date | None, to_date: date | None,
                      limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN, FACULTY, STUDENT)
    _day_bounds(from_date, to_date)
    scoped = attendance._scoped_filters(
        viewer, student_id=student_id, student_uid=None, course_offering_id=course_offering_id,
        course_id=course_id, semester_id=semester_id, academic_session_id=academic_session_id,
        faculty_uid=_faculty_uid(faculty_id) if viewer.role == ADMIN else None,
        attendance_date=None, status=None)
    rows: list[dict[str, Any]] = []
    if scoped is not None:
        order = "__name__"
        if from_date or to_date:
            scoped += [("attendance_date", from_date.isoformat() if from_date else None, ">="),
                       ("attendance_date", to_date.isoformat() if to_date else None, "<=")]
            order = "attendance_date"
        nxt = None
        while True:
            page, nxt = common.list_docs("attendance", scoped, common.MAX_PAGE_SIZE, nxt, order_by=order)
            rows += page
            if len(rows) > attendance.MAX_SUMMARY_SCAN:
                raise AcademicValidationError("Too many attendance records to report; narrow the filters.")
            if nxt is None:
                break
    items = attendance.summarize(rows)
    attended = sum(i.attended_count for i in items)
    total = sum(i.total_classes for i in items)
    summary = {"total_records": total, "attended_count": attended,
               "attendance_percentage": attendance.percentage(attended, total),
               "students": len({i.student_uid for i in items}), "course_offerings": len({i.course_offering_id for i in items})}
    return _report(summary, items, limit, cursor, lambda i: f"{i.student_uid}|{i.course_offering_id}")


# ---- Examinations (schedules visible to the caller) ------------------------
def examination_report(viewer: Viewer, *, academic_session_id, semester_id, program_id, department_id,
                       course_id, course_offering_id, faculty_id, from_date: date | None, to_date: date | None,
                       limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN, FACULTY, STUDENT)
    _day_bounds(from_date, to_date)
    rows = drain(exams.list_schedules, viewer=viewer, academic_session_id=academic_session_id,
                 semester_id=semester_id, program_id=program_id, department_id=department_id, course_id=course_id,
                 course_offering_id=course_offering_id, faculty_uid=_faculty_uid(faculty_id), examination_id=None,
                 exam_date=None, status=None)
    rows = [r for r in rows if (not from_date or r.exam_date >= from_date) and (not to_date or r.exam_date <= to_date)]
    rows.sort(key=lambda r: (r.exam_date, r.start_time, r.id))
    summary = {"total_schedules": len(rows), "by_status": _by(rows, "status"),
               "by_examination": _by(rows, "examination_id"), "total_max_marks": sum(r.max_marks for r in rows)}
    return _report(summary, rows, limit, cursor, lambda r: r.id)


# ---- Results / grades -------------------------------------------------------
def result_report(viewer: Viewer, *, academic_session_id, semester_id, program_id, student_id, status, published,
                  limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN, FACULTY, STUDENT)
    rows = drain(results.list_results, viewer=viewer, student_id=student_id, semester_id=semester_id,
                 academic_session_id=academic_session_id, program_id=program_id, status=status, published=published)
    summary: dict[str, Any] = {"total": len(rows), "by_status": _by(rows, "status")}
    if viewer.role != FACULTY:  # faculty see course rows only: no aggregates (matches the results module)
        sgpas = [r.sgpa for r in rows if r.sgpa is not None]
        grades = Counter(c.grade for r in rows for c in r.courses if c.grade)
        summary |= {"published": sum(1 for r in rows if r.published),
                    "average_sgpa": round(sum(sgpas) / len(sgpas), 2) if sgpas else None,
                    "grade_distribution": dict(sorted(grades.items()))}
    else:
        grades = Counter(c.grade for r in rows for c in r.courses if c.grade)
        summary["grade_distribution"] = dict(sorted(grades.items()))
    return _report(summary, rows, limit, cursor, lambda r: r.id)


# ---- Enrollments ------------------------------------------------------------
def enrollment_report(viewer: Viewer, *, academic_session_id, semester_id, program_id, course_id,
                      course_offering_id, student_id, status, from_date: date | None, to_date: date | None,
                      limit: int, cursor: str | None) -> Report:
    _require(viewer, ADMIN, FACULTY, STUDENT)
    _day_bounds(from_date, to_date)
    rows = drain(enrollments.list_enrollments, viewer=viewer, student_id=student_id, student_uid=None,
                 course_offering_id=course_offering_id, course_id=course_id, semester_id=semester_id, status=status)

    def day(r: Enrollment) -> date | None:
        v = r.enrolled_at
        return v.date() if isinstance(v, datetime) else None

    rows = [r for r in rows if (not academic_session_id or r.academic_session_id == academic_session_id)
            and (not program_id or r.program_id == program_id)
            and (not from_date or (day(r) and day(r) >= from_date))
            and (not to_date or (day(r) and day(r) <= to_date))]
    summary = {"total": len(rows), "by_status": _by(rows, "status"), "by_course": _by(rows, "course_id"),
               "distinct_students": len({r.student_uid for r in rows})}
    return _report(summary, rows, limit, cursor, lambda r: r.id)


