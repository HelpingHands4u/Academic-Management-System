from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from typing import Annotated

from app.core.security import AuthContext, require_admin, require_roles
from app.routers._errors import to_http
from app.routers.exams import Cursor, Limit, RefQ, _actor, _call, _viewer
from app.schemas.academic import Page
from app.schemas.timetable import DayOfWeek, TimetableCreate, TimetableEntry, TimetableUpdate, TimetableView
from app.schemas.user import UserRole
from app.services import timetable as svc

Reader = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Admin = Annotated[AuthContext, Depends(require_admin())]
StudentOnly = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
FacultyOnly = Annotated[AuthContext, Depends(require_roles(UserRole.FACULTY))]

router = APIRouter(prefix="/timetable", tags=["timetable"])


@router.post("", response_model=TimetableEntry, status_code=status.HTTP_201_CREATED)
def create_entry(payload: TimetableCreate, ctx: Admin):
    """ADMIN only. Relationships are derived from the offering. 409 on offering, room, faculty or student overlap."""
    return _call(svc.create_entry, payload, _actor(ctx))


@router.get("", response_model=Page[TimetableView])
def list_entries(ctx: Reader, academic_session_id: RefQ = None, semester_id: RefQ = None, program_id: RefQ = None,
                 department_id: RefQ = None, section: RefQ = None, course_offering_id: RefQ = None,
                 course_id: RefQ = None, faculty_uid: RefQ = None, day_of_week: DayOfWeek | None = None,
                 room: RefQ = None, is_active: bool | None = None, limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: entries of their assigned offerings. STUDENT: entries of offerings they are actively
    enrolled in. Non-admins only see active entries."""
    return _call(svc.list_entries, viewer=_viewer(ctx), academic_session_id=academic_session_id,
                 semester_id=semester_id, program_id=program_id, department_id=department_id, section=section,
                 course_offering_id=course_offering_id, course_id=course_id, faculty_uid=faculty_uid,
                 day_of_week=day_of_week, room=room, is_active=is_active, limit=limit, cursor=cursor)


@router.get("/me", response_model=Page[TimetableView])
def my_timetable(ctx: StudentOnly, day_of_week: DayOfWeek | None = None, limit: Limit = 50, cursor: Cursor = None):
    """The authenticated student's timetable, sorted by weekday then start time."""
    return _call(svc.list_entries, viewer=_viewer(ctx), day_of_week=day_of_week, limit=limit, cursor=cursor)


@router.get("/faculty/me", response_model=Page[TimetableView])
def my_faculty_timetable(ctx: FacultyOnly, day_of_week: DayOfWeek | None = None, limit: Limit = 50,
                         cursor: Cursor = None):
    """Timetable of offerings assigned to the authenticated faculty member."""
    return _call(svc.list_entries, viewer=_viewer(ctx), day_of_week=day_of_week, limit=limit, cursor=cursor)


@router.get("/{timetable_id}", response_model=TimetableView)
def get_entry(timetable_id: str, ctx: Reader):
    return _call(svc.get_entry, timetable_id, _viewer(ctx))


@router.patch("/{timetable_id}", response_model=TimetableEntry)
def update_entry(timetable_id: str, payload: TimetableUpdate, ctx: Admin):
    """ADMIN only. Set is_active=false to retire an entry; the offering link is immutable."""
    return _call(svc.update_entry, timetable_id, payload, _actor(ctx))
