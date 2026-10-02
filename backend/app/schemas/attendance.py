from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.academic import RefId, _Strict
from app.schemas.people import PersonId

Remarks = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    EXCUSED = "EXCUSED"


class AttendanceCreate(_Strict):
    """Everything else (uid, course, session, semester, faculty) is derived server-side."""

    student_id: PersonId
    course_offering_id: RefId
    attendance_date: date
    status: AttendanceStatus
    remarks: Remarks | None = None


class AttendanceUpdate(_Strict):
    """Only status and remarks can change; ownership relationships are immutable."""

    status: AttendanceStatus | None = None
    remarks: Remarks | None = None


class BulkEntry(_Strict):
    student_id: PersonId
    status: AttendanceStatus
    remarks: Remarks | None = None


class AttendanceBulkCreate(_Strict):
    course_offering_id: RefId
    attendance_date: date
    entries: list[BulkEntry] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_students(self):
        ids = [e.student_id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Each student may appear only once per bulk request.")
        return self


class AttendanceRecord(BaseModel):
    id: str
    attendance_id: str
    student_uid: str
    student_id: str
    course_offering_id: str
    course_id: str
    academic_session_id: str
    semester_id: str
    faculty_uid: str | None = None
    attendance_date: date
    status: AttendanceStatus
    remarks: str | None = None
    marked_by_uid: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BulkAttendanceResponse(BaseModel):
    created: int
    items: list[AttendanceRecord]


class AttendanceSummaryItem(BaseModel):
    student_uid: str
    student_id: str | None = None
    course_id: str | None = None
    course_code: str | None = None
    course_name: str | None = None
    course_offering_id: str
    total_classes: int
    present_count: int
    absent_count: int
    late_count: int
    excused_count: int
    attended_count: int = Field(description="PRESENT + LATE.")
    attendance_percentage: float = Field(description="attended_count / total_classes * 100, 0 when no classes.")


class AttendanceSummaryResponse(BaseModel):
    items: list[AttendanceSummaryItem]
