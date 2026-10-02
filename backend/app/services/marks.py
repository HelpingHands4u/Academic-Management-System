from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.errors import (
    AcademicForbiddenError,
    AcademicNotFoundError,
    AcademicValidationError,
    UnprocessableAcademicError,
)
from app.schemas.academic import Page
from app.schemas.exams import ExaminationStatus
from app.schemas.marks import (
    GradingScheme,
    Mark,
    MarkCreate,
    MarkStatus,
    MarkUpdate,
    MarkView,
    RegradeResponse,
)
from app.schemas.people import EnrollmentStatus
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services import grading, results
from app.services.academic_common import Actor, Viewer
from app.services.course_offerings import OFFERINGS
from app.services.courses import get_course
from app.services.departments_programs import slug
from app.services.enrollments import ENROLLMENTS, enrollment_id
from app.services.exams import EXAM_SCHEDULES, EXAMINATIONS, collect, schedule_id
from app.services.students import get_student

MARKS = "marks"
IN_LIMIT = 30
COMPONENTS = ("internal", "external", "practical")


def mark_id(student_doc_id: str, offering_id: str, exam_id: str) -> str:
    return f"{student_doc_id}__{offering_id}__{exam_id}"


def _admin(role: str | None) -> bool:
    return role == UserRole.ADMIN.value


def _require_marker(viewer: Viewer, offering: dict[str, Any]) -> None:
    if _admin(viewer.role):
        return
    if viewer.role == UserRole.FACULTY.value and offering.get("faculty_uid") == viewer.uid:
        return
    raise AcademicForbiddenError("You are not allowed to manage marks for this course offering.")


def compute(values: dict[str, Any], reference_max: Any) -> dict[str, Any]:
    """Validate components and calculate total/max/percentage. `values` holds
    {internal,external,practical}_marks and *_max_marks (None = component not used).

    With component maximums supplied they must cover every entered component and sum to the
    trusted reference maximum (exam schedule / course); otherwise the reference is the maximum."""
    ref = grading.dec(reference_max)
    present = [c for c in COMPONENTS if values.get(f"{c}_marks") is not None]
    if not present:
        raise UnprocessableAcademicError("At least one mark component is required.")
    for c in COMPONENTS:
        if c not in present and values.get(f"{c}_max_marks") is not None:
            raise UnprocessableAcademicError(f"{c}_max_marks was given without {c}_marks.")
    with_max = [c for c in present if values.get(f"{c}_max_marks") is not None]
    if with_max:
        if len(with_max) != len(present):
            raise UnprocessableAcademicError("Provide a maximum for every entered component, or for none.")
        for c in present:
            if grading.dec(values[f"{c}_marks"]) > grading.dec(values[f"{c}_max_marks"]):
                raise UnprocessableAcademicError(f"{c}_marks exceeds {c}_max_marks.")
        if sum((grading.dec(values[f"{c}_max_marks"]) for c in present), Decimal(0)) != ref:
            raise UnprocessableAcademicError("Component maximums must add up to the maximum marks of the assessment.")
    total = sum((grading.dec(values[f"{c}_marks"]) for c in present), Decimal(0))
    if total > ref:
        raise UnprocessableAcademicError("Total marks exceed the maximum marks.")
    pct = grading.calculate_percentage(total, ref)
    return {"total_marks": float(total), "max_marks": float(ref), "percentage": float(pct)}


def grade_fields(percentage: float, scheme: GradingScheme | None) -> dict[str, Any]:
    if scheme is None:
        return {"grade": None, "grade_point": None}
    g = grading.calculate_grade(percentage, scheme)
    return {"grade": g.grade, "grade_point": g.grade_point}


