from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.audit import AuditLog
from app.schemas.academic import Page
from app.services import academic_common as common

AUDIT = "audit_logs"


def list_audit_logs(*, actor_uid, actor_role, action, resource_type, resource_id,
                    from_time: datetime | None, to_time: datetime | None, limit: int, cursor: str | None) -> Page[AuditLog]:
    """Document-ID order by default; timestamp order when a time range is supplied."""
    from app.core.errors import UnprocessableAcademicError

    # Audit timestamps are UTC. Treat offset-free query values as UTC too.
    if from_time is not None and from_time.tzinfo is None:
        from_time = from_time.replace(tzinfo=timezone.utc)
    if to_time is not None and to_time.tzinfo is None:
        to_time = to_time.replace(tzinfo=timezone.utc)
    if from_time and to_time and from_time > to_time:
        raise UnprocessableAcademicError("from must not be after to.")
    filters: list[tuple] = [("actor_uid", actor_uid), ("actor_role", actor_role.upper() if actor_role else None),
                            ("action", action), ("resource_type", resource_type), ("resource_id", resource_id)]
    order = "__name__"
    if from_time or to_time:
        filters += [("timestamp", from_time, ">="), ("timestamp", to_time, "<=")]
        order = "timestamp"
    rows, nxt = common.list_docs(AUDIT, filters, limit, cursor, order_by=order)
    return Page[AuditLog](items=[AuditLog(audit_id=r["id"], **r) for r in rows], next_cursor=nxt)
