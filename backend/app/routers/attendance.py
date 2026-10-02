from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.security import AuthContext, require_roles
from app.routers._errors import to_http
from app.schemas.academic import Page
from app.schemas.attendance import (
    AttendanceBulkCreate,
    AttendanceCreate,
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSummaryResponse,
    AttendanceUpdate,
    BulkAttendanceResponse,
)
from app.schemas.people import PersonId
from app.schemas.user import UserRole
from app.services import attendance as attendance_service
from app.services.academic_common import Viewer

AnyRole = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Marker = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY))]
StudentOnly = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
RefQ = Annotated[str | None, Query(max_length=200)]
StudentQ = Annotated[PersonId | None, Query()]

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _viewer(ctx: AuthContext) -> Viewer:
    p = ctx.profile
    return Viewer(ctx.user.uid, ctx.role.value if ctx.role else None,
                  p.program_id if p else None, p.semester_id if p else None)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise to_http(exc) from None


@router.post("", response_model=AttendanceRecord, status_code=status.HTTP_201_CREATED)
def create_attendance(payload: AttendanceCreate, ctx: Marker):
    """ADMIN or the FACULTY member assigned to the offering."""
    return _call(attendance_service.create_attendance, payload, _viewer(ctx))


@router.post("/bulk", response_model=BulkAttendanceResponse, status_code=status.HTTP_201_CREATED)
def create_bulk_attendance(payload: AttendanceBulkCreate, ctx: Marker):
    """All-or-nothing bulk marking for one offering and date."""
    return _call(attendance_service.create_bulk, payload, _viewer(ctx))


@router.get("/me/summary", response_model=AttendanceSummaryResponse)
def my_attendance_summary(ctx: StudentOnly, course_offering_id: RefQ = None, course_id: RefQ = None,
                          semester_id: RefQ = None, academic_session_id: RefQ = None):
    """The authenticated student's own summary, grouped per course offering."""
    return _call(attendance_service.attendance_summary, viewer=_viewer(ctx), student_id=None, student_uid=None,
                 course_offering_id=course_offering_id, course_id=course_id, semester_id=semester_id,
                 academic_session_id=academic_session_id, faculty_uid=None, attendance_date=None, status=None)


@router.get("/summary", response_model=AttendanceSummaryResponse)
def attendance_summary(ctx: Marker, student_id: StudentQ = None, student_uid: RefQ = None,
                       course_offering_id: RefQ = None, course_id: RefQ = None, semester_id: RefQ = None,
                       academic_session_id: RefQ = None, faculty_uid: RefQ = None):
    """ADMIN: any scope. FACULTY: limited to their assigned offerings."""
    return _call(attendance_service.attendance_summary, viewer=_viewer(ctx), student_id=student_id,
                 student_uid=student_uid, course_offering_id=course_offering_id, course_id=course_id,
                 semester_id=semester_id, academic_session_id=academic_session_id, faculty_uid=faculty_uid,
                 attendance_date=None, status=None)


@router.get("", response_model=Page[AttendanceRecord])
def list_attendance(ctx: AnyRole, student_id: StudentQ = None, student_uid: RefQ = None,
                    course_offering_id: RefQ = None, course_id: RefQ = None, semester_id: RefQ = None,
                    academic_session_id: RefQ = None, faculty_uid: RefQ = None,
                    attendance_date: date | None = None, status: AttendanceStatus | None = None,
                    limit: Limit = 50, cursor: Cursor = None):
    return _call(attendance_service.list_attendance, viewer=_viewer(ctx), student_id=student_id,
                 student_uid=student_uid, course_offering_id=course_offering_id, course_id=course_id,
                 semester_id=semester_id, academic_session_id=academic_session_id, faculty_uid=faculty_uid,
                 attendance_date=attendance_date, status=status, limit=limit, cursor=cursor)


@router.get("/{attendance_id}", response_model=AttendanceRecord)
def get_attendance(attendance_id: str, ctx: AnyRole):
    return _call(attendance_service.get_attendance, attendance_id, _viewer(ctx))


@router.patch("/{attendance_id}", response_model=AttendanceRecord)
def update_attendance(attendance_id: str, payload: AttendanceUpdate, ctx: Marker):
    """Only status/remarks are editable. ADMIN or the assigned FACULTY member."""
    return _call(attendance_service.update_attendance, attendance_id, payload, _viewer(ctx))
