from __future__ import annotations

from app.core.errors import AcademicConflictError, AcademicNotFoundError, AcademicValidationError, InvalidDateRangeError
from app.schemas.academic import AcademicSession, AcademicSessionCreate, AcademicSessionUpdate, Page
from app.services import academic_common as common
from app.services.academic_common import Actor
from app.services.departments_programs import _apply, slug

SESSIONS = "academic_sessions"


def create_session(payload: AcademicSessionCreate, actor: Actor) -> AcademicSession:
    doc_id = slug(payload.name)
    if not doc_id:
        raise AcademicValidationError("Session name must contain letters or digits.")
    ts = common.now()
    data = {**payload.model_dump(), "is_active": True, "created_at": ts, "updated_at": ts}
    # At most one current session: creating a current one clears the others atomically.
    common.write(
        SESSIONS,
        doc_id,
        data,
        create=True,
        conflict_message="An academic session with this name already exists.",
        clear_current_where=[] if payload.is_current else None,
    )
    common.audit(actor, "academic_session.create", "academic_session", doc_id, {"name": payload.name})
    return AcademicSession(id=doc_id, **data)


def get_session(session_id: str, *, include_inactive: bool = True) -> AcademicSession:
    row = common.fetch(SESSIONS, session_id)
    if row is None or (not include_inactive and not row.get("is_active", True)):
        raise AcademicNotFoundError("Academic session not found.")
    return AcademicSession(**row)


def list_sessions(
    *, is_active: bool | None, is_current: bool | None, limit: int, cursor: str | None
) -> Page[AcademicSession]:
    rows, nxt = common.list_docs(SESSIONS, [("is_active", is_active), ("is_current", is_current)], limit, cursor)
    return Page[AcademicSession](items=[AcademicSession(**r) for r in rows], next_cursor=nxt)


def update_session(session_id: str, payload: AcademicSessionUpdate, actor: Actor) -> AcademicSession:
    current = get_session(session_id)
    changes = payload.model_dump(exclude_unset=True)
    for key in ("start_date", "end_date", "is_current", "is_active"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    start = changes.get("start_date", current.start_date)
    end = changes.get("end_date", current.end_date)
    if start >= end:
        raise InvalidDateRangeError("start_date must be before end_date.")
    if changes.get("is_active") is False and "is_current" not in changes:
        changes["is_current"] = False  # deactivation clears current
    if changes.get("is_current", current.is_current) and not changes.get("is_active", current.is_active):
        raise AcademicValidationError("An inactive session cannot be the current session.")
    if changes.get("is_current") and not current.is_current:
        _write_becoming_current(session_id, changes)
        common.audit(actor, "academic_session.update", "academic_session", session_id, {"fields": sorted(changes)})
        return AcademicSession(**{**current.model_dump(), **changes})
    return _apply(SESSIONS, session_id, current, changes, AcademicSession, actor, "academic_session")


def _write_becoming_current(session_id: str, changes: dict) -> None:
    changes["updated_at"] = common.now()
    common.write(SESSIONS, session_id, changes, create=False, clear_current_where=[])


__all__ = [
    "AcademicConflictError",
    "create_session",
    "get_session",
    "list_sessions",
    "update_session",
]

