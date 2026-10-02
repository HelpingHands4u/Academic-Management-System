from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers._errors import to_http
from app.schemas.academic import Page, RefId
from app.schemas.marks import (
    GradingScheme,
    GradingSchemeView,
    MarkCreate,
    Mark,
    MarkStatus,
    MarkUpdate,
    MarkView,
    RegradeRequest,
    RegradeResponse,
)
from app.schemas.people import PersonId
from app.schemas.results import (
    CgpaResponse,
    GenerateResultRequest,
    Result,
    ResultStatus,
    SgpaResponse,
)
from app.schemas.user import UserRole
from app.services import grading, marks as marks_svc, results as results_svc
from app.services.academic_common import Actor, Viewer
from app.services.students import get_student, get_student_by_uid
from app.services.departments_programs import slug

Reader = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
Marker = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY))]
Admin = Annotated[AuthContext, Depends(require_admin())]
StudentOnly = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]
RefQ = Annotated[str | None, Query(max_length=200)]
StudentQ = Annotated[PersonId | None, Query()]
GradeQ = Annotated[str | None, Query(max_length=5)]


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


# ---- grading scheme -------------------------------------------------------
grading_router = APIRouter(prefix="/grading-scheme", tags=["grading"])


@grading_router.get("", response_model=GradingSchemeView)
def read_scheme(ctx: Reader):
    """The active, configurable grading scheme (404 until an ADMIN sets one)."""
    return _call(grading.get_scheme_view)


@grading_router.put("", response_model=GradingSchemeView)
def set_scheme(payload: GradingScheme, ctx: Admin):
    """ADMIN only. Bands must tile 0-100 without gaps/overlaps. Existing marks keep their stored
    grade until `POST /grading-scheme/regrade` is run for a semester."""
    return _call(grading.set_scheme, payload, _actor(ctx))


@grading_router.post("/regrade", response_model=RegradeResponse)
def regrade(payload: RegradeRequest, ctx: Admin):
    """ADMIN only. Re-apply the current scheme to a semester's marks and regenerate its results."""
    return _call(marks_svc.regrade_semester, payload.semester_id, _actor(ctx))


# ---- marks ----------------------------------------------------------------
marks_router = APIRouter(prefix="/marks", tags=["marks"])


@marks_router.post("", response_model=Mark, status_code=status.HTTP_201_CREATED)
def create_mark(payload: MarkCreate, ctx: Marker):
    """ADMIN, or FACULTY assigned to the offering. Totals, percentage, grade and grade point are
    calculated by the backend; only an ADMIN can create a FINAL mark."""
    return _call(marks_svc.create_mark, payload, _viewer(ctx))


@marks_router.get("/me", response_model=Page[MarkView])
def my_marks(ctx: StudentOnly, course_id: RefQ = None, course_offering_id: RefQ = None,
             examination_id: RefQ = None, semester_id: RefQ = None, academic_session_id: RefQ = None,
             grade: GradeQ = None, limit: Limit = 50, cursor: Cursor = None):
    """The authenticated student's own FINAL marks."""
    return _call(marks_svc.list_marks, viewer=_viewer(ctx), course_id=course_id,
                 course_offering_id=course_offering_id, examination_id=examination_id, semester_id=semester_id,
                 academic_session_id=academic_session_id, grade=grade, limit=limit, cursor=cursor)


