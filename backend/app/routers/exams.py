from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers._errors import to_http
from app.schemas.academic import Page
from app.schemas.exams import (
    Examination,
    ExaminationCreate,
    ExaminationStatus,
    ExaminationType,
    ExaminationUpdate,
    ExamSchedule,
    ExamScheduleCreate,
    ExamScheduleUpdate,
    ExamScheduleView,
    ScheduleStatus,
)
from app.schemas.user import UserRole
from app.services import exams as svc
from app.services.academic_common import Actor, Viewer

Reader = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Admin = Annotated[AuthContext, Depends(require_admin())]
StudentOnly = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
FacultyOnly = Annotated[AuthContext, Depends(require_roles(UserRole.FACULTY))]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
RefQ = Annotated[str | None, Query(max_length=200)]


def _actor(ctx: AuthContext) -> Actor:
    return Actor(ctx.user.uid, ctx.role.value if ctx.role else None)


def _viewer(ctx: AuthContext) -> Viewer:
    p = ctx.profile
    return Viewer(ctx.user.uid, ctx.role.value if ctx.role else None,
                  p.program_id if p else None, p.semester_id if p else None)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise to_http(exc) from None


examinations_router = APIRouter(prefix="/examinations", tags=["examinations"])


@examinations_router.post("", response_model=Examination, status_code=status.HTTP_201_CREATED)
def create_examination(payload: ExaminationCreate, ctx: Admin):
    """ADMIN only. Session, program and department are derived from the semester."""
    return _call(svc.create_examination, payload, _actor(ctx))


@examinations_router.get("", response_model=Page[Examination])
def list_examinations(ctx: Reader, academic_session_id: RefQ = None, semester_id: RefQ = None,
                      program_id: RefQ = None, department_id: RefQ = None,
                      examination_type: ExaminationType | None = None,
                      status: ExaminationStatus | None = None, limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: non-draft examinations of their assigned offerings' semesters.
    STUDENT: non-draft examinations of their own semester."""
    return _call(svc.list_examinations, viewer=_viewer(ctx), academic_session_id=academic_session_id,
                 semester_id=semester_id, program_id=program_id, department_id=department_id,
                 examination_type=examination_type, status=status, limit=limit, cursor=cursor)


@examinations_router.get("/me", response_model=Page[ExamScheduleView])
def my_exam_schedules(ctx: StudentOnly, examination_id: RefQ = None, exam_date: date | None = None,
                      status: ScheduleStatus | None = None, limit: Limit = 50, cursor: Cursor = None):
    """Exam schedules for the authenticated student's active enrollments."""
    return _call(svc.list_schedules, viewer=_viewer(ctx), examination_id=examination_id,
                 exam_date=exam_date, status=status, limit=limit, cursor=cursor)


@examinations_router.get("/faculty/me", response_model=Page[ExamScheduleView])
def my_faculty_exam_schedules(ctx: FacultyOnly, examination_id: RefQ = None, exam_date: date | None = None,
                              status: ScheduleStatus | None = None, limit: Limit = 50, cursor: Cursor = None):
    """Exam schedules for course offerings assigned to the authenticated faculty member."""
    return _call(svc.list_schedules, viewer=_viewer(ctx), examination_id=examination_id,
                 exam_date=exam_date, status=status, limit=limit, cursor=cursor)


@examinations_router.get("/{examination_id}", response_model=Examination)
def get_examination(examination_id: str, ctx: Reader):
    return _call(svc.get_examination, examination_id, _viewer(ctx))


@examinations_router.patch("/{examination_id}", response_model=Examination)
def update_examination(examination_id: str, payload: ExaminationUpdate, ctx: Admin):
    return _call(svc.update_examination, examination_id, payload, _actor(ctx))


schedules_router = APIRouter(prefix="/exam-schedules", tags=["exam-schedules"])


@schedules_router.post("", response_model=ExamSchedule, status_code=status.HTTP_201_CREATED)
def create_schedule(payload: ExamScheduleCreate, ctx: Admin):
    """ADMIN only. Returns 409 on course-offering, room, faculty or student overlap."""
    return _call(svc.create_schedule, payload, _actor(ctx))


@schedules_router.get("", response_model=Page[ExamScheduleView])
def list_schedules(ctx: Reader, examination_id: RefQ = None, course_offering_id: RefQ = None,
                   course_id: RefQ = None, academic_session_id: RefQ = None, semester_id: RefQ = None,
                   program_id: RefQ = None, department_id: RefQ = None, faculty_uid: RefQ = None,
                   exam_date: date | None = None, status: ScheduleStatus | None = None,
                   limit: Limit = 50, cursor: Cursor = None):
    return _call(svc.list_schedules, viewer=_viewer(ctx), examination_id=examination_id,
                 course_offering_id=course_offering_id, course_id=course_id,
                 academic_session_id=academic_session_id, semester_id=semester_id, program_id=program_id,
                 department_id=department_id, faculty_uid=faculty_uid, exam_date=exam_date,
                 status=status, limit=limit, cursor=cursor)


@schedules_router.get("/{exam_schedule_id}", response_model=ExamScheduleView)
def get_schedule(exam_schedule_id: str, ctx: Reader):
    return _call(svc.get_schedule, exam_schedule_id, _viewer(ctx))


@schedules_router.patch("/{exam_schedule_id}", response_model=ExamSchedule)
def update_schedule(exam_schedule_id: str, payload: ExamScheduleUpdate, ctx: Admin):
    """ADMIN only. Set status=CANCELLED to cancel; examination/offering are immutable."""
    return _call(svc.update_schedule, exam_schedule_id, payload, _actor(ctx))
