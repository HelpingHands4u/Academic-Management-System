from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers.exams import Cursor, Limit, RefQ, _actor, _call, _viewer
from app.schemas.academic import Page
from app.schemas.notices import Notice, NoticeAudience, NoticeCreate, NoticePriority, NoticeUpdate
from app.schemas.user import UserRole
from app.services import notices as svc

Reader = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Admin = Annotated[AuthContext, Depends(require_admin())]
StudentOnly = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
FacultyOnly = Annotated[AuthContext, Depends(require_roles(UserRole.FACULTY))]

router = APIRouter(prefix="/notices", tags=["notices"])


@router.post("", response_model=Notice, status_code=status.HTTP_201_CREATED)
def create_notice(payload: NoticeCreate, ctx: Admin):
    """ADMIN only. Creator and academic relationships are derived server-side."""
    return _call(svc.create_notice, payload, _actor(ctx))


@router.get("", response_model=Page[Notice])
def list_notices(ctx: Reader, audience: NoticeAudience | None = None, department_id: RefQ = None,
                 program_id: RefQ = None, semester_id: RefQ = None, academic_session_id: RefQ = None,
                 is_active: bool | None = None, is_published: bool | None = None,
                 priority: NoticePriority | None = None, limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all notices. FACULTY/STUDENT: only live notices addressed to them."""
    return _call(svc.list_notices, viewer=_viewer(ctx), audience=audience, department_id=department_id,
                 program_id=program_id, semester_id=semester_id, academic_session_id=academic_session_id,
                 is_active=is_active, is_published=is_published, priority=priority, limit=limit, cursor=cursor)


@router.get("/me", response_model=Page[Notice])
def my_notices(ctx: StudentOnly, priority: NoticePriority | None = None, limit: Limit = 50, cursor: Cursor = None):
    """Live notices for the authenticated student (all, students, own department/program/semester)."""
    return _call(svc.list_notices, viewer=_viewer(ctx), priority=priority, limit=limit, cursor=cursor)


@router.get("/faculty/me", response_model=Page[Notice])
def my_faculty_notices(ctx: FacultyOnly, priority: NoticePriority | None = None, limit: Limit = 50,
                       cursor: Cursor = None):
    """Live notices for the authenticated faculty member (all, faculty, own department, taught programs/semesters)."""
    return _call(svc.list_notices, viewer=_viewer(ctx), priority=priority, limit=limit, cursor=cursor)


@router.get("/{notice_id}", response_model=Notice)
def get_notice(notice_id: str, ctx: Reader):
    return _call(svc.get_notice, notice_id, _viewer(ctx))


@router.patch("/{notice_id}", response_model=Notice)
def update_notice(notice_id: str, payload: NoticeUpdate, ctx: Admin):
    """ADMIN only. is_active toggles activation, is_published toggles publication."""
    return _call(svc.update_notice, notice_id, payload, _actor(ctx))
