from __future__ import annotations

from typing import Any

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError
from app.schemas.academic import Page
from app.schemas.people import Faculty, FacultyCreate, FacultyUpdate
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor
from app.services.departments_programs import get_department, slug
from app.services.user_links import load_linkable_user

FACULTY = "faculty"
USERS = "users"


def _require_active_department(department_id: str) -> None:
    if not get_department(department_id).is_active:
        raise AcademicValidationError("Department is not active.")


def create_faculty(payload: FacultyCreate, actor: Actor) -> Faculty:
    _require_active_department(payload.department_id)
    user = load_linkable_user(payload.uid, UserRole.FACULTY, "faculty_id", payload.faculty_id)
    existing, _ = common.list_docs(FACULTY, [("uid", payload.uid)], 1, None)
    if existing:
        raise AcademicConflictError("This user already has a faculty profile.")
    doc_id = slug(payload.faculty_id)
    ts = common.now()
    data = {
        **payload.model_dump(mode="json"),
        "email": user.email,
        "display_name": user.display_name,
        "is_active": True,
        "created_at": ts,
        "updated_at": ts,
    }
    common.commit_batch(
        [
            ("create", FACULTY, doc_id, data),
            ("update", USERS, payload.uid,
             {"faculty_id": payload.faculty_id, "department_id": payload.department_id, "updated_at": ts}),
        ],
        "A faculty member with this faculty_id already exists.",
    )
    common.audit(actor, "faculty.create", "faculty", doc_id, {"uid": payload.uid})
    return Faculty(id=doc_id, **data)


def get_faculty(faculty_doc_id: str) -> Faculty:
    row = common.fetch(FACULTY, faculty_doc_id)
    if row is None:
        raise AcademicNotFoundError("Faculty member not found.")
    return Faculty(**row)


def get_faculty_for_viewer(faculty_doc_id: str, viewer_uid: str, role: str | None) -> Faculty:
    member = get_faculty(slug(faculty_doc_id))
    if role != UserRole.ADMIN.value and member.uid != viewer_uid:
        raise AcademicNotFoundError("Faculty member not found.")
    return member


def get_faculty_by_uid(uid: str) -> Faculty:
    rows, _ = common.list_docs(FACULTY, [("uid", uid)], 1, None)
    if not rows:
        raise AcademicNotFoundError("Faculty profile not found.")
    return Faculty(**rows[0])


def list_faculty(*, department_id, designation, is_active, limit, cursor) -> Page[Faculty]:
    rows, nxt = common.list_docs(
        FACULTY, [("department_id", department_id), ("designation", designation), ("is_active", is_active)], limit, cursor
    )
    return Page[Faculty](items=[Faculty(**r) for r in rows], next_cursor=nxt)


def update_faculty(faculty_doc_id: str, payload: FacultyUpdate, actor: Actor) -> Faculty:
    doc_id = slug(faculty_doc_id)
    current = get_faculty(doc_id)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    for key in ("department_id", "is_active"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    if not changes:
        return current
    if "department_id" in changes and changes["department_id"] != current.department_id:
        _require_active_department(changes["department_id"])
    ts = common.now()
    changes["updated_at"] = ts
    merged = {**current.model_dump(), **changes}
    common.commit_batch(
        [
            ("update", FACULTY, doc_id, changes),
            ("update", USERS, current.uid, {"department_id": merged["department_id"], "updated_at": ts}),
        ],
        "Conflict while updating the faculty member.",
    )
    common.audit(actor, "faculty.update", "faculty", doc_id, {"fields": sorted(k for k in changes if k != "updated_at")})
    return Faculty(**merged)