def create_mark(payload: MarkCreate, viewer: Viewer) -> Mark:
    actor = Actor(viewer.uid, viewer.role)
    student_doc = slug(payload.student_id)
    student = get_student(student_doc)  # 404
    offering = common.fetch(OFFERINGS, payload.course_offering_id)
    if offering is None:
        raise AcademicNotFoundError("Course offering not found.")
    _require_marker(viewer, offering)
    course = get_course(offering["course_id"])  # 404
    exam_row = common.fetch(EXAMINATIONS, payload.examination_id)
    if exam_row is None:
        raise AcademicNotFoundError("Examination not found.")
    if not student.is_active:
        raise AcademicValidationError("Student is not active.")
    enr = common.fetch(ENROLLMENTS, enrollment_id(student_doc, offering["id"]))
    if enr is None or enr.get("status") not in (EnrollmentStatus.ACTIVE.value, EnrollmentStatus.COMPLETED.value):
        raise AcademicValidationError("Student is not enrolled in this course offering.")
    if exam_row["semester_id"] != offering["semester_id"] or \
            exam_row["academic_session_id"] != offering["academic_session_id"]:
        raise AcademicValidationError("Examination does not belong to the course offering's semester/session.")
    if exam_row.get("status") in (ExaminationStatus.CANCELLED.value, ExaminationStatus.DRAFT.value):
        raise AcademicValidationError("Examination is not open for marks entry.")

    schedule = None
    sched_id = schedule_id(payload.examination_id, offering["id"])
    if payload.exam_schedule_id is not None and payload.exam_schedule_id != sched_id:
        raise AcademicValidationError("Exam schedule does not match the examination and course offering.")
    if payload.exam_schedule_id is not None:
        schedule = common.fetch(EXAM_SCHEDULES, sched_id)
        if schedule is None:
            raise AcademicNotFoundError("Exam schedule not found.")
    else:
        schedule = common.fetch(EXAM_SCHEDULES, sched_id)  # optional: used when it exists
    reference = schedule["max_marks"] if schedule else course.max_marks
    values = payload.model_dump(exclude={"student_id", "course_offering_id", "examination_id",
                                          "exam_schedule_id", "status", "remarks"})
    calc = compute(values, reference)
    status = payload.status
    if status == MarkStatus.FINAL and not _admin(viewer.role):
        raise AcademicForbiddenError("Only an ADMIN can finalize (verify) marks.")

    doc_id = mark_id(student_doc, offering["id"], payload.examination_id)
    ts = common.now()
    data = {
        "mark_id": doc_id,
        "student_uid": student.uid,
        "student_id": student.student_id,
        "course_offering_id": offering["id"],
        "course_id": course.id,
        "examination_id": payload.examination_id,
        "exam_schedule_id": sched_id if schedule else None,
        "academic_session_id": offering["academic_session_id"],
        "semester_id": offering["semester_id"],
        **values,
        **calc,
        **grade_fields(calc["percentage"], grading.get_scheme(required=False)),
        "status": status.value,
        "remarks": payload.remarks,
        "entered_by_uid": viewer.uid,
        "verified_by_uid": viewer.uid if status == MarkStatus.FINAL else None,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(MARKS, doc_id, data, create=True,
                 conflict_message="Marks already exist for this student, course offering and examination.")
    common.audit(actor, "mark.create", "mark", doc_id, {"course_offering_id": offering["id"], "status": status.value})
    results.regenerate_if_exists(student_doc, student.uid, offering["semester_id"], actor)
    return Mark(id=doc_id, **data)


def update_mark(mark_id_: str, payload: MarkUpdate, viewer: Viewer) -> Mark:
    actor = Actor(viewer.uid, viewer.role)
    row = common.fetch(MARKS, mark_id_)
    if row is None:
        raise AcademicNotFoundError("Mark not found.")
    offering = common.fetch(OFFERINGS, row["course_offering_id"])
    if offering is None:
        raise AcademicNotFoundError("Course offering not found.")
    if not _admin(viewer.role) and (viewer.role != UserRole.FACULTY.value or offering.get("faculty_uid") != viewer.uid):
        raise AcademicNotFoundError("Mark not found.")  # do not reveal other offerings' marks
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] is None:
        raise AcademicValidationError("status cannot be null.")
    if not _admin(viewer.role):
        if row["status"] == MarkStatus.FINAL.value:
            raise AcademicForbiddenError("Finalized marks can only be changed by an ADMIN.")
        if changes.get("status") == MarkStatus.FINAL:
            raise AcademicForbiddenError("Only an ADMIN can finalize (verify) marks.")
    merged = {**row, **{k: v for k, v in changes.items() if k not in ("status", "remarks")}}
    touches_marks = any(k.endswith("marks") for k in changes)
    update: dict[str, Any] = {}
    if touches_marks:
        for c in COMPONENTS:  # a removed component drops its maximum too
            if merged.get(f"{c}_marks") is None and f"{c}_max_marks" not in changes:
                merged[f"{c}_max_marks"] = None
        calc = compute(merged, row["max_marks"])
        update.update({f"{c}_{s}": merged.get(f"{c}_{s}") for c in COMPONENTS for s in ("marks", "max_marks")})
        update.update(calc)
    scheme = grading.get_scheme(required=False)
    update.update(grade_fields(update.get("percentage", row["percentage"]), scheme))
    if "remarks" in changes:
        update["remarks"] = changes["remarks"]
    new_status = changes["status"].value if changes.get("status") else row["status"]
    if new_status != row["status"] or touches_marks:
        update["status"] = new_status
        update["verified_by_uid"] = viewer.uid if new_status == MarkStatus.FINAL.value else None
    update["updated_at"] = common.now()
    common.write(MARKS, mark_id_, update, create=False)
    common.audit(actor, "mark.update", "mark", mark_id_,
                 {"fields": sorted(k for k in changes), "status": new_status})
    results.regenerate_if_exists(slug(row["student_id"]), row["student_uid"], row["semester_id"], actor)
    return Mark(**{**row, **update})


