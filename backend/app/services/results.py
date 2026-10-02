from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, NamedTuple

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError
from app.schemas.academic import Page
from app.schemas.exams import ExaminationType
from app.schemas.marks import MarkStatus
from app.schemas.people import EnrollmentStatus
from app.schemas.results import (
    CgpaResponse,
    CgpaSemester,
    CgpaStatus,
    CourseResult,
    CourseResultStatus,
    Result,
    ResultStatus,
    SgpaItem,
    SgpaResponse,
)
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services import grading
from app.services.academic_common import Actor, Viewer
from app.services.course_offerings import OFFERINGS
from app.services.courses import get_course
from app.services.departments_programs import slug
from app.services.enrollments import ENROLLMENTS
from app.services.exams import EXAMINATIONS, collect
from app.services.semesters import get_semester
from app.services.students import get_student

logger = logging.getLogger(__name__)
RESULTS = "results"
MARKS = "marks"
IN_LIMIT = 30
COUNTED = (EnrollmentStatus.ACTIVE.value, EnrollmentStatus.COMPLETED.value)


class Regenerated(NamedTuple):
    result: Result
    unpublished: bool


def result_id(student_doc_id: str, semester_id: str) -> str:
    return f"{student_doc_id}__{semester_id}"


def _admin(role: str | None) -> bool:
    return role == UserRole.ADMIN.value


def _num(value: Decimal) -> float:
    return float(value)


def compute_semester(student_uid: str, semester_id: str, exam_type: str, scheme) -> dict[str, Any]:
    """Pure derivation from stored enrollments, FINAL marks and trusted course credits.
    Missing marks are never treated as zero: they make the result INCOMPLETE and withhold the SGPA."""
    enrollments = [e for e in collect(ENROLLMENTS, [("student_uid", student_uid), ("semester_id", semester_id)])
                   if e.get("status") in COUNTED]
    enrollments.sort(key=lambda e: e["course_offering_id"])
    marks_by_offering: dict[str, list[dict[str, Any]]] = {}
    exam_types: dict[str, str | None] = {}
    for m in collect(MARKS, [("student_uid", student_uid), ("semester_id", semester_id)]):
        if m.get("status") != MarkStatus.FINAL.value:
            continue
        if m["examination_id"] not in exam_types:
            ex = common.fetch(EXAMINATIONS, m["examination_id"])
            exam_types[m["examination_id"]] = ex.get("examination_type") if ex else None
        if exam_types[m["examination_id"]] == exam_type:
            marks_by_offering.setdefault(m["course_offering_id"], []).append(m)

    seen_courses: set[str] = set()
    rows: list[CourseResult] = []
    graded: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []  # credits, grade point, total, max
    earned = Decimal(0)
    counted_credits = Decimal(0)
    incomplete = False
    for e in enrollments:
        course = get_course(e["course_id"])  # credits always come from the trusted course record
        credits = grading.dec(course.credits)
        base = dict(course_id=course.id, course_code=course.code, course_name=course.name,
                    course_offering_id=e["course_offering_id"], credits=float(credits))
        if course.id in seen_courses:
            rows.append(CourseResult(**base, status=CourseResultStatus.DUPLICATE))
            continue
        seen_courses.add(course.id)
        counted_credits += credits
        marks = marks_by_offering.get(e["course_offering_id"], [])
        if not marks:
            incomplete = True
            rows.append(CourseResult(**base, status=CourseResultStatus.MISSING))
            continue
        if len(marks) > 1:
            incomplete = True
            rows.append(CourseResult(**base, status=CourseResultStatus.AMBIGUOUS))
            continue
        m = marks[0]
        g = grading.calculate_grade(m["percentage"], scheme)  # recomputed from the live scheme
        earned_here = credits if g.is_pass else Decimal(0)
        earned += earned_here
        graded.append((credits, grading.dec(g.grade_point), grading.dec(m["total_marks"]), grading.dec(m["max_marks"])))
        rows.append(CourseResult(**base, status=CourseResultStatus.GRADED, mark_id=m["id"],
                                 total_marks=m["total_marks"], max_marks=m["max_marks"],
                                 percentage=m["percentage"], grade=g.grade, grade_point=g.grade_point,
                                 passed=g.is_pass, earned_credits=float(earned_here)))
    complete = bool(graded) and not incomplete
    total_marks = sum((t for _, _, t, _ in graded), Decimal(0))
    max_marks = sum((x for _, _, _, x in graded), Decimal(0))
    sgpa = grading.calculate_sgpa([(c, gp) for c, gp, _, _ in graded]) if complete else None
    return {
        "courses": [r.model_dump(mode="json") for r in rows],
        "total_credits": _num(counted_credits),
        "earned_credits": _num(earned),
        "total_marks": _num(total_marks) if graded else None,
        "max_marks": _num(max_marks) if graded else None,
        "percentage": _num(grading.calculate_percentage(total_marks, max_marks)) if max_marks > 0 else None,
        "sgpa": _num(sgpa) if sgpa is not None else None,
        "status": (ResultStatus.COMPLETE if complete and sgpa is not None else ResultStatus.INCOMPLETE).value,
    }


