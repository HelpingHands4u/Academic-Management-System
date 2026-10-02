from __future__ import annotations

from datetime import date
from typing import Any

from app.core.errors import AcademicValidationError
from app.schemas.analytics import ActiveSessionRef, ActiveUsers, AdminAnalytics, FacultyAnalytics, StudentAnalytics
from app.schemas.exams import ScheduleStatus
from app.schemas.notices import Notice
from app.schemas.people import EnrollmentStatus
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services import attendance, course_offerings, enrollments, exams, notices, results, sessions, timetable
from app.services.academic_common import Viewer, count_docs, drain
from app.services.students import get_student_by_uid
from app.core.errors import AcademicNotFoundError
from datetime import timedelta

ACTIVE = EnrollmentStatus.ACTIVE.value


def admin_overview() -> AdminAnalytics:
    """Server-side COUNT aggregations only: no documents are read."""
    return AdminAnalytics(
        active_students=count_docs("students", [("is_active", True)]),
        active_faculty=count_docs("faculty", [("is_active", True)]),
        departments=count_docs("departments", []),
        programs=count_docs("programs", []),
        courses=count_docs("courses", []),
        course_offerings=count_docs("course_offerings", []),
        active_enrollments=count_docs("enrollments", [("status", ACTIVE)]),
        examinations=count_docs("examinations", []),
        attendance_records=count_docs("attendance", []),
        published_results=count_docs("results", [("published", True)]),
        active_notices=count_docs("notices", [("is_active", True), ("is_published", True)]),
    )


def faculty_overview(viewer: Viewer) -> FacultyAnalytics:
    offerings = exams._faculty_offerings(viewer.uid)
    ids = [o["id"] for o in offerings]
    enrolled: list[dict[str, Any]] = []
    attendance_total = 0
    schedules: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []
    for chunk in exams._chunks(ids):
        in_f = ("course_offering_id", chunk, "in")
        enrolled += exams.collect("enrollments", [in_f, ("status", ACTIVE)])
        attendance_total += count_docs("attendance", [in_f])
        schedules += exams.collect("exam_schedules", [in_f])
        marks += exams.collect("marks", [in_f])
    live = [s for s in schedules if s.get("status") != ScheduleStatus.CANCELLED.value]
    # Pending = an active enrollment x a live exam schedule of that offering with no mark document yet.
    marked = {(m["student_uid"], m["course_offering_id"], m["examination_id"]) for m in marks}
    by_offering: dict[str, set[str]] = {}
    for e in enrolled:
        by_offering.setdefault(e["course_offering_id"], set()).add(e["student_uid"])
    pending = sum(1 for s in live for uid in by_offering.get(s["course_offering_id"], ())
                  if (uid, s["course_offering_id"], s["examination_id"]) not in marked)
    today = date.today().isoformat()
    upcoming = [s for s in schedules if s.get("status") == ScheduleStatus.SCHEDULED.value
                and str(s.get("exam_date")) >= today]
    return FacultyAnalytics(
        assigned_course_offerings=len(ids),
        enrolled_students=len({e["student_uid"] for e in enrolled}),
        attendance_records=attendance_total,
        upcoming_exam_schedules=len(upcoming),
        pending_marks=pending,
        live_notices=len(notices._feed(viewer, [])),
    )


def student_overview(viewer: Viewer) -> StudentAnalytics:
    """Everything is derived from the authenticated uid; existing services apply their own scoping."""
    try:
        get_student_by_uid(viewer.uid)
    except AcademicNotFoundError:
        return StudentAnalytics(profile_found=False, enrolled_courses=0, enrollments=[], attendance=[],
                                upcoming_exams=[], published_results=0, sgpa=[], cgpa=None, timetable=[], notices=[])
    student = get_student_by_uid(viewer.uid)
    enr = drain(enrollments.list_enrollments, viewer=viewer, student_id=None, student_uid=None,
                course_offering_id=None, course_id=None, semester_id=None, status=EnrollmentStatus.ACTIVE)
    today = date.today()
    upcoming = [s for s in drain(exams.list_schedules, viewer=viewer, status=ScheduleStatus.SCHEDULED)
                if s.exam_date >= today]
    upcoming.sort(key=lambda s: (s.exam_date, s.start_time, s.id))
    published = drain(results.list_results, viewer=viewer)
    return StudentAnalytics(
        profile_found=True,
        enrolled_courses=len({e.course_id for e in enr}),
        enrollments=enr,
        attendance=attendance.attendance_summary(
            viewer=viewer, student_id=None, student_uid=None, course_offering_id=None, course_id=None,
            semester_id=None, academic_session_id=None, faculty_uid=None, attendance_date=None, status=None).items,
        upcoming_exams=upcoming,
        published_results=len(published),
        sgpa=results.sgpa_for(viewer=viewer, student_uid=viewer.uid, semester_id=None).items,
        cgpa=results.cgpa_for(viewer=viewer, student_uid=viewer.uid, student_id=student.student_id),
        timetable=drain(timetable.list_entries, viewer=viewer),
        notices=[Notice(**r) for r in notices._feed(viewer, [])],
    )


def active_users(include_sessions: bool = False) -> ActiveUsers:
    active_s, recent_s = sessions.windows()
    at = common.now()
    open_rows = exams.collect(sessions.SESSIONS, [("is_active", True), ("last_seen_at", at - timedelta(seconds=active_s), ">=")])
    recent_rows = exams.collect(sessions.SESSIONS, [("last_seen_at", at - timedelta(seconds=recent_s), ">=")])

    def distinct(rows: list[dict[str, Any]], role: str | None = None) -> set[str]:
        return {r["uid"] for r in rows if role is None or r.get("role") == role}

    return ActiveUsers(
        active_window_seconds=active_s, recent_window_seconds=recent_s,
        active_user_count=len(distinct(open_rows)),
        active_student_count=len(distinct(open_rows, UserRole.STUDENT.value)),
        active_faculty_count=len(distinct(open_rows, UserRole.FACULTY.value)),
        active_admin_count=len(distinct(open_rows, UserRole.ADMIN.value)),
        recently_active_count=len(distinct(recent_rows)),
        total_users=count_docs("users", []),
        total_students=count_docs("users", [("role", UserRole.STUDENT.value)]),
        total_faculty=count_docs("users", [("role", UserRole.FACULTY.value)]),
        total_admins=count_docs("users", [("role", UserRole.ADMIN.value)]),
        active_sessions=[ActiveSessionRef(session_id=r["id"], uid=r["uid"], role=r["role"]) for r in open_rows]
        if include_sessions else None,
    )
