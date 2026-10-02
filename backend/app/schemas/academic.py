from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

T = TypeVar("T")

Code = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,19}$"),
]
DegreeType = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_]{2,20}$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
RefId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")]


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = Field(default=None, description="Pass as `cursor` for the next page.")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_range(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and start >= end:
        raise ValueError("start_date must be before end_date.")


# ---- Departments ----------------------------------------------------------
class DepartmentCreate(_Strict):
    name: Name
    code: Code
    description: str | None = Field(default=None, max_length=1000)


class DepartmentUpdate(_Strict):
    """`code` is immutable (it determines the stable document id)."""

    name: Name | None = None
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class Department(BaseModel):
    id: str
    name: str
    code: str
    description: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Programs -------------------------------------------------------------
class ProgramCreate(_Strict):
    name: Name
    code: Code
    department_id: RefId
    degree_type: DegreeType
    duration_years: int = Field(gt=0, le=10)
    total_semesters: int = Field(gt=0, le=20)


class ProgramUpdate(_Strict):
    """`code` is immutable."""

    name: Name | None = None
    department_id: RefId | None = None
    degree_type: DegreeType | None = None
    duration_years: int | None = Field(default=None, gt=0, le=10)
    total_semesters: int | None = Field(default=None, gt=0, le=20)
    is_active: bool | None = None


class Program(BaseModel):
    id: str
    name: str
    code: str
    department_id: str
    degree_type: str
    duration_years: int
    total_semesters: int
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Academic sessions ----------------------------------------------------
class AcademicSessionCreate(_Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)]
    start_date: date
    end_date: date
    is_current: bool = False

    @model_validator(mode="after")
    def _dates(self):
        _check_range(self.start_date, self.end_date)
        return self


class AcademicSessionUpdate(_Strict):
    """`name` is immutable (it determines the stable document id)."""

    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _dates(self):
        _check_range(self.start_date, self.end_date)
        return self


class AcademicSession(BaseModel):
    id: str
    name: str
    start_date: date
    end_date: date
    is_current: bool = False
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Semesters ------------------------------------------------------------
class SemesterCreate(_Strict):
    program_id: RefId
    academic_session_id: RefId
    semester_number: int = Field(gt=0, le=20)
    name: Name | None = None
    start_date: date
    end_date: date
    is_current: bool = False

    @model_validator(mode="after")
    def _dates(self):
        _check_range(self.start_date, self.end_date)
        return self


class SemesterUpdate(_Strict):
    """program, session and number are immutable (they determine the document id)."""

    name: Name | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _dates(self):
        _check_range(self.start_date, self.end_date)
        return self


class Semester(BaseModel):
    id: str
    program_id: str
    academic_session_id: str
    semester_number: int
    name: str
    start_date: date
    end_date: date
    is_current: bool = False
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
