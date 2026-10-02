"""Shared Firestore helpers for the academic-structure services."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, NamedTuple

from google.api_core.exceptions import AlreadyExists

from app.core.errors import AcademicConflictError
from app.core.firebase import get_firestore_client
from app.services.audit import record_audit_event

MAX_PAGE_SIZE = 100


class Actor(NamedTuple):
    uid: str | None
    role: str | None


class Viewer(NamedTuple):
    """Trusted identity of the caller (derived server-side from the auth context)."""

    uid: str
    role: str | None
    program_id: str | None = None
    semester_id: str | None = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def to_doc(data: dict[str, Any]) -> dict[str, Any]:
    """Firestore has no date type: store dates as ISO strings (sortable)."""
    return {k: (v.isoformat() if isinstance(v, date) and not isinstance(v, datetime) else v) for k, v in data.items()}


def fetch(collection: str, doc_id: str) -> dict[str, Any] | None:
    snap = get_firestore_client().collection(collection).document(doc_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    data["id"] = doc_id
    return data


def write(
    collection: str,
    doc_id: str,
    data: dict[str, Any],
    *,
    create: bool,
    conflict_message: str = "Record already exists.",
    clear_current_where: list[tuple[str, Any]] | None = None,
) -> None:
    """Atomically create/update one document, optionally unsetting `is_current`
    on sibling documents (those matching `clear_current_where`) in the same batch.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    client = get_firestore_client()
    batch = client.batch()
    col = client.collection(collection)
    ref = col.document(doc_id)
    if clear_current_where is not None:
        query = col.where(filter=FieldFilter("is_current", "==", True))
        for field, value in clear_current_where:
            query = query.where(filter=FieldFilter(field, "==", value))
        for snap in query.stream():
            if snap.id != doc_id:
                batch.update(snap.reference, {"is_current": False, "updated_at": data["updated_at"]})
    if create:
        batch.create(ref, to_doc(data))
    else:
        batch.update(ref, to_doc(data))
    try:
        batch.commit()
    except AlreadyExists:
        raise AcademicConflictError(conflict_message) from None


def list_docs(
    collection: str,
    filters: list[tuple],
    limit: int,
    cursor: str | None,
    order_by: str = "__name__",
) -> tuple[list[dict[str, Any]], str | None]:
    """Filtered, ordered, cursor-paginated listing. Filters are (field, value[, op]); op defaults to "==".

    Equality-only lists default to document-ID order. Range queries default to
    their inequality field. Validate composite indexes for actual filter combinations.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    limit = max(1, min(limit, MAX_PAGE_SIZE))
    col = get_firestore_client().collection(collection)
    query = col
    for flt in filters:
        field, value = flt[0], flt[1]
        op = flt[2] if len(flt) > 2 else "=="
        if value is not None:
            query = query.where(filter=FieldFilter(field, op, value))
    if order_by == "__name__":
        # Firestore requires the first ordering to match a range/inequality field.
        order_by = next(
            (flt[0] for flt in filters
             if len(flt) > 2 and flt[1] is not None and flt[2] in ("<", "<=", ">", ">=", "!=", "not-in")),
            order_by,
        )
    query = query.order_by(order_by)
    if cursor:
        cursor_snap = col.document(cursor).get()
        if cursor_snap.exists:
            query = query.start_after(cursor_snap)
    snaps = list(query.limit(limit + 1).stream())
    rows = []
    for snap in snaps[:limit]:
        row = snap.to_dict() or {}
        row["id"] = snap.id
        rows.append(row)
    next_cursor = snaps[limit - 1].id if len(snaps) > limit else None
    return rows, next_cursor


def count_docs(collection: str, filters: list[tuple]) -> int:
    """Server-side COUNT aggregation (no documents are read). Filters as in `list_docs`."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = get_firestore_client().collection(collection)
    for flt in filters:
        field, value = flt[0], flt[1]
        op = flt[2] if len(flt) > 2 else "=="
        if value is not None:
            query = query.where(filter=FieldFilter(field, op, value))
    return int(query.count().get()[0][0].value)


MAX_SCAN = 2000


def drain(fn, *, cap: int = MAX_SCAN, **kwargs) -> list:
    """Collect every item of a cursor-paginated service function (bounded)."""
    from app.core.errors import AcademicValidationError

    items: list = []
    cursor = None
    while True:
        page = fn(limit=MAX_PAGE_SIZE, cursor=cursor, **kwargs)
        items.extend(page.items)
        if len(items) > cap:
            raise AcademicValidationError("Too many records; narrow the filters.")
        if page.next_cursor is None:
            return items
        cursor = page.next_cursor


def audit(actor: Actor, action: str, resource_type: str, resource_id: str, metadata: dict[str, Any] | None = None) -> None:
    record_audit_event(
        actor_uid=actor.uid,
        actor_role=actor.role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata,
    )



def commit_batch(ops: list[tuple[str, str, str, dict[str, Any]]], conflict_message: str) -> None:
    """Atomically apply ("create"|"update", collection, doc_id, data) operations.

    A "create" on an existing document aborts the whole batch with a conflict,
    so related documents are never left half-written.
    """
    client = get_firestore_client()
    batch = client.batch()
    for kind, collection, doc_id, data in ops:
        ref = client.collection(collection).document(doc_id)
        if kind == "create":
            batch.create(ref, to_doc(data))
        else:
            batch.update(ref, to_doc(data))
    try:
        batch.commit()
    except AlreadyExists:
        raise AcademicConflictError(conflict_message) from None


