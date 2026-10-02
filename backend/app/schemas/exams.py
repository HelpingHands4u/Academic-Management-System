from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.academic import Name, RefId, _Strict

Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Room = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Instructions = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ExaminationType(str, Enum):
    MIDTERM = "MIDTERM"
    INTERNAL = "INTERNAL"
    END_SEMESTER = "END_SEMESTER"
    PRACTICAL = "PRACTICAL"
    SUPPLEMENTARY = "SUPPLEMENTARY"


class ExaminationStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ONGOING = "ONGOING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---- Examinations ---------------------------------------------------------
class ExaminationCreate(_Strict):
    """Session, program and department are derived from the semester; if supplied they must agree."""

    name: Name
    examination_type: ExaminationType
    semester_id: RefId
    start_date: date
    end_date: date
    status: ExaminationStatus = ExaminationStatus.DRAFT
    description: Description | None = None
    academic_session_id: RefId | None = None
    program_id: RefId | None = None
    department_id: RefId | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date.")
        return self


class ExaminationUpdate(_Strict):
    """Type, semester and the derived academic relationships are immutable."""

    name: Name | None = None
    description: Description | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: ExaminationStatus | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date.")
        return self


class Examination(BaseModel):
    id: str
    examination_id: str
    name: str
    examination_type: ExaminationType
    academic_session_id: str
    semester_id: str
    program_id: str
    department_id: str
    start_date: date
    end_date: date
    status: ExaminationStatus
    description: str | None = None
    created_by_uid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- Exam schedules -------------------------------------------------------
def _check_times(start: time | None, end: time | None) -> None:
    if start is not None and end is not None and end <= start:
        raise ValueError("end_time must be after start_time.")


class ExamScheduleCreate(_Strict):
    """Course, session, semester, program, department and faculty are derived from the
    offering; if supplied they must agree with it."""

    examination_id: RefId
    course_offering_id: RefId
    exam_date: date
    start_time: time
    end_time: time
    room: Room | None = None
    max_marks: int | None = Field(default=None, gt=0, le=10000, description="Defaults to the course max_marks.")
    instructions: Instructions | None = None
    course_id: RefId | None = None
    academic_session_id: RefId | None = None
    semester_id: RefId | None = None
    program_id: RefId | None = None
    department_id: RefId | None = None
    faculty_uid: RefId | None = None

    @model_validator(mode="after")
    def _times(self):
        _check_times(self.start_time, self.end_time)
        return self


class ExamScheduleUpdate(_Strict):
    """Examination and offering (and everything derived from them) are immutable."""

    exam_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    room: Room | None = None
    max_marks: int | None = Field(default=None, gt=0, le=10000)
    instructions: Instructions | None = None
    status: ScheduleStatus | None = None

    @model_validator(mode="after")
    def _times(self):
        _check_times(self.start_time, self.end_time)
        return self


class ExamSchedule(BaseModel):
    id: str
    exam_schedule_id: str
    examination_id: str
    course_offering_id: str
    course_id: str
    academic_session_id: str
    semester_id: str
    program_id: str
    department_id: str
    exam_date: date
    start_time: time
    end_time: time
    room: str | None = None
    faculty_uid: str | None = None
    max_marks: int
    instructions: str | None = None
    status: ScheduleStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExamScheduleView(ExamSchedule):
    """Schedule enriched with examination / course details (used for every schedule read)."""

    examination_name: str | None = None
    examination_type: ExaminationType | None = None
    examination_status: ExaminationStatus | None = None
    course_code: str | None = None
    course_name: str | None = None
    section: str | None = None
