from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLog(BaseModel):
    """audit_logs/{audit_id}. Metadata is sanitized at write time (no secrets/tokens/passwords)."""

    id: str
    audit_id: str
    actor_uid: str | None = None
    actor_role: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
