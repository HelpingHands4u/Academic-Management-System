from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers._errors import to_http
from app.schemas.academic import Page
from app.schemas.courses import Section
from app.schemas.people import (
    Batch,
    Designation,
    Enrollment,
    EnrollmentCreate,
    EnrollmentStatus,
    EnrollmentUpdate,
    Faculty,
    FacultyCreate,
    FacultyUpdate,
    PersonId,
    Student,
    StudentCreate,
    StudentUpdate,
)
from app.schemas.user import UserRole
from app.services import enrollments as enrollment_service
from app.services import faculty as faculty_service
from app.services import students as student_service
from app.services.academic_common import Actor, Viewer

Admin = Annotated[AuthContext, Depends(require_admin())]
StudentCtx = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
FacultyCtx = Annotated[AuthContext, Depends(require_roles(UserRole.FACULTY))]
AnyRole = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
StudentOrAdmin = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.STUDENT))]
FacultyOrAdmin = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY))]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
RefQ = Annotated[str | None, Query(max_length=200)]


def _actor(ctx: AuthContext) -> Actor:
    return Actor(ctx.user.uid, ctx.role.value if ctx.role else None)


def _viewer(ctx: AuthContext) -> Viewer:
    p = ctx.profile
    return Viewer(ctx.user.uid, ctx.role.value if ctx.role else None,
                  p.program_id if p else None, p.semester_id if p else None)


def _role(ctx: AuthContext) -> str | None:
    return ctx.role.value if ctx.role else None


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise to_http(exc) from None


# ---- Students -------------------------------------------------------------
students_router = APIRouter(prefix="/students", tags=["students"])


@students_router.post("", response_model=Student, status_code=status.HTTP_201_CREATED)
def create_student(payload: StudentCreate, ctx: Admin):
    return _call(student_service.create_student, payload, _actor(ctx))


@students_router.get("", response_model=Page[Student])
def list_students(
    ctx: Admin,
    department_id: RefQ = None,
    program_id: RefQ = None,
    semester_id: RefQ = None,
    section: Annotated[str | None, Query(max_length=10)] = None,
    batch: Annotated[Batch | None, Query()] = None,
    is_active: bool | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    return _call(student_service.list_students, department_id=department_id, program_id=program_id,
                 semester_id=semester_id, section=section, batch=batch, is_active=is_active,
                 limit=limit, cursor=cursor)


@students_router.get("/me", response_model=Student)
def read_my_student_profile(ctx: StudentCtx):
    return _call(student_service.get_student_by_uid, ctx.user.uid)


@students_router.get("/{student_id}", response_model=Student)
def get_student(student_id: str, ctx: StudentOrAdmin):
    return _call(student_service.get_student_for_viewer, student_id, ctx.user.uid, _role(ctx))


@students_router.patch("/{student_id}", response_model=Student)
def update_student(student_id: str, payload: StudentUpdate, ctx: Admin):
    return _call(student_service.update_student, student_id, payload, _actor(ctx))


# ---- Faculty --------------------------------------------------------------
faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])


@faculty_router.post("", response_model=Faculty, status_code=status.HTTP_201_CREATED)
def create_faculty(payload: FacultyCreate, ctx: Admin):
    return _call(faculty_service.create_faculty, payload, _actor(ctx))


@faculty_router.get("", response_model=Page[Faculty])
def list_faculty(
    ctx: Admin,
    department_id: RefQ = None,
    designation: Annotated[Designation | None, Query()] = None,
    is_active: bool | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    return _call(faculty_service.list_faculty, department_id=department_id, designation=designation,
                 is_active=is_active, limit=limit, cursor=cursor)


@faculty_router.get("/me", response_model=Faculty)
def read_my_faculty_profile(ctx: FacultyCtx):
    return _call(faculty_service.get_faculty_by_uid, ctx.user.uid)


@faculty_router.get("/{faculty_id}", response_model=Faculty)
def get_faculty(faculty_id: str, ctx: FacultyOrAdmin):
    return _call(faculty_service.get_faculty_for_viewer, faculty_id, ctx.user.uid, _role(ctx))


@faculty_router.patch("/{faculty_id}", response_model=Faculty)
def update_faculty(faculty_id: str, payload: FacultyUpdate, ctx: Admin):
    return _call(faculty_service.update_faculty, faculty_id, payload, _actor(ctx))


# ---- Enrollments ----------------------------------------------------------
enrollments_router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@enrollments_router.post("", response_model=Enrollment, status_code=status.HTTP_201_CREATED)
def create_enrollment(payload: EnrollmentCreate, ctx: Admin):
    return _call(enrollment_service.create_enrollment, payload, _actor(ctx))


@enrollments_router.get("", response_model=Page[Enrollment])
def list_enrollments(
    ctx: AnyRole,
    student_id: Annotated[PersonId | None, Query()] = None,
    student_uid: RefQ = None,
    course_offering_id: RefQ = None,
    course_id: RefQ = None,
    semester_id: RefQ = None,
    status: EnrollmentStatus | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    return _call(enrollment_service.list_enrollments, viewer=_viewer(ctx), student_id=student_id,
                 student_uid=student_uid, course_offering_id=course_offering_id, course_id=course_id,
                 semester_id=semester_id, status=status, limit=limit, cursor=cursor)


@enrollments_router.get("/{enrollment_id}", response_model=Enrollment)
def get_enrollment(enrollment_id: str, ctx: AnyRole):
    return _call(enrollment_service.get_enrollment, enrollment_id, _viewer(ctx))


@enrollments_router.patch("/{enrollment_id}", response_model=Enrollment)
def update_enrollment(enrollment_id: str, payload: EnrollmentUpdate, ctx: Admin):
    return _call(enrollment_service.update_enrollment, enrollment_id, payload, _actor(ctx))
