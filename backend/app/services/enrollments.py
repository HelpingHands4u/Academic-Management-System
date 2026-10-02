from __future__ import annotations

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError
from app.schemas.academic import Page
from app.schemas.courses import OfferingStatus
from app.schemas.people import Enrollment, EnrollmentCreate, EnrollmentStatus, EnrollmentUpdate
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor, Viewer
from app.services.course_offerings import OFFERINGS
from app.services.courses import get_course
from app.services.departments_programs import slug
from app.services.students import get_student

ENROLLMENTS = "enrollments"
ENROLLABLE = {OfferingStatus.PLANNED.value, OfferingStatus.ACTIVE.value}
IN_LIMIT = 30  # Firestore `in` operator limit

_TRANSITIONS = {
    EnrollmentStatus.ACTIVE: {EnrollmentStatus.DROPPED, EnrollmentStatus.COMPLETED},
    EnrollmentStatus.DROPPED: {EnrollmentStatus.ACTIVE},
    EnrollmentStatus.COMPLETED: set(),
}


def enrollment_id(student_doc_id: str, offering_id: str) -> str:
    return f"{student_doc_id}__{offering_id}"


def _validated_context(student_doc_id: str, offering_id: str):
    """Load and validate student, offering and course; returns (student, offering_row)."""
    student = get_student(student_doc_id)  # 404
    offering = common.fetch(OFFERINGS, offering_id)
    if offering is None:
        raise AcademicNotFoundError("Course offering not found.")
    course = get_course(offering["course_id"])  # 404
    if not student.is_active:
        raise AcademicValidationError("Student is not active.")
    if offering.get("status") not in ENROLLABLE:
        raise AcademicValidationError("Course offering is not open for enrollment.")
    if not course.is_active:
        raise AcademicValidationError("Course is not active.")
    if student.program_id != offering["program_id"]:
        raise AcademicValidationError("Student's program does not match the course offering.")
    if student.current_semester_id and student.current_semester_id != offering["semester_id"]:
        raise AcademicValidationError("Student's current semester does not match the course offering.")
    if student.section and offering.get("section") and student.section != offering["section"]:
        raise AcademicValidationError("Student's section does not match the course offering.")
    return student, offering


def create_enrollment(payload: EnrollmentCreate, actor: Actor) -> Enrollment:
    student_doc_id = slug(payload.student_id)
    student, offering = _validated_context(student_doc_id, payload.course_offering_id)
    doc_id = enrollment_id(student_doc_id, payload.course_offering_id)
    ts = common.now()
    existing = common.fetch(ENROLLMENTS, doc_id)
    if existing is not None:
        if existing.get("status") != EnrollmentStatus.DROPPED.value:
            raise AcademicConflictError("Student is already enrolled in this course offering.")
        # Re-enrolling after a drop reactivates the same record.
        changes = {"status": EnrollmentStatus.ACTIVE.value, "enrolled_at": ts, "dropped_at": None, "updated_at": ts}
        common.write(ENROLLMENTS, doc_id, changes, create=False)
        common.audit(actor, "enrollment.reenroll", "enrollment", doc_id, {"offering": payload.course_offering_id})
        return Enrollment(**{**existing, **changes})
    data = {
        "student_uid": student.uid,
        "student_id": student.student_id,
        "course_offering_id": payload.course_offering_id,
        "course_id": offering["course_id"],
        "academic_session_id": offering["academic_session_id"],
        "semester_id": offering["semester_id"],
        "program_id": offering["program_id"],
        "section": offering.get("section"),
        "status": EnrollmentStatus.ACTIVE.value,
        "enrolled_at": ts,
        "dropped_at": None,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(ENROLLMENTS, doc_id, data, create=True,
                 conflict_message="Student is already enrolled in this course offering.")
    common.audit(actor, "enrollment.create", "enrollment", doc_id, {"offering": payload.course_offering_id})
    return Enrollment(id=doc_id, **data)


def _can_view(viewer: Viewer, row: dict) -> bool:
    if viewer.role == UserRole.ADMIN.value:
        return True
    if viewer.role == UserRole.STUDENT.value:
        return row.get("student_uid") == viewer.uid
    if viewer.role == UserRole.FACULTY.value:
        offering = common.fetch(OFFERINGS, row.get("course_offering_id", ""))
        return offering is not None and offering.get("faculty_uid") == viewer.uid
    return False


def get_enrollment(enrollment_id_: str, viewer: Viewer | None = None) -> Enrollment:
    row = common.fetch(ENROLLMENTS, enrollment_id_)
    if row is None or (viewer is not None and not _can_view(viewer, row)):
        raise AcademicNotFoundError("Enrollment not found.")
    return Enrollment(**row)


def list_enrollments(
    *,
    viewer: Viewer,
    student_id: str | None,
    student_uid: str | None,
    course_offering_id: str | None,
    course_id: str | None,
    semester_id: str | None,
    status: EnrollmentStatus | None,
    limit: int,
    cursor: str | None,
) -> Page[Enrollment]:
    filters: list[tuple] = []
    empty = Page[Enrollment](items=[], next_cursor=None)
    if viewer.role == UserRole.STUDENT.value:
        student_uid = viewer.uid  # forced: students only ever see their own
    elif viewer.role == UserRole.FACULTY.value:
        if course_offering_id:
            offering = common.fetch(OFFERINGS, course_offering_id)
            if offering is None or offering.get("faculty_uid") != viewer.uid:
                return empty
        else:
            owned, _ = common.list_docs(OFFERINGS, [("faculty_uid", viewer.uid)], IN_LIMIT + 1, None)
            if not owned:
                return empty
            if len(owned) > IN_LIMIT:
                raise AcademicValidationError("Too many assigned offerings; filter by course_offering_id.")
            filters.append(("course_offering_id", [o["id"] for o in owned], "in"))
    elif viewer.role != UserRole.ADMIN.value:
        return empty
    filters += [
        ("student_id", student_id.upper() if student_id else None),
        ("student_uid", student_uid),
        ("course_offering_id", course_offering_id),
        ("course_id", course_id),
        ("semester_id", semester_id),
        ("status", status.value if status else None),
    ]
    rows, nxt = common.list_docs(ENROLLMENTS, filters, limit, cursor)
    return Page[Enrollment](items=[Enrollment(**r) for r in rows], next_cursor=nxt)


def update_enrollment(enrollment_id_: str, payload: EnrollmentUpdate, actor: Actor) -> Enrollment:
    current = get_enrollment(enrollment_id_)
    if payload.status == current.status:
        return current
    if payload.status not in _TRANSITIONS[current.status]:
        raise AcademicValidationError(f"Cannot change enrollment from {current.status.value} to {payload.status.value}.")
    ts = common.now()
    changes: dict = {"status": payload.status.value, "updated_at": ts}
    if payload.status == EnrollmentStatus.DROPPED:
        changes["dropped_at"] = ts
    elif payload.status == EnrollmentStatus.ACTIVE:
        # Reactivation must satisfy the same rules as a fresh enrollment.
        _validated_context(slug(current.student_id), current.course_offering_id)
        changes.update({"dropped_at": None, "enrolled_at": ts})
    common.write(ENROLLMENTS, enrollment_id_, changes, create=False)
    common.audit(actor, "enrollment.status", "enrollment", enrollment_id_,
                 {"from": current.status.value, "to": payload.status.value})
    return Enrollment(**{**current.model_dump(), **changes})
