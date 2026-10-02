from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.academic import _Strict

MAX_METADATA_KEYS = 10
MAX_VALUE_LEN = 200


class SessionCreate(_Strict):
    """Optional body. uid and role are never accepted: they come from the verified ID token."""

    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, description="Small client info (e.g. platform). Never put secrets or tokens here."
    )

    @field_validator("metadata")
    @classmethod
    def _small(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > MAX_METADATA_KEYS:
            raise ValueError(f"metadata may have at most {MAX_METADATA_KEYS} keys.")
        for key, value in v.items():
            if len(str(key)) > 50 or (isinstance(value, str) and len(value) > MAX_VALUE_LEN):
                raise ValueError("metadata keys/values are too long.")
        return v


class SessionStarted(BaseModel):
    session_id: str
    login_at: datetime
    last_seen_at: datetime
    is_active: bool


class UserSession(SessionStarted):
    """user_sessions/{session_id}."""

    uid: str
    role: str
    logout_at: datetime | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
