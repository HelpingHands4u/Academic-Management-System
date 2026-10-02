from __future__ import annotations

import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import AcademicConflictError, AcademicNotFoundError
from app.schemas.sessions import SessionCreate, SessionStarted, UserSession
from app.services import academic_common as common
from app.services.audit import sanitize_metadata

SESSIONS = "user_sessions"


def windows() -> tuple[int, int]:
    """(active_window_seconds, recent_window_seconds); single accessor so it is configurable/testable."""
    s = get_settings()
    return s.session_active_window_seconds, s.session_recent_window_seconds


def start_session(viewer: common.Viewer, payload: SessionCreate | None, user_agent: str | None) -> SessionStarted:
    ts = common.now()
    sid = f"ss_{uuid.uuid4().hex}"
    data = {
        "session_id": sid, "uid": viewer.uid, "role": viewer.role,  # identity comes from the verified token only
        "login_at": ts, "last_seen_at": ts, "logout_at": None, "is_active": True,
        "user_agent": (user_agent or "")[:300] or None,
        "metadata": sanitize_metadata(payload.metadata if payload else {}),
        "created_at": ts, "updated_at": ts,
    }
    common.write(SESSIONS, sid, data, create=True, conflict_message="Session already exists.")
    return SessionStarted(**data)


def _owned(session_id: str, viewer: common.Viewer) -> dict[str, Any]:
    row = common.fetch(SESSIONS, session_id)
    if row is None or (viewer.role != "ADMIN" and row.get("uid") != viewer.uid):
        raise AcademicNotFoundError("Session not found.")  # do not reveal other users' sessions
    return row


def heartbeat(session_id: str, viewer: common.Viewer) -> UserSession:
    row = _owned(session_id, viewer)
    if not row.get("is_active"):
        raise AcademicConflictError("Session is closed.")
    ts = common.now()
    common.write(SESSIONS, session_id, {"last_seen_at": ts, "updated_at": ts}, create=False)
    return UserSession(**{**row, "last_seen_at": ts, "updated_at": ts})


def logout(session_id: str, viewer: common.Viewer) -> UserSession:
    """Idempotent: logging out an already-closed session returns it unchanged."""
    row = _owned(session_id, viewer)
    if not row.get("is_active"):
        return UserSession(**row)
    ts = common.now()
    changes = {"logout_at": ts, "is_active": False, "updated_at": ts}
    common.write(SESSIONS, session_id, changes, create=False)
    return UserSession(**{**row, **changes})
