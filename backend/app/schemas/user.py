from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    FACULTY = "FACULTY"
    STUDENT = "STUDENT"


class UserProfile(BaseModel):
    """Firestore users/{uid} document (safe to return to clients; no secrets)."""

    uid: str
    email: str | None = None
    display_name: str | None = None
    role: UserRole
    student_id: str | None = None
    faculty_id: str | None = None
    department_id: str | None = None
    program_id: str | None = None
    semester_id: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserCreate(BaseModel):
    """Admin request body for POST /api/v1/users."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: SecretStr
    display_name: str = Field(min_length=1, max_length=100)
    role: UserRole
    student_id: str | None = None
    faculty_id: str | None = None
    department_id: str | None = None
    program_id: str | None = None
    semester_id: str | None = None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: SecretStr) -> SecretStr:
        pw = value.get_secret_value()
        if not 8 <= len(pw) <= 128:
            raise ValueError("Password must be 8 to 128 characters long.")
        if not (re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw) and re.search(r"\d", pw)):
            raise ValueError("Password must contain upper-case, lower-case and a digit.")
        return value

    @field_validator("student_id", "faculty_id", "department_id", "program_id", "semester_id")
    @classmethod
    def _safe_id(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not _ID_PATTERN.match(value):
            raise ValueError("IDs may contain letters, digits, '.', '_' and '-' (max 64 chars).")
        return value

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def _role_ids(self) -> "UserCreate":
        if self.role == UserRole.STUDENT and not self.student_id:
            raise ValueError("student_id is required for STUDENT users.")
        if self.role == UserRole.FACULTY and not self.faculty_id:
            raise ValueError("faculty_id is required for FACULTY users.")
        if self.role != UserRole.STUDENT and self.student_id:
            raise ValueError("student_id is only valid for STUDENT users.")
        if self.role != UserRole.FACULTY and self.faculty_id:
            raise ValueError("faculty_id is only valid for FACULTY users.")
        return self


class UserListResponse(BaseModel):
    items: list[UserProfile]
    next_cursor: str | None = Field(default=None, description="Pass as `cursor` for the next page.")


class AuthMeResponse(BaseModel):
    uid: str
    email: str | None = None
    email_verified: bool | None = None
    display_name: str | None = None
    role: UserRole | None = Field(default=None, description="Trusted role (claims or Firestore).")
    role_source: str | None = Field(default=None, description="'claims' or 'profile'.")
    profile_provisioned: bool
    profile: UserProfile | None = None
    message: str | None = None


class UserUpdate(BaseModel):
    """Admin request body for PATCH /api/v1/users/{uid}: activation status and role only."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    role: UserRole | None = None
