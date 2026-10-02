from __future__ import annotations

from typing import Any

from app.core.errors import AcademicNotFoundError, AcademicValidationError
from app.core.firebase import get_auth_account_status
from app.schemas.academic import Page
from app.schemas.courses import CourseOffering, OfferingCreate, OfferingStatus, OfferingUpdate
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor, Viewer
from app.services.academic_sessions import get_session
from app.services.courses import get_course
from app.services.departments_programs import _apply, get_department, get_program
from app.services.semesters import get_semester
from app.services.users import get_user_profile

OFFERINGS = "course_offerings"
OPEN_STATUSES = [OfferingStatus.PLANNED.value, OfferingStatus.ACTIVE.value]
STUDENT_VISIBLE = [OfferingStatus.PLANNED.value, OfferingStatus.ACTIVE.value, OfferingStatus.COMPLETED.value]


def offering_id(course_id: str, semester_id: str, section: str) -> str:
    return f"{course_id}__{semester_id}__{section.lower()}"


def _resolve_faculty(faculty_uid: str) -> tuple[str, str | None]:
    """Verify the account exists, is enabled, and is an active FACULTY user."""
    disabled = get_auth_account_status(faculty_uid)
    if disabled is None:
        raise AcademicNotFoundError("Faculty user not found.")
    profile = get_user_profile(faculty_uid)
    if profile is None:
        raise AcademicNotFoundError("Faculty user not found.")
    if profile.role != UserRole.FACULTY:
        raise AcademicValidationError("Assigned user is not a FACULTY member.")
    if disabled or not profile.is_active:
        raise AcademicValidationError("Assigned faculty account is not active.")
    return profile.uid, profile.faculty_id


def create_offering(payload: OfferingCreate, actor: Actor) -> CourseOffering:
    course = get_course(payload.course_id)  # 404
    semester = get_semester(payload.semester_id)  # 404
    # Existence of any client-supplied references first (404), then consistency (400).
    if payload.academic_session_id:
        get_session(payload.academic_session_id)
    if payload.program_id:
        get_program(payload.program_id)
    if payload.department_id:
        get_department(payload.department_id)
    session = get_session(semester.academic_session_id)
    program = get_program(semester.program_id)

    if payload.academic_session_id and payload.academic_session_id != semester.academic_session_id:
        raise AcademicValidationError("Semester does not belong to the specified academic session.")
    if payload.program_id and payload.program_id != semester.program_id:
        raise AcademicValidationError("Semester does not belong to the specified program.")
    if course.program_id != program.id:
        raise AcademicValidationError("Course does not belong to the semester's program.")
    if payload.department_id and payload.department_id != course.department_id:
        raise AcademicValidationError("Course does not belong to the specified department.")
    if course.semester_number != semester.semester_number:
        raise AcademicValidationError("Course semester_number does not match the semester.")
    for label, active in (("Course", course.is_active), ("Semester", semester.is_active),
                          ("Academic session", session.is_active), ("Program", program.is_active)):
        if not active:
            raise AcademicValidationError(f"{label} is not active.")

    faculty_uid = faculty_id = None
    if payload.faculty_uid:
        faculty_uid, faculty_id = _resolve_faculty(payload.faculty_uid)

    doc_id = offering_id(course.id, semester.id, payload.section)
    ts = common.now()
    data = {
        "course_id": course.id,
        "academic_session_id": session.id,
        "semester_id": semester.id,
        "program_id": program.id,
        "department_id": course.department_id,
        "section": payload.section,
        "faculty_uid": faculty_uid,
        "faculty_id": faculty_id,
        "room": payload.room,
        "capacity": payload.capacity,
        "status": payload.status.value,
        "created_at": ts,
        "updated_at": ts,
    }
    # Deterministic id => create() enforces course + semester + section uniqueness.
    common.write(OFFERINGS, doc_id, data, create=True,
                 conflict_message="This course is already offered for the semester and section.")
    common.audit(actor, "course_offering.create", "course_offering", doc_id, {"course_id": course.id})
    return CourseOffering(id=doc_id, **data)


def _visible(viewer: Viewer, off: CourseOffering) -> bool:
    if viewer.role == UserRole.ADMIN.value:
        return True
    if viewer.role == UserRole.FACULTY.value:
        return off.faculty_uid == viewer.uid
    if viewer.role == UserRole.STUDENT.value:
        if not viewer.program_id or off.program_id != viewer.program_id:
            return False
        if viewer.semester_id and off.semester_id != viewer.semester_id:
            return False
        return off.status.value in STUDENT_VISIBLE
    return False


def get_offering(offering_id_: str, viewer: Viewer | None = None) -> CourseOffering:
    row = common.fetch(OFFERINGS, offering_id_)
    if row is None:
        raise AcademicNotFoundError("Course offering not found.")
    off = CourseOffering(**row)
    if viewer is not None and not _visible(viewer, off):
        raise AcademicNotFoundError("Course offering not found.")
    return off


def list_offerings(
    *,
    viewer: Viewer,
    course_id: str | None,
    academic_session_id: str | None,
    semester_id: str | None,
    program_id: str | None,
    department_id: str | None,
    faculty_uid: str | None,
    section: str | None,
    status: OfferingStatus | None,
    limit: int,
    cursor: str | None,
) -> Page[CourseOffering]:
    filters: list[tuple] = []
    if viewer.role == UserRole.FACULTY.value:
        faculty_uid = viewer.uid  # forced: faculty only ever see their own offerings
    elif viewer.role == UserRole.STUDENT.value:
        if not viewer.program_id:
            return Page[CourseOffering](items=[], next_cursor=None)
        program_id = viewer.program_id
        if viewer.semester_id:
            semester_id = viewer.semester_id
        filters.append(("status", STUDENT_VISIBLE if status is None else
                        ([status.value] if status.value in STUDENT_VISIBLE else ["__none__"]), "in"))
        status = None
    elif viewer.role != UserRole.ADMIN.value:
        return Page[CourseOffering](items=[], next_cursor=None)
    filters += [
        ("course_id", course_id),
        ("academic_session_id", academic_session_id),
        ("semester_id", semester_id),
        ("program_id", program_id),
        ("department_id", department_id),
        ("faculty_uid", faculty_uid),
        ("section", section.upper() if section else None),
        ("status", status.value if status else None),
    ]
    rows, nxt = common.list_docs(OFFERINGS, filters, limit, cursor)
    return Page[CourseOffering](items=[CourseOffering(**r) for r in rows], next_cursor=nxt)


def update_offering(offering_id_: str, payload: OfferingUpdate, actor: Actor) -> CourseOffering:
    current = get_offering(offering_id_)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    if "status" in changes and changes["status"] is None:
        raise AcademicValidationError("status cannot be null.")
    if "faculty_uid" in changes:
        if changes["faculty_uid"] is None:
            changes["faculty_id"] = None
        else:
            changes["faculty_uid"], changes["faculty_id"] = _resolve_faculty(changes["faculty_uid"])
    return _apply(OFFERINGS, offering_id_, current, changes, CourseOffering, actor, "course_offering")


def has_open_offerings(course_id: str) -> bool:
    rows, _ = common.list_docs(OFFERINGS, [("course_id", course_id), ("status", OPEN_STATUSES, "in")], 1, None)
    return bool(rows)
