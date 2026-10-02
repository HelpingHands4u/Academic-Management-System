from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, StringConstraints, field_validator, model_validator

from app.schemas.academic import RefId, _Strict


class NoticeAudience(str, Enum):
    ALL = "ALL"  # every authenticated portal user
    STUDENTS = "STUDENTS"
    FACULTY = "FACULTY"
    DEPARTMENT = "DEPARTMENT"  # students and faculty of one department (needs department_id)
    PROGRAM = "PROGRAM"  # students of one program, and faculty teaching it (needs program_id)
    SEMESTER = "SEMESTER"  # students of one semester, and faculty teaching it (needs semester_id)


class NoticePriority(str, Enum):
    NORMAL = "NORMAL"
    IMPORTANT = "IMPORTANT"
    URGENT = "URGENT"


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


def _aware(value: datetime | None) -> datetime | None:
    """Naive datetimes are interpreted as UTC so every stored value is comparable."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _https(value: str | None) -> str | None:
    if value is not None and not value.lower().startswith(("https://", "http://")):
        raise ValueError("attachment_url must be an http(s) URL.")
    return value


AttachmentUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
                          AfterValidator(_https)]
MetaValue = str | int | float | bool


def _check_meta(value: dict[str, MetaValue] | None):
    if value is not None and len(value) > 20:
        raise ValueError("metadata may hold at most 20 entries.")
    return value


class _NoticeDates:
    @staticmethod
    def check(publish_at: datetime | None, expiry_at: datetime | None) -> None:
        if publish_at and expiry_at and expiry_at < publish_at:
            raise ValueError("expiry_at must not be before publish_at.")


class NoticeCreate(_Strict):
    """Creator, creator role and (for DEPARTMENT/PROGRAM/SEMESTER) derived relationships come from the server.
    Omitting publish_at publishes immediately."""

    title: Title
    description: Body
    audience: NoticeAudience = NoticeAudience.ALL
    department_id: RefId | None = None
    program_id: RefId | None = None
    semester_id: RefId | None = None
    academic_session_id: RefId | None = None
    priority: NoticePriority = NoticePriority.NORMAL
    publish_at: datetime | None = None
    expiry_at: datetime | None = None
    attachment_url: AttachmentUrl | None = None
    metadata: dict[str, MetaValue] | None = None
    is_published: bool = True

    _p = field_validator("publish_at", "expiry_at")(_aware)
    _m = field_validator("metadata")(_check_meta)

    @model_validator(mode="after")
    def _dates(self):
        _NoticeDates.check(self.publish_at, self.expiry_at)
        return self


class NoticeUpdate(_Strict):
    """Creator fields are immutable. Targets can only change together with `audience`
    (they are re-derived and re-validated)."""

    title: Title | None = None
    description: Body | None = None
    audience: NoticeAudience | None = None
    department_id: RefId | None = None
    program_id: RefId | None = None
    semester_id: RefId | None = None
    academic_session_id: RefId | None = None
    priority: NoticePriority | None = None
    publish_at: datetime | None = None
    expiry_at: datetime | None = None
    attachment_url: AttachmentUrl | None = None
    metadata: dict[str, MetaValue] | None = None
    is_active: bool | None = None
    is_published: bool | None = None

    _p = field_validator("publish_at", "expiry_at")(_aware)
    _m = field_validator("metadata")(_check_meta)

    @model_validator(mode="after")
    def _dates(self):
        _NoticeDates.check(self.publish_at, self.expiry_at)
        return self


class Notice(BaseModel):
    id: str
    notice_id: str
    title: str
    description: str
    audience: NoticeAudience
    department_id: str | None = None
    program_id: str | None = None
    semester_id: str | None = None
    academic_session_id: str | None = None
    creator_uid: str | None = None
    creator_role: str | None = None
    priority: NoticePriority = NoticePriority.NORMAL
    publish_at: datetime | None = None
    expiry_at: datetime | None = None
    is_published: bool = True
    is_active: bool = True
    attachment_url: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

