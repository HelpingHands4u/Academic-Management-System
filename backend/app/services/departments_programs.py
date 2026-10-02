from __future__ import annotations

import re
from typing import Any

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError
from app.schemas.academic import (
    Department,
    DepartmentCreate,
    DepartmentUpdate,
    Page,
    Program,
    ProgramCreate,
    ProgramUpdate,
)
from app.services import academic_common as common
from app.services.academic_common import Actor

DEPARTMENTS = "departments"
PROGRAMS = "programs"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")


# ---- Departments ----------------------------------------------------------
def create_department(payload: DepartmentCreate, actor: Actor) -> Department:
    # The id is derived server-side from the unique code, so Firestore's
    # create() enforces code uniqueness atomically.
    doc_id = slug(payload.code)
    ts = common.now()
    data = {
        "name": payload.name,
        "code": payload.code,
        "description": payload.description,
        "is_active": True,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(DEPARTMENTS, doc_id, data, create=True, conflict_message="A department with this code already exists.")
    common.audit(actor, "department.create", "department", doc_id, {"code": payload.code})
    return Department(id=doc_id, **data)


def get_department(department_id: str, *, include_inactive: bool = True) -> Department:
    row = common.fetch(DEPARTMENTS, department_id)
    if row is None or (not include_inactive and not row.get("is_active", True)):
        raise AcademicNotFoundError("Department not found.")
    return Department(**row)


def list_departments(*, is_active: bool | None, limit: int, cursor: str | None) -> Page[Department]:
    rows, nxt = common.list_docs(DEPARTMENTS, [("is_active", is_active)], limit, cursor)
    return Page[Department](items=[Department(**r) for r in rows], next_cursor=nxt)


def update_department(department_id: str, payload: DepartmentUpdate, actor: Actor) -> Department:
    current = get_department(department_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_active") is False and current.is_active:
        rows, _ = common.list_docs(PROGRAMS, [("department_id", department_id), ("is_active", True)], 1, None)
        if rows:
            raise AcademicConflictError("Department has active programs; deactivate them first.")
    return _apply(DEPARTMENTS, department_id, current, changes, Department, actor, "department")


# ---- Programs -------------------------------------------------------------
def _require_active_department(department_id: str) -> None:
    dept = get_department(department_id)  # 404 if missing
    if not dept.is_active:
        raise AcademicValidationError("Department is not active.")


def create_program(payload: ProgramCreate, actor: Actor) -> Program:
    _require_active_department(payload.department_id)
    doc_id = slug(payload.code)
    ts = common.now()
    data = {**payload.model_dump(), "is_active": True, "created_at": ts, "updated_at": ts}
    common.write(PROGRAMS, doc_id, data, create=True, conflict_message="A program with this code already exists.")
    common.audit(actor, "program.create", "program", doc_id, {"code": payload.code})
    return Program(id=doc_id, **data)


def get_program(program_id: str, *, include_inactive: bool = True) -> Program:
    row = common.fetch(PROGRAMS, program_id)
    if row is None or (not include_inactive and not row.get("is_active", True)):
        raise AcademicNotFoundError("Program not found.")
    return Program(**row)


def list_programs(
    *, department_id: str | None, is_active: bool | None, limit: int, cursor: str | None
) -> Page[Program]:
    rows, nxt = common.list_docs(
        PROGRAMS, [("department_id", department_id), ("is_active", is_active)], limit, cursor
    )
    return Page[Program](items=[Program(**r) for r in rows], next_cursor=nxt)


def update_program(program_id: str, payload: ProgramUpdate, actor: Actor) -> Program:
    from app.services import semesters as semester_service

    current = get_program(program_id)
    changes = payload.model_dump(exclude_unset=True)
    if "department_id" in changes and changes["department_id"] != current.department_id:
        _require_active_department(changes["department_id"])
    total = changes.get("total_semesters", current.total_semesters)
    if total < semester_service.max_semester_number(program_id):
        raise AcademicValidationError("total_semesters is lower than an existing semester number.")
    if changes.get("is_active") is False and current.is_active and semester_service.has_active_semesters(program_id):
        raise AcademicConflictError("Program has active semesters; deactivate them first.")
    return _apply(PROGRAMS, program_id, current, changes, Program, actor, "program")


def _apply(collection: str, doc_id: str, current: Any, changes: dict[str, Any], model: Any, actor: Actor, kind: str):
    if not changes:
        return current
    changes = {**changes, "updated_at": common.now()}
    common.write(collection, doc_id, changes, create=False)
    common.audit(actor, f"{kind}.update", kind, doc_id, {"fields": sorted(k for k in changes if k != "updated_at")})
    return model(**{**current.model_dump(), **changes})
