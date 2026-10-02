from __future__ import annotations

from typing import Any

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError
from app.schemas.academic import Page
from app.schemas.people import Student, StudentCreate, StudentUpdate
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor
from app.services.departments_programs import get_department, get_program, slug
from app.services.semesters import get_semester
from app.services.user_links import load_linkable_user

STUDENTS = "students"
USERS = "users"


def _validate_academics(department_id: str, program_id: str, semester_id: str | None) -> None:
    """Verify the academic relationships against stored data (404 missing, 400 inconsistent)."""
    department = get_department(department_id)
    program = get_program(program_id)
    semester = get_semester(semester_id) if semester_id else None
    if program.department_id != department.id:
        raise AcademicValidationError("Program does not belong to the specified department.")
    if semester is not None and semester.program_id != program.id:
        raise AcademicValidationError("Semester does not belong to the student's program.")
    for label, active in (("Department", department.is_active), ("Program", program.is_active),
                          ("Semester", semester.is_active if semester else True)):
        if not active:
            raise AcademicValidationError(f"{label} is not active.")


def _user_sync(student: dict[str, Any], ts) -> dict[str, Any]:
    """Fields mirrored onto users/{uid} so existing role-aware code (e.g. offering visibility) works."""
    return {
        "student_id": student["student_id"],
        "department_id": student["department_id"],
        "program_id": student["program_id"],
        "semester_id": student.get("current_semester_id"),
        "updated_at": ts,
    }


def create_student(payload: StudentCreate, actor: Actor) -> Student:
    _validate_academics(payload.department_id, payload.program_id, payload.current_semester_id)
    user = load_linkable_user(payload.uid, UserRole.STUDENT, "student_id", payload.student_id)
    existing, _ = common.list_docs(STUDENTS, [("uid", payload.uid)], 1, None)
    if existing:
        raise AcademicConflictError("This user already has a student profile.")
    doc_id = slug(payload.student_id)
    ts = common.now()
    data = {
        **payload.model_dump(mode="json"),
        "email": user.email,
        "display_name": user.display_name,
        "is_active": True,
        "created_at": ts,
        "updated_at": ts,
    }
    # One atomic batch: student doc (create fails if student_id exists) + users/{uid} link.
    common.commit_batch(
        [("create", STUDENTS, doc_id, data), ("update", USERS, payload.uid, _user_sync(data, ts))],
        "A student with this student_id already exists.",
    )
    common.audit(actor, "student.create", "student", doc_id, {"uid": payload.uid})
    return Student(id=doc_id, **data)


def get_student(student_doc_id: str) -> Student:
    row = common.fetch(STUDENTS, student_doc_id)
    if row is None:
        raise AcademicNotFoundError("Student not found.")
    return Student(**row)


def get_student_for_viewer(student_doc_id: str, viewer_uid: str, role: str | None) -> Student:
    student = get_student(slug(student_doc_id))
    if role != UserRole.ADMIN.value and student.uid != viewer_uid:
        raise AcademicNotFoundError("Student not found.")  # do not reveal other students
    return student


def get_student_by_uid(uid: str) -> Student:
    rows, _ = common.list_docs(STUDENTS, [("uid", uid)], 1, None)
    if not rows:
        raise AcademicNotFoundError("Student profile not found.")
    return Student(**rows[0])


def list_students(*, department_id, program_id, semester_id, section, batch, is_active, limit, cursor) -> Page[Student]:
    rows, nxt = common.list_docs(
        STUDENTS,
        [("department_id", department_id), ("program_id", program_id), ("current_semester_id", semester_id),
         ("section", section.upper() if section else None), ("batch", batch), ("is_active", is_active)],
        limit,
        cursor,
    )
    return Page[Student](items=[Student(**r) for r in rows], next_cursor=nxt)


def update_student(student_doc_id: str, payload: StudentUpdate, actor: Actor) -> Student:
    doc_id = slug(student_doc_id)
    current = get_student(doc_id)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    for key in ("department_id", "program_id", "admission_year", "is_active"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    if not changes:
        return current
    merged = {**current.model_dump(mode="json"), **changes}
    _validate_academics(merged["department_id"], merged["program_id"], merged["current_semester_id"])
    ts = common.now()
    changes["updated_at"] = ts
    merged["updated_at"] = ts
    common.commit_batch(
        [("update", STUDENTS, doc_id, changes), ("update", USERS, current.uid, _user_sync(merged, ts))],
        "Conflict while updating the student.",
    )
    common.audit(actor, "student.update", "student", doc_id, {"fields": sorted(k for k in changes if k != "updated_at")})
    return Student(**{**current.model_dump(), **changes})