@marks_router.get("", response_model=Page[MarkView])
def list_marks(ctx: Reader, student_id: StudentQ = None, student_uid: RefQ = None, course_id: RefQ = None,
               course_offering_id: RefQ = None, examination_id: RefQ = None, semester_id: RefQ = None,
               academic_session_id: RefQ = None, grade: GradeQ = None, status: MarkStatus | None = None,
               limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: assigned offerings. STUDENT: own FINAL marks (filters only narrow)."""
    return _call(marks_svc.list_marks, viewer=_viewer(ctx), student_id=student_id, student_uid=student_uid,
                 course_id=course_id, course_offering_id=course_offering_id, examination_id=examination_id,
                 semester_id=semester_id, academic_session_id=academic_session_id, grade=grade,
                 status=status, limit=limit, cursor=cursor)


@marks_router.get("/{mark_id}", response_model=MarkView)
def get_mark(mark_id: str, ctx: Reader):
    return _call(marks_svc.get_mark, mark_id, _viewer(ctx))


@marks_router.patch("/{mark_id}", response_model=Mark)
def update_mark(mark_id: str, payload: MarkUpdate, ctx: Marker):
    """ADMIN: any mark. FACULTY: non-final marks of their assigned offerings. Ownership fields are immutable."""
    return _call(marks_svc.update_mark, mark_id, payload, _viewer(ctx))


# ---- results --------------------------------------------------------------
results_router = APIRouter(prefix="/results", tags=["results"])


@results_router.post("/generate", response_model=Result, status_code=status.HTTP_201_CREATED)
def generate_result(payload: GenerateResultRequest, ctx: Admin):
    """ADMIN only. (Re)derives a student's semester result from enrollments, FINAL marks and course
    credits. Results are unpublished until an ADMIN publishes them."""
    return _call(results_svc.generate_result, payload.student_id, payload.semester_id,
                 payload.examination_type, _actor(ctx))


@results_router.get("/me", response_model=Page[Result])
def my_results(ctx: StudentOnly, semester_id: RefQ = None, academic_session_id: RefQ = None,
               limit: Limit = 50, cursor: Cursor = None):
    """The authenticated student's own PUBLISHED results."""
    return _call(results_svc.list_results, viewer=_viewer(ctx), semester_id=semester_id,
                 academic_session_id=academic_session_id, limit=limit, cursor=cursor)


@results_router.get("/me/sgpa", response_model=SgpaResponse)
def my_sgpa(ctx: StudentOnly, semester_id: RefQ = None):
    """Own SGPA per published semester result."""
    return _call(results_svc.sgpa_for, viewer=_viewer(ctx), student_uid=ctx.user.uid, semester_id=semester_id)


@results_router.get("/me/cgpa", response_model=CgpaResponse)
def my_cgpa(ctx: StudentOnly):
    """Own CGPA: credit-weighted over published, COMPLETE semesters."""
    student = _call(get_student_by_uid, ctx.user.uid)
    return _call(results_svc.cgpa_for, viewer=_viewer(ctx), student_uid=student.uid, student_id=student.student_id)


@results_router.get("/sgpa", response_model=SgpaResponse)
def student_sgpa(student_id: PersonId, ctx: Admin, semester_id: RefQ = None):
    """ADMIN only: SGPA of any student (including unpublished results)."""
    student = _call(get_student, slug(student_id))
    return _call(results_svc.sgpa_for, viewer=_viewer(ctx), student_uid=student.uid, semester_id=semester_id)


@results_router.get("/cgpa", response_model=CgpaResponse)
def student_cgpa(student_id: PersonId, ctx: Admin):
    """ADMIN only: CGPA of any student."""
    student = _call(get_student, slug(student_id))
    return _call(results_svc.cgpa_for, viewer=_viewer(ctx), student_uid=student.uid, student_id=student.student_id)


@results_router.get("", response_model=Page[Result])
def list_results(ctx: Reader, student_id: StudentQ = None, semester_id: RefQ = None,
                 academic_session_id: RefQ = None, program_id: RefQ = None,
                 status: ResultStatus | None = None, published: bool | None = None,
                 limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: only course rows of their assigned offerings (no aggregates).
    STUDENT: own published results."""
    return _call(results_svc.list_results, viewer=_viewer(ctx), student_id=student_id, semester_id=semester_id,
                 academic_session_id=academic_session_id, program_id=program_id, status=status,
                 published=published, limit=limit, cursor=cursor)


@results_router.get("/{result_id}", response_model=Result)
def get_result(result_id: str, ctx: Reader):
    return _call(results_svc.get_result, result_id, _viewer(ctx))


@results_router.post("/{result_id}/publish", response_model=Result)
def publish_result(result_id: str, ctx: Admin):
    """ADMIN only. Recomputes the result first; only COMPLETE results can be published."""
    return _call(results_svc.set_published, result_id, True, _actor(ctx))


@results_router.post("/{result_id}/unpublish", response_model=Result)
def unpublish_result(result_id: str, ctx: Admin):
    return _call(results_svc.set_published, result_id, False, _actor(ctx))