def _enrich(rows: list[dict[str, Any]]) -> list[MarkView]:
    courses: dict[str, Any] = {}
    exams: dict[str, Any] = {}
    out = []
    for r in rows:
        if r["course_id"] not in courses:
            try:
                courses[r["course_id"]] = get_course(r["course_id"])
            except AcademicNotFoundError:
                courses[r["course_id"]] = None
        ex = exams.setdefault(r["examination_id"], common.fetch(EXAMINATIONS, r["examination_id"]))
        c = courses[r["course_id"]]
        out.append(MarkView(**r, course_code=c.code if c else None, course_name=c.name if c else None,
                            examination_name=ex.get("name") if ex else None))
    return out


def _can_read(viewer: Viewer, row: dict[str, Any]) -> bool:
    if _admin(viewer.role):
        return True
    if viewer.role == UserRole.STUDENT.value:
        return row["student_uid"] == viewer.uid and row["status"] == MarkStatus.FINAL.value
    if viewer.role == UserRole.FACULTY.value:
        off = common.fetch(OFFERINGS, row["course_offering_id"])
        return bool(off) and off.get("faculty_uid") == viewer.uid
    return False


def get_mark(mark_id_: str, viewer: Viewer) -> MarkView:
    row = common.fetch(MARKS, mark_id_)
    if row is None or not _can_read(viewer, row):
        raise AcademicNotFoundError("Mark not found.")
    return _enrich([row])[0]


def list_marks(*, viewer: Viewer, limit: int, cursor: str | None, **f) -> Page[MarkView]:
    """Scope comes from the verified identity; request filters can only narrow it."""
    filters: list[tuple] = []
    student_uid = f.get("student_uid")
    status = f.get("status")
    offering_id = f.get("course_offering_id")
    if viewer.role == UserRole.STUDENT.value:
        if student_uid and student_uid != viewer.uid:
            return Page[MarkView](items=[], next_cursor=None)
        student_uid = viewer.uid
        if status is not None and status != MarkStatus.FINAL:
            return Page[MarkView](items=[], next_cursor=None)
        status = MarkStatus.FINAL  # draft marks are not visible to students
    elif viewer.role == UserRole.FACULTY.value:
        if offering_id:
            off = common.fetch(OFFERINGS, offering_id)
            if off is None or off.get("faculty_uid") != viewer.uid:
                return Page[MarkView](items=[], next_cursor=None)
        else:
            owned, _ = common.list_docs(OFFERINGS, [("faculty_uid", viewer.uid)], IN_LIMIT + 1, None)
            if not owned:
                return Page[MarkView](items=[], next_cursor=None)
            if len(owned) > IN_LIMIT:
                raise AcademicValidationError("Too many assigned offerings; filter by course_offering_id.")
            filters.append(("course_offering_id", [o["id"] for o in owned], "in"))
    elif not _admin(viewer.role):
        return Page[MarkView](items=[], next_cursor=None)
    sid = f.get("student_id")
    filters += [
        ("student_id", sid.upper() if sid else None),
        ("student_uid", student_uid),
        ("course_id", f.get("course_id")),
        ("course_offering_id", offering_id),
        ("examination_id", f.get("examination_id")),
        ("semester_id", f.get("semester_id")),
        ("academic_session_id", f.get("academic_session_id")),
        ("grade", f.get("grade")),
        ("status", status.value if status else None),
    ]
    rows, nxt = common.list_docs(MARKS, filters, limit, cursor)
    return Page[MarkView](items=_enrich(rows), next_cursor=nxt)


def regrade_semester(semester_id: str, actor: Actor) -> RegradeResponse:
    """Re-apply the current grading scheme to stored marks of a semester and regenerate its results."""
    scheme = grading.get_scheme()
    rows = collect(MARKS, [("semester_id", semester_id)])
    ts = common.now()
    updated = 0
    students: dict[str, str] = {}
    for r in rows:
        fields = grade_fields(r["percentage"], scheme)
        if fields != {"grade": r.get("grade"), "grade_point": r.get("grade_point")}:
            common.write(MARKS, r["id"], {**fields, "updated_at": ts}, create=False)
            updated += 1
        students[r["student_uid"]] = slug(r["student_id"])
    regenerated = unpublished = 0
    for uid, doc in students.items():
        res = results.regenerate_if_exists(doc, uid, semester_id, actor)
        if res is not None:
            regenerated += 1
            unpublished += int(res.unpublished)
    common.audit(actor, "grading_scheme.regrade", "semester", semester_id, {"marks_updated": updated})
    return RegradeResponse(marks_updated=updated, results_regenerated=regenerated, results_unpublished=unpublished)

