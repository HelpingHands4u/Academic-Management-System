from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.attendance import AttendanceSummaryItem
from app.schemas.exams import ExamScheduleView
from app.schemas.notices import Notice
from app.schemas.people import Enrollment
from app.schemas.results import CgpaResponse, SgpaItem
from app.schemas.timetable import TimetableView


class AdminAnalytics(BaseModel):
    active_students: int
    active_faculty: int
    departments: int
    programs: int
    courses: int
    course_offerings: int
    active_enrollments: int
    examinations: int
    attendance_records: int
    published_results: int
    active_notices: int = Field(description="Notices with is_active and is_published set (publish/expiry dates are not evaluated).")


class FacultyAnalytics(BaseModel):
    assigned_course_offerings: int
    enrolled_students: int = Field(description="Distinct students with an ACTIVE enrollment in an assigned offering.")
    attendance_records: int
    attendance_completion_percentage: float | None = Field(
        default=None, description="Always null: the data model stores no planned class count, so completion is not determinable.")
    upcoming_exam_schedules: int
    pending_marks: int = Field(description="Active enrollments x non-cancelled exam schedules with no mark document yet.")
    live_notices: int


class StudentAnalytics(BaseModel):
    profile_found: bool
    enrolled_courses: int
    enrollments: list[Enrollment]
    attendance: list[AttendanceSummaryItem]
    upcoming_exams: list[ExamScheduleView]
    published_results: int
    sgpa: list[SgpaItem]
    cgpa: CgpaResponse | None = None
    timetable: list[TimetableView]
    notices: list[Notice]


class ActiveSessionRef(BaseModel):
    session_id: str
    uid: str
    role: str


class ActiveUsers(BaseModel):
    active_window_seconds: int
    recent_window_seconds: int
    active_user_count: int
    active_student_count: int
    active_faculty_count: int
    active_admin_count: int
    recently_active_count: int
    total_users: int
    total_students: int
    total_faculty: int
    total_admins: int
    note: str = ("Active counts come from tracked sessions (open + seen within the active window); registered "
                 "totals come from users documents. Firebase Auth totals are not queried.")
    active_sessions: list[ActiveSessionRef] | None = None