_CONTENT = ("courses", "total_credits", "earned_credits", "total_marks", "max_marks", "percentage", "sgpa", "status")


def _store(student, semester, exam_type: str, actor: Actor, scheme) -> Regenerated:
    doc_id = result_id(slug(student.student_id), semester.id)
    calc = compute_semester(student.uid, semester.id, exam_type, scheme)
    existing = common.fetch(RESULTS, doc_id)
    ts = common.now()
    unpublished = False
    if existing is None:
        data = {
            "result_id": doc_id, "student_uid": student.uid, "student_id": student.student_id,
            "academic_session_id": semester.academic_session_id, "semester_id": semester.id,
            "program_id": semester.program_id, "examination_type": exam_type, **calc,
            "published": False, "published_at": None, "published_by_uid": None,
            "generated_by_uid": actor.uid, "created_at": ts, "updated_at": ts,
        }
        common.write(RESULTS, doc_id, data, create=True, conflict_message="Result generation conflict; retry.")
        action = "result.generate"
    else:
        changed = any(existing.get(k) != calc[k] for k in _CONTENT) or existing.get("examination_type") != exam_type
        update = {**calc, "examination_type": exam_type, "generated_by_uid": actor.uid, "updated_at": ts}
        if changed and existing.get("published"):
            # A published result must never contradict the marks: pull it back for re-review.
            update.update({"published": False, "published_at": None, "published_by_uid": None})
            unpublished = True
        data = {**existing, **update}
        common.write(RESULTS, doc_id, update, create=False)
        action = "result.regenerate"
    common.audit(actor, action, "result", doc_id, {"status": calc["status"], "unpublished": unpublished})
    return Regenerated(Result(**{**data, "id": doc_id}), unpublished)


def generate_result(student_id: str, semester_id: str, exam_type: ExaminationType, actor: Actor) -> Result:
    student = get_student(slug(student_id))  # 404
    semester = get_semester(semester_id)  # 404
    if student.program_id != semester.program_id:
        raise AcademicValidationError("Semester does not belong to the student's program.")
    scheme = grading.get_scheme()
    return _store(student, semester, exam_type.value, actor, scheme).result


def regenerate_if_exists(student_doc_id: str, student_uid: str, semester_id: str, actor: Actor) -> Regenerated | None:
    """Keep an existing result in step with changed marks. Skipped when no result was generated
    yet or no grading scheme is configured. Never fails the calling mark operation."""
    try:
        existing = common.fetch(RESULTS, result_id(student_doc_id, semester_id))
        if existing is None:
            return None
        scheme = grading.get_scheme(required=False)
        if scheme is None:
            return None
        student = get_student(student_doc_id)
        semester = get_semester(semester_id)
        return _store(student, semester, existing.get("examination_type") or ExaminationType.END_SEMESTER.value,
                      actor, scheme)
    except Exception as exc:  # noqa: BLE001
        logger.error("Result regeneration failed (%s).", type(exc).__name__)
        return None


def set_published(result_id_: str, publish: bool, actor: Actor) -> Result:
    row = common.fetch(RESULTS, result_id_)
    if row is None:
        raise AcademicNotFoundError("Result not found.")
    if publish:
        # Recompute first so a published result always reflects the current marks.
        regen = regenerate_if_exists(slug(row["student_id"]), row["student_uid"], row["semester_id"], actor)
        if regen is None:
            raise AcademicConflictError("Result could not be recalculated. Regenerate it before publication.")
        row = common.fetch(RESULTS, result_id_) or row
        if row["status"] != ResultStatus.COMPLETE.value:
            raise AcademicConflictError("Only COMPLETE results (all course marks finalized) can be published.")
    update = {"published": publish, "published_at": common.now() if publish else None,
              "published_by_uid": actor.uid if publish else None, "updated_at": common.now()}
    common.write(RESULTS, result_id_, update, create=False)
    common.audit(actor, "result.publish" if publish else "result.unpublish", "result", result_id_, None)
    return Result(**{**row, **update})


# ---- reads ----------------------------------------------------------------
def _faculty_view(row: dict[str, Any], offering_ids: set[str]) -> Result | None:
    courses = [c for c in row["courses"] if c["course_offering_id"] in offering_ids]
    if not courses:
        return None
    row = {**row, "courses": courses, "total_credits": None, "earned_credits": None, "total_marks": None,
           "max_marks": None, "percentage": None, "sgpa": None}
    return Result(**row)


def _faculty_offerings(uid: str) -> set[str]:
    return {o["id"] for o in collect(OFFERINGS, [("faculty_uid", uid)])}


