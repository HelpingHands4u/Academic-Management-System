from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers._errors import to_http
from app.schemas.academic import (
    AcademicSession,
    AcademicSessionCreate,
    AcademicSessionUpdate,
    Department,
    DepartmentCreate,
    DepartmentUpdate,
    Page,
    Program,
    ProgramCreate,
    ProgramUpdate,
    Semester,
    SemesterCreate,
    SemesterUpdate,
)
from app.schemas.user import UserRole
from app.services import academic_sessions as sessions
from app.services import departments_programs as dp
from app.services import semesters as sems
from app.services.academic_common import Actor

# Reads need an authenticated, active user holding any portal role.
Reader = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Admin = Annotated[AuthContext, Depends(require_admin())]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
RefQ = Annotated[str | None, Query(max_length=200)]


def _actor(ctx: AuthContext) -> Actor:
    return Actor(ctx.user.uid, ctx.role.value if ctx.role else None)


def _is_admin(ctx: AuthContext) -> bool:
    return ctx.role == UserRole.ADMIN


def _active_filter(ctx: AuthContext, is_active: bool | None) -> bool | None:
    """Non-admins only ever see active records, whatever they ask for."""
    return is_active if _is_admin(ctx) else True


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise to_http(exc) from None


# ---- Departments ----------------------------------------------------------
departments_router = APIRouter(prefix="/departments", tags=["departments"])


@departments_router.post("", response_model=Department, status_code=status.HTTP_201_CREATED)
def create_department(payload: DepartmentCreate, ctx: Admin):
    return _call(dp.create_department, payload, _actor(ctx))


@departments_router.get("", response_model=Page[Department])
def list_departments(ctx: Reader, is_active: bool | None = None, limit: Limit = 50, cursor: Cursor = None):
    return _call(dp.list_departments, is_active=_active_filter(ctx, is_active), limit=limit, cursor=cursor)


@departments_router.get("/{department_id}", response_model=Department)
def get_department(department_id: str, ctx: Reader):
    return _call(dp.get_department, department_id, include_inactive=_is_admin(ctx))


@departments_router.patch("/{department_id}", response_model=Department)
def update_department(department_id: str, payload: DepartmentUpdate, ctx: Admin):
    return _call(dp.update_department, department_id, payload, _actor(ctx))


# ---- Programs -------------------------------------------------------------
programs_router = APIRouter(prefix="/programs", tags=["programs"])


@programs_router.post("", response_model=Program, status_code=status.HTTP_201_CREATED)
def create_program(payload: ProgramCreate, ctx: Admin):
    return _call(dp.create_program, payload, _actor(ctx))


@programs_router.get("", response_model=Page[Program])
def list_programs(
    ctx: Reader, department_id: RefQ = None, is_active: bool | None = None, limit: Limit = 50, cursor: Cursor = None
):
    return _call(
        dp.list_programs,
        department_id=department_id,
        is_active=_active_filter(ctx, is_active),
        limit=limit,
        cursor=cursor,
    )


@programs_router.get("/{program_id}", response_model=Program)
def get_program(program_id: str, ctx: Reader):
    return _call(dp.get_program, program_id, include_inactive=_is_admin(ctx))


@programs_router.patch("/{program_id}", response_model=Program)
def update_program(program_id: str, payload: ProgramUpdate, ctx: Admin):
    return _call(dp.update_program, program_id, payload, _actor(ctx))


# ---- Academic sessions ----------------------------------------------------
sessions_router = APIRouter(prefix="/academic-sessions", tags=["academic-sessions"])


@sessions_router.post("", response_model=AcademicSession, status_code=status.HTTP_201_CREATED)
def create_session(payload: AcademicSessionCreate, ctx: Admin):
    return _call(sessions.create_session, payload, _actor(ctx))


@sessions_router.get("", response_model=Page[AcademicSession])
def list_sessions(
    ctx: Reader,
    is_active: bool | None = None,
    is_current: bool | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    return _call(
        sessions.list_sessions,
        is_active=_active_filter(ctx, is_active),
        is_current=is_current,
        limit=limit,
        cursor=cursor,
    )


@sessions_router.get("/{session_id}", response_model=AcademicSession)
def get_session(session_id: str, ctx: Reader):
    return _call(sessions.get_session, session_id, include_inactive=_is_admin(ctx))


@sessions_router.patch("/{session_id}", response_model=AcademicSession)
def update_session(session_id: str, payload: AcademicSessionUpdate, ctx: Admin):
    return _call(sessions.update_session, session_id, payload, _actor(ctx))


# ---- Semesters ------------------------------------------------------------
semesters_router = APIRouter(prefix="/semesters", tags=["semesters"])


@semesters_router.post("", response_model=Semester, status_code=status.HTTP_201_CREATED)
def create_semester(payload: SemesterCreate, ctx: Admin):
    return _call(sems.create_semester, payload, _actor(ctx))


@semesters_router.get("", response_model=Page[Semester])
def list_semesters(
    ctx: Reader,
    program_id: RefQ = None,
    academic_session_id: RefQ = None,
    semester_number: Annotated[int | None, Query(gt=0, le=20)] = None,
    is_active: bool | None = None,
    is_current: bool | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    return _call(
        sems.list_semesters,
        program_id=program_id,
        academic_session_id=academic_session_id,
        semester_number=semester_number,
        is_active=_active_filter(ctx, is_active),
        is_current=is_current,
        limit=limit,
        cursor=cursor,
    )


@semesters_router.get("/{semester_id}", response_model=Semester)
def get_semester(semester_id: str, ctx: Reader):
    return _call(sems.get_semester, semester_id, include_inactive=_is_admin(ctx))


@semesters_router.patch("/{semester_id}", response_model=Semester)
def update_semester(semester_id: str, payload: SemesterUpdate, ctx: Admin):
    return _call(sems.update_semester, semester_id, payload, _actor(ctx))

