from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.schemas.academic import RefId, _Strict
from app.schemas.people import PersonId

Remarks = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
GradeLabel = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=5)]
MarkValue = Annotated[float, Field(ge=0, le=10000, allow_inf_nan=False)]
MaxValue = Annotated[float, Field(gt=0, le=10000, allow_inf_nan=False)]

MAX_GRADE_POINT = 10.0


class MarkStatus(str, Enum):
    DRAFT = "DRAFT"  # entered, not counted in results
    FINAL = "FINAL"  # verified by an ADMIN, counted in results


# ---- Grading scheme (configurable; no official values are built in) -------
class GradeBand(BaseModel):
    """Half-open percentage band [min_percentage, max_percentage); the band ending at 100 includes 100."""

    grade: GradeLabel
    min_percentage: float = Field(ge=0, le=100, allow_inf_nan=False)
    max_percentage: float = Field(gt=0, le=100, allow_inf_nan=False)
    grade_point: float = Field(ge=0, le=MAX_GRADE_POINT, allow_inf_nan=False)
    is_pass: bool = Field(default=True, description="Whether this grade counts as a pass for earned credits.")

    @model_validator(mode="after")
    def _range(self):
        if self.min_percentage >= self.max_percentage:
            raise ValueError("min_percentage must be lower than max_percentage.")
        return self


class GradingScheme(BaseModel):
    """Bands must tile 0-100 with no gaps or overlaps and unique grade labels."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    bands: list[GradeBand] = Field(min_length=1, max_length=30)

    @field_validator("bands")
    @classmethod
    def _tile(cls, bands: list[GradeBand]):
        ordered = sorted(bands, key=lambda b: (b.min_percentage, b.max_percentage))
        if len({b.grade for b in ordered}) != len(ordered):
            raise ValueError("Grade labels must be unique.")
        expected = Decimal(0)
        for b in ordered:
            low = Decimal(str(b.min_percentage))
            if low < expected:
                raise ValueError("Grading bands must not overlap.")
            if low > expected:
                raise ValueError("Grading bands must cover 0-100 without gaps.")
            expected = Decimal(str(b.max_percentage))
        if expected != Decimal(100):
            raise ValueError("Grading bands must cover 0-100 without gaps.")
        return ordered


class GradingSchemeView(GradingScheme):
    updated_at: datetime | None = None
    updated_by_uid: str | None = None


class RegradeRequest(_Strict):
    semester_id: RefId


class RegradeResponse(BaseModel):
    marks_updated: int
    results_regenerated: int
    results_unpublished: int = 0


# ---- Marks ----------------------------------------------------------------
class _Components(_Strict):
    internal_marks: MarkValue | None = None
    external_marks: MarkValue | None = None
    practical_marks: MarkValue | None = None
    internal_max_marks: MaxValue | None = None
    external_max_marks: MaxValue | None = None
    practical_max_marks: MaxValue | None = None


class MarkCreate(_Components):
    """Totals, percentage, grade and grade point are always calculated by the backend; the
    student uid, course, session and semester are derived from verified records."""

    student_id: PersonId
    course_offering_id: RefId
    examination_id: RefId
    exam_schedule_id: RefId | None = None
    status: MarkStatus = MarkStatus.DRAFT
    remarks: Remarks | None = None

    @model_validator(mode="after")
    def _one_component(self):
        if all(v is None for v in (self.internal_marks, self.external_marks, self.practical_marks)):
            raise ValueError("At least one of internal_marks, external_marks, practical_marks is required.")
        return self


class MarkUpdate(_Components):
    """Send a component as null to remove it. Ownership relationships are immutable."""

    status: MarkStatus | None = None
    remarks: Remarks | None = None


class Mark(BaseModel):
    id: str
    mark_id: str
    student_uid: str
    student_id: str
    course_offering_id: str
    course_id: str
    examination_id: str
    exam_schedule_id: str | None = None
    academic_session_id: str
    semester_id: str
    internal_marks: float | None = None
    external_marks: float | None = None
    practical_marks: float | None = None
    internal_max_marks: float | None = None
    external_max_marks: float | None = None
    practical_max_marks: float | None = None
    total_marks: float
    max_marks: float
    percentage: float
    grade: str | None = None
    grade_point: float | None = None
    status: MarkStatus
    remarks: str | None = None
    entered_by_uid: str
    verified_by_uid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarkView(Mark):
    course_code: str | None = None
    course_name: str | None = None
    examination_name: str | None = None

