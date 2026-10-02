from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.academic import RefId, _Strict
from app.schemas.courses import Section

PersonId = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
]
Batch = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9 _/\-]+$")]
Designation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DROPPED = "DROPPED"
    COMPLETED = "COMPLETED"


# ---- Students -------------------------------------------------------------
class StudentCreate(_Strict):
    """email / display_name come from the linked user profile, never from the client."""

    uid: RefId
    student_id: PersonId
    department_id: RefId
    program_id: RefId
    current_semester_id: RefId | None = None
    admission_year: int = Field(ge=1900, le=2100)
    batch: Batch | None = None
    section: Section | None = None


class StudentUpdate(_Strict):
    """uid, student_id and email are immutable. Send null to clear semester/batch/section."""

    department_id: RefId | None = None
    program_id: RefId | None = None
    current_semester_id: RefId | None = None
    admission_year: int | None = Field(default=None, ge=1900, le=2100)
    batch: Batch | None = None
    section: Section | None = None
    is_active: bool | None = None


class Student(BaseModel):
    id: str
    uid: str
    student_id: str
    email: str | None = None
    display_name: str | None = None
    department_id: str
    program_id: str
    current_semester_id: str | None = None
    admission_year: int
    batch: str | None = None
    section: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Faculty --------------------------------------------------------------
class FacultyCreate(_Strict):
    uid: RefId
    faculty_id: PersonId
    department_id: RefId
    designation: Designation | None = None


class FacultyUpdate(_Strict):
    """uid, faculty_id and email are immutable."""

    department_id: RefId | None = None
    designation: Designation | None = None
    is_active: bool | None = None


class Faculty(BaseModel):
    id: str
    uid: str
    faculty_id: str
    email: str | None = None
    display_name: str | None = None
    department_id: str
    designation: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Enrollments ----------------------------------------------------------
class EnrollmentCreate(_Strict):
    student_id: PersonId
    course_offering_id: RefId


class EnrollmentUpdate(_Strict):
    status: EnrollmentStatus


class Enrollment(BaseModel):
    id: str
    student_uid: str
    student_id: str
    course_offering_id: str
    course_id: str
    academic_session_id: str
    semester_id: str
    program_id: str
    section: str | None = None
    status: EnrollmentStatus
    enrolled_at: datetime | None = None
    dropped_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

