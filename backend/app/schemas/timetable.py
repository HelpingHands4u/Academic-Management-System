from __future__ import annotations

from datetime import datetime, time
from enum import Enum

from pydantic import BaseModel, model_validator

from app.schemas.academic import RefId, _Strict
from app.schemas.exams import Room
from app.schemas.courses import Section


class DayOfWeek(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


DAY_ORDER = {d.value: i for i, d in enumerate(DayOfWeek)}


class ClassType(str, Enum):
    LECTURE = "LECTURE"
    LAB = "LAB"
    TUTORIAL = "TUTORIAL"
    PRACTICAL = "PRACTICAL"
    OTHER = "OTHER"


def _check_times(start: time | None, end: time | None) -> None:
    for value in (start, end):
        if value is not None and value.tzinfo is not None:
            raise ValueError("Times must be timezone-naive (HH:MM[:SS]).")
    if start is not None and end is not None and end <= start:
        raise ValueError("end_time must be after start_time.")


class TimetableCreate(_Strict):
    """Course, session, semester, program, department, section and faculty are derived from the
    offering; if supplied they must agree with it."""

    course_offering_id: RefId
    day_of_week: DayOfWeek
    start_time: time
    end_time: time
    room: Room
    class_type: ClassType = ClassType.LECTURE
    section: Section | None = None
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


class TimetableUpdate(_Strict):
    """Offering and everything derived from it are immutable. is_active=false retires an entry."""

    day_of_week: DayOfWeek | None = None
    start_time: time | None = None
    end_time: time | None = None
    room: Room | None = None
    class_type: ClassType | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _times(self):
        _check_times(self.start_time, self.end_time)
        return self


class TimetableEntry(BaseModel):
    id: str
    timetable_id: str
    academic_session_id: str
    semester_id: str
    program_id: str
    department_id: str
    section: str
    course_offering_id: str
    course_id: str
    faculty_uid: str | None = None
    day_of_week: DayOfWeek
    start_time: time
    end_time: time
    room: str
    class_type: ClassType
    is_active: bool = True
    created_by_uid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TimetableView(TimetableEntry):
    """Entry enriched with course / faculty details (used for every read)."""

    course_code: str | None = None
    course_name: str | None = None
    faculty_name: str | None = None
