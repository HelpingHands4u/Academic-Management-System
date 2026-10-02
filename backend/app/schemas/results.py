from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.academic import RefId, _Strict
from app.schemas.exams import ExaminationType
from app.schemas.people import PersonId


class ResultStatus(str, Enum):
    COMPLETE = "COMPLETE"  # every enrolled course has a FINAL mark
    INCOMPLETE = "INCOMPLETE"  # at least one course has no FINAL mark yet (never treated as zero)


class CourseResultStatus(str, Enum):
    GRADED = "GRADED"
    MISSING = "MISSING"  # no FINAL mark
    AMBIGUOUS = "AMBIGUOUS"  # several FINAL marks of the configured examination type
    DUPLICATE = "DUPLICATE"  # same course already counted through another offering


class CourseResult(BaseModel):
    course_id: str
    course_code: str | None = None
    course_name: str | None = None
    course_offering_id: str
    credits: float
    status: CourseResultStatus
    mark_id: str | None = None
    total_marks: float | None = None
    max_marks: float | None = None
    percentage: float | None = None
    grade: str | None = None
    grade_point: float | None = None
    passed: bool | None = None
    earned_credits: float = 0


class GenerateResultRequest(_Strict):
    student_id: PersonId
    semester_id: RefId
    examination_type: ExaminationType = Field(
        default=ExaminationType.END_SEMESTER,
        description="Only FINAL marks of examinations of this type count towards the result.",
    )


class Result(BaseModel):
    id: str
    result_id: str
    student_uid: str
    student_id: str
    academic_session_id: str
    semester_id: str
    program_id: str
    courses: list[CourseResult]
    total_credits: float | None = Field(default=None, description="Credits of all counted courses (null in the faculty view).")
    earned_credits: float | None = None
    total_marks: float | None = None
    max_marks: float | None = None
    percentage: float | None = None
    sgpa: float | None = Field(default=None, description="Only set when status is COMPLETE.")
    examination_type: ExaminationType | None = None
    status: ResultStatus
    published: bool = False
    published_at: datetime | None = None
    published_by_uid: str | None = None
    generated_by_uid: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SgpaItem(BaseModel):
    student_id: str
    semester_id: str
    academic_session_id: str
    total_credits: float
    earned_credits: float
    sgpa: float | None
    status: ResultStatus
    published: bool


class SgpaResponse(BaseModel):
    items: list[SgpaItem]


class CgpaSemester(BaseModel):
    semester_id: str
    academic_session_id: str
    total_credits: float
    sgpa: float


class CgpaStatus(str, Enum):
    COMPLETE = "COMPLETE"  # every result record of the student is included
    PARTIAL = "PARTIAL"  # some semesters are incomplete or unpublished and were excluded
    NO_DATA = "NO_DATA"


class CgpaResponse(BaseModel):
    student_id: str
    semesters_considered: list[CgpaSemester]
    semesters_excluded: int
    total_credits: float
    cgpa: float | None
    status: CgpaStatus


