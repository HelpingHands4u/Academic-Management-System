from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.academic import Code, Name, RefId, _Strict


class CourseType(str, Enum):
    CORE = "CORE"
    ELECTIVE = "ELECTIVE"
    PRACTICAL = "PRACTICAL"
    PROJECT = "PROJECT"
    OTHER = "OTHER"


class OfferingStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


Section = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9]{1,10}$")]
SearchPrefix = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_-]{1,20}$")]


# ---- Courses --------------------------------------------------------------
class CourseCreate(_Strict):
    code: Code
    name: Name
    description: str | None = Field(default=None, max_length=2000)
    department_id: RefId
    program_id: RefId
    credits: float = Field(gt=0, le=50)
    course_type: CourseType
    semester_number: int = Field(gt=0, le=20)
    max_marks: int = Field(gt=0, le=10000)
    passing_marks: int = Field(ge=0)

    @model_validator(mode="after")
    def _marks(self):
        if self.passing_marks > self.max_marks:
            raise ValueError("passing_marks must not exceed max_marks.")
        return self


class CourseUpdate(_Strict):
    """code, department_id, program_id and semester_number are immutable."""

    name: Name | None = None
    description: str | None = Field(default=None, max_length=2000)
    credits: float | None = Field(default=None, gt=0, le=50)
    course_type: CourseType | None = None
    max_marks: int | None = Field(default=None, gt=0, le=10000)
    passing_marks: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _marks(self):
        if self.max_marks is not None and self.passing_marks is not None and self.passing_marks > self.max_marks:
            raise ValueError("passing_marks must not exceed max_marks.")
        return self


class Course(BaseModel):
    id: str
    code: str
    name: str
    description: str | None = None
    department_id: str
    program_id: str
    credits: float
    course_type: CourseType
    semester_number: int
    max_marks: int
    passing_marks: int
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Course offerings -----------------------------------------------------
class OfferingCreate(_Strict):
    """program/session/department are derived server-side; if supplied they must be consistent."""

    course_id: RefId
    semester_id: RefId
    section: Section
    academic_session_id: RefId | None = None
    program_id: RefId | None = None
    department_id: RefId | None = None
    faculty_uid: RefId | None = None
    room: str | None = Field(default=None, max_length=50)
    capacity: int | None = Field(default=None, gt=0, le=5000)
    status: OfferingStatus = OfferingStatus.PLANNED


class OfferingUpdate(_Strict):
    """course, semester and section are immutable. faculty_uid=null unassigns."""

    faculty_uid: RefId | None = None
    room: str | None = Field(default=None, max_length=50)
    capacity: int | None = Field(default=None, gt=0, le=5000)
    status: OfferingStatus | None = None


class CourseOffering(BaseModel):
    id: str
    course_id: str
    academic_session_id: str
    semester_id: str
    program_id: str
    department_id: str
    section: str
    faculty_uid: str | None = None
    faculty_id: str | None = None
    room: str | None = None
    capacity: int | None = None
    status: OfferingStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None