def get_result(result_id_: str, viewer: Viewer) -> Result:
    row = common.fetch(RESULTS, result_id_)
    if row is not None:
        if _admin(viewer.role):
            return Result(**row)
        if viewer.role == UserRole.STUDENT.value and row["student_uid"] == viewer.uid and row.get("published"):
            return Result(**row)
        if viewer.role == UserRole.FACULTY.value:
            view = _faculty_view(row, _faculty_offerings(viewer.uid))
            if view is not None:
                return view
    raise AcademicNotFoundError("Result not found.")


def list_results(*, viewer: Viewer, limit: int, cursor: str | None, **f) -> Page[Result]:
    sid = f.get("student_id")
    filters: list[tuple] = []
    student_uid = None
    published = f.get("published")
    if viewer.role == UserRole.STUDENT.value:
        student_uid = viewer.uid
        if published is False:
            return Page[Result](items=[], next_cursor=None)
        published = True
    elif viewer.role == UserRole.FACULTY.value:
        return _list_for_faculty(viewer, limit, cursor, f)
    elif not _admin(viewer.role):
        return Page[Result](items=[], next_cursor=None)
    status = f.get("status")
    filters += [
        ("student_id", sid.upper() if sid else None),
        ("student_uid", student_uid),
        ("semester_id", f.get("semester_id")),
        ("academic_session_id", f.get("academic_session_id")),
        ("program_id", f.get("program_id")),
        ("status", status.value if status else None),
        ("published", published),
    ]
    rows, nxt = common.list_docs(RESULTS, filters, limit, cursor)
    return Page[Result](items=[Result(**r) for r in rows], next_cursor=nxt)


def _list_for_faculty(viewer: Viewer, limit: int, cursor: str | None, f: dict[str, Any]) -> Page[Result]:
    """Faculty only see course rows of offerings assigned to them (no aggregates)."""
    offering_ids = _faculty_offerings(viewer.uid)
    if not offering_ids:
        return Page[Result](items=[], next_cursor=None)
    sid = f.get("student_id")
    status = f.get("status")
    filters = [("student_id", sid.upper() if sid else None), ("semester_id", f.get("semester_id")),
               ("academic_session_id", f.get("academic_session_id")), ("program_id", f.get("program_id")),
               ("status", status.value if status else None), ("published", f.get("published"))]
    rows = collect(RESULTS, filters)
    views = [v for r in rows if (v := _faculty_view(r, offering_ids)) is not None]
    views.sort(key=lambda r: r.id)
    start = next((i + 1 for i, r in enumerate(views) if r.id == cursor), 0) if cursor else 0
    limit = max(1, min(limit, common.MAX_PAGE_SIZE))
    page = views[start:start + limit]
    return Page[Result](items=page, next_cursor=page[-1].id if start + limit < len(views) and page else None)


def sgpa_for(*, viewer: Viewer, student_uid: str, semester_id: str | None) -> SgpaResponse:
    filters = [("student_uid", student_uid), ("semester_id", semester_id)]
    if not _admin(viewer.role):
        filters.append(("published", True))  # students only ever see published SGPA
    rows = collect(RESULTS, filters)
    rows.sort(key=lambda r: r["semester_id"])
    return SgpaResponse(items=[SgpaItem(
        student_id=r["student_id"], semester_id=r["semester_id"], academic_session_id=r["academic_session_id"],
        total_credits=r["total_credits"], earned_credits=r["earned_credits"], sgpa=r["sgpa"],
        status=r["status"], published=bool(r.get("published"))) for r in rows])


def cgpa_for(*, viewer: Viewer, student_uid: str, student_id: str) -> CgpaResponse:
    """Credit-weighted: sum(semester credits * SGPA) / sum(semester credits), over COMPLETE
    semesters (published ones for students). Incomplete/unpublished semesters are excluded and
    reported; a semester without any result record cannot be detected and is simply absent."""
    rows = collect(RESULTS, [("student_uid", student_uid)])
    rows.sort(key=lambda r: r["semester_id"])
    used: list[CgpaSemester] = []
    excluded = 0
    for r in rows:
        ok = r["status"] == ResultStatus.COMPLETE.value and r.get("sgpa") is not None and r["total_credits"] > 0
        if ok and not _admin(viewer.role):
            ok = bool(r.get("published"))
        if ok:
            used.append(CgpaSemester(semester_id=r["semester_id"], academic_session_id=r["academic_session_id"],
                                     total_credits=r["total_credits"], sgpa=r["sgpa"]))
        else:
            excluded += 1
    cgpa = grading.calculate_cgpa([(s.total_credits, s.sgpa) for s in used])
    total = sum((grading.dec(s.total_credits) for s in used), Decimal(0))
    status = CgpaStatus.NO_DATA if not used else (CgpaStatus.PARTIAL if excluded else CgpaStatus.COMPLETE)
    return CgpaResponse(student_id=student_id, semesters_considered=used, semesters_excluded=excluded,
                        total_credits=float(total), cgpa=float(cgpa) if cgpa is not None else None, status=status)

