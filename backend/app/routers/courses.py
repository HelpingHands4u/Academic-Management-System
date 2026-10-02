from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers._errors import to_http
from app.schemas.academic import Page
from app.schemas.courses import (
    Course,
    CourseCreate,
    CourseOffering,
    CourseType,
    CourseUpdate,
    OfferingCreate,
    OfferingStatus,
    OfferingUpdate,
    SearchPrefix,
)
from app.schemas.user import UserRole
from app.services import course_offerings as offerings
from app.services import courses
from app.services.academic_common import Actor, Viewer

Reader = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Admin = Annotated[AuthContext, Depends(require_admin())]
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


courses_router = APIRouter(prefix="/courses", tags=["courses"])


@courses_router.post("", response_model=Course, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, ctx: Admin):
    return _call(courses.create_course, payload, _actor(ctx))


@courses_router.get("", response_model=Page[Course])
def list_courses(
    ctx: Reader,
    department_id: RefQ = None,
    program_id: RefQ = None,
    semester_number: Annotated[int | None, Query(gt=0, le=20)] = None,
    course_type: CourseType | None = None,
    is_active: bool | None = None,
    search: Annotated[SearchPrefix | None, Query(description="Course code prefix.")] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    admin = ctx.role == UserRole.ADMIN
    return _call(
        courses.list_courses,
        department_id=department_id,
        program_id=program_id,
        semester_number=semester_number,
        course_type=course_type,
        is_active=is_active if admin else True,
        code_prefix=search,
        limit=limit,
        cursor=cursor,
    )


@courses_router.get("/{course_id}", response_model=Course)
def get_course(course_id: str, ctx: Reader):
    return _call(courses.get_course, course_id, include_inactive=ctx.role == UserRole.ADMIN)


@courses_router.patch("/{course_id}", response_model=Course)
def update_course(course_id: str, payload: CourseUpdate, ctx: Admin):
    return _call(courses.update_course, course_id, payload, _actor(ctx))


offerings_router = APIRouter(prefix="/course-offerings", tags=["course-offerings"])


@offerings_router.post("", response_model=CourseOffering, status_code=status.HTTP_201_CREATED)
def create_offering(payload: OfferingCreate, ctx: Admin):
    return _call(offerings.create_offering, payload, _actor(ctx))


@offerings_router.get("", response_model=Page[CourseOffering])
def list_offerings(
    ctx: Reader,
    course_id: RefQ = None,
    academic_session_id: RefQ = None,
    semester_id: RefQ = None,
    program_id: RefQ = None,
    department_id: RefQ = None,
    faculty_uid: RefQ = None,
    section: Annotated[str | None, Query(max_length=10)] = None,
    status: OfferingStatus | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    return _call(
        offerings.list_offerings,
        viewer=_viewer(ctx),
        course_id=course_id,
        academic_session_id=academic_session_id,
        semester_id=semester_id,
        program_id=program_id,
        department_id=department_id,
        faculty_uid=faculty_uid,
        section=section,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@offerings_router.get("/{offering_id}", response_model=CourseOffering)
def get_offering(offering_id: str, ctx: Reader):
    return _call(offerings.get_offering, offering_id, _viewer(ctx))


@offerings_router.patch("/{offering_id}", response_model=CourseOffering)
def update_offering(offering_id: str, payload: OfferingUpdate, ctx: Admin):
    return _call(offerings.update_offering, offering_id, payload, _actor(ctx))
