from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.firebase import get_firestore_client

logger = logging.getLogger(__name__)

AUDIT_COLLECTION = "audit_logs"

_SENSITIVE_PARTS = ("password", "token", "secret", "privatekey", "credential", "authorization", "apikey")


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_metadata(value)
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return value


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop sensitive keys, including camelCase/hyphen variants and nested lists."""
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        normalized = "".join(c for c in str(key).lower() if c.isalnum())
        if any(part in normalized for part in _SENSITIVE_PARTS):
            continue
        clean[str(key)] = _sanitize_value(value)
    return clean


def record_audit_event(
    *,
    actor_uid: str | None,
    actor_role: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Best-effort audit write to audit_logs. Never raises; returns success."""
    event = {
        "actor_uid": actor_uid,
        "actor_role": actor_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "timestamp": datetime.now(timezone.utc),
        "metadata": sanitize_metadata(metadata),
    }
    try:
        get_firestore_client().collection(AUDIT_COLLECTION).add(event)
        return True
    except Exception as exc:
        logger.error("Audit write failed (%s).", type(exc).__name__)
        return False

