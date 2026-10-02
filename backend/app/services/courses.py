from __future__ import annotations

from typing import Any

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError, UnprocessableAcademicError
from app.schemas.academic import Page
from app.schemas.courses import Course, CourseCreate, CourseType, CourseUpdate
from app.services import academic_common as common
from app.services.academic_common import Actor
from app.services.departments_programs import _apply, get_department, get_program, slug

COURSES = "courses"


def create_course(payload: CourseCreate, actor: Actor) -> Course:
    # Relationships are verified against stored data, never trusted from the client.
    department = get_department(payload.department_id)  # 404
    program = get_program(payload.program_id)  # 404
    if program.department_id != department.id:
        raise AcademicValidationError("Program does not belong to the specified department.")
    if not department.is_active:
        raise AcademicValidationError("Department is not active.")
    if not program.is_active:
        raise AcademicValidationError("Program is not active.")
    if payload.semester_number > program.total_semesters:
        raise AcademicValidationError("semester_number exceeds the program's total_semesters.")
    doc_id = slug(payload.code)
    ts = common.now()
    data = {
        **payload.model_dump(mode="json"),
        "department_id": department.id,
        "program_id": program.id,
        "is_active": True,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(COURSES, doc_id, data, create=True, conflict_message="A course with this code already exists.")
    common.audit(actor, "course.create", "course", doc_id, {"code": payload.code})
    return Course(id=doc_id, **data)


def get_course(course_id: str, *, include_inactive: bool = True) -> Course:
    row = common.fetch(COURSES, course_id)
    if row is None or (not include_inactive and not row.get("is_active", True)):
        raise AcademicNotFoundError("Course not found.")
    return Course(**row)


def list_courses(
    *,
    department_id: str | None,
    program_id: str | None,
    semester_number: int | None,
    course_type: CourseType | None,
    is_active: bool | None,
    code_prefix: str | None,
    limit: int,
    cursor: str | None,
) -> Page[Course]:
    filters: list[tuple] = [
        ("department_id", department_id),
        ("program_id", program_id),
        ("semester_number", semester_number),
        ("course_type", course_type.value if course_type else None),
        ("is_active", is_active),
    ]
    order = "__name__"
    if code_prefix:
        # Prefix search on the (upper-cased) code via an indexed range query.
        prefix = code_prefix.upper()
        filters += [("code", prefix, ">="), ("code", prefix + "\uf8ff", "<=")]
        order = "code"
    rows, nxt = common.list_docs(COURSES, filters, limit, cursor, order_by=order)
    return Page[Course](items=[Course(**r) for r in rows], next_cursor=nxt)


def update_course(course_id: str, payload: CourseUpdate, actor: Actor) -> Course:
    from app.services import course_offerings as offering_service

    current = get_course(course_id)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    for key in ("name", "credits", "course_type", "max_marks", "passing_marks", "is_active"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    if changes.get("passing_marks", current.passing_marks) > changes.get("max_marks", current.max_marks):
        raise UnprocessableAcademicError("passing_marks must not exceed max_marks.")
    if changes.get("is_active") is False and current.is_active and offering_service.has_open_offerings(course_id):
        raise AcademicConflictError("Course has planned or active offerings; cancel or complete them first.")
    return _apply(COURSES, course_id, current, changes, Course, actor, "course")
