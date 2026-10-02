from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.core.security import AuthContext, require_admin, require_roles
from app.routers.exams import Cursor, Limit, RefQ, _actor, _call, _viewer
from app.schemas.academic import Page
from app.schemas.analytics import ActiveUsers, AdminAnalytics, FacultyAnalytics, StudentAnalytics
from app.schemas.audit import AuditLog
from app.schemas.courses import CourseType
from app.schemas.people import EnrollmentStatus
from app.schemas.reports import Report
from app.schemas.results import ResultStatus
from app.schemas.sessions import SessionCreate, SessionStarted, UserSession
from app.schemas.user import UserRole
from app.services import analytics as analytics_svc
from app.services import audit_logs as audit_svc
from app.services import reports as reports_svc
from app.services import sessions as sessions_svc

Admin = Annotated[AuthContext, Depends(require_admin())]
AnyRole = Annotated[AuthContext, Depends(require_roles(UserRole.ADMIN, UserRole.FACULTY, UserRole.STUDENT))]
StudentOnly = Annotated[AuthContext, Depends(require_roles(UserRole.STUDENT))]
FacultyOnly = Annotated[AuthContext, Depends(require_roles(UserRole.FACULTY))]

# ---- Audit logs -------------------------------------------------------------
audit_router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@audit_router.get("", response_model=Page[AuditLog])
def list_audit_logs(ctx: Admin, actor_uid: RefQ = None, actor_role: RefQ = None, action: RefQ = None,
                    resource_type: RefQ = None, resource_id: RefQ = None,
                    from_time: Annotated[datetime | None, Query(alias="from")] = None,
                    to_time: Annotated[datetime | None, Query(alias="to")] = None,
                    limit: Limit = 50, cursor: Cursor = None):
    """ADMIN only. Oldest first. Time-range queries combined with equality filters may need a composite index."""
    return _call(audit_svc.list_audit_logs, actor_uid=actor_uid, actor_role=actor_role, action=action,
                 resource_type=resource_type, resource_id=resource_id, from_time=from_time, to_time=to_time,
                 limit=limit, cursor=cursor)


# ---- Sessions ---------------------------------------------------------------
sessions_router = APIRouter(prefix="/sessions", tags=["sessions"])


@sessions_router.post("", response_model=SessionStarted, status_code=status.HTTP_201_CREATED)
def start_session(ctx: AnyRole, payload: SessionCreate | None = None,
                  user_agent: Annotated[str | None, Header()] = None):
    """Start a tracked session for the authenticated user. uid/role come from the verified token."""
    return _call(sessions_svc.start_session, _viewer(ctx), payload, user_agent)


@sessions_router.patch("/{session_id}/heartbeat", response_model=UserSession)
def heartbeat(session_id: str, ctx: AnyRole):
    """Owner or ADMIN. Updates last_seen_at only. 409 when the session is closed."""
    return _call(sessions_svc.heartbeat, session_id, _viewer(ctx))


@sessions_router.post("/{session_id}/logout", response_model=UserSession)
def logout(session_id: str, ctx: AnyRole):
    """Owner or ADMIN. Closes the session (kept, not deleted). Idempotent."""
    return _call(sessions_svc.logout, session_id, _viewer(ctx))


# ---- Analytics --------------------------------------------------------------
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


@analytics_router.get("/admin", response_model=AdminAnalytics)
def admin_analytics(ctx: Admin):
    """ADMIN only. Counts come from Firestore COUNT aggregations."""
    return _call(analytics_svc.admin_overview)


@analytics_router.get("/faculty/me", response_model=FacultyAnalytics)
def faculty_analytics(ctx: FacultyOnly):
    return _call(analytics_svc.faculty_overview, _viewer(ctx))


@analytics_router.get("/student/me", response_model=StudentAnalytics)
def student_analytics(ctx: StudentOnly):
    return _call(analytics_svc.student_overview, _viewer(ctx))


@analytics_router.get("/active-users", response_model=ActiveUsers)
def active_users(ctx: Admin, include_sessions: bool = False):
    """ADMIN only. Active = open session seen within SESSION_ACTIVE_WINDOW_SECONDS."""
    return _call(analytics_svc.active_users, include_sessions)


# ---- Reports ----------------------------------------------------------------
reports_router = APIRouter(prefix="/reports", tags=["reports"])
FromDate = Annotated[date | None, Query()]


@reports_router.get("/students", response_model=Report)
def students_report(ctx: Admin, department_id: RefQ = None, program_id: RefQ = None, semester_id: RefQ = None,
                    section: RefQ = None, batch: RefQ = None, is_active: bool | None = None,
                    limit: Limit = 50, cursor: Cursor = None):
    """ADMIN only."""
    return _call(reports_svc.student_report, _viewer(ctx), department_id=department_id, program_id=program_id,
                 semester_id=semester_id, section=section, batch=batch, is_active=is_active, limit=limit, cursor=cursor)


@reports_router.get("/faculty", response_model=Report)
def faculty_report(ctx: Admin, department_id: RefQ = None, designation: RefQ = None, is_active: bool | None = None,
                   limit: Limit = 50, cursor: Cursor = None):
    """ADMIN only."""
    return _call(reports_svc.faculty_report, _viewer(ctx), department_id=department_id, designation=designation,
                 is_active=is_active, limit=limit, cursor=cursor)


@reports_router.get("/courses", response_model=Report)
def courses_report(ctx: AnyRole, department_id: RefQ = None, program_id: RefQ = None,
                   semester_number: int | None = Query(default=None, ge=1), course_type: CourseType | None = None,
                   is_active: bool | None = None, limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all courses. FACULTY: courses of assigned offerings. STUDENT: 403."""
    return _call(reports_svc.course_report, _viewer(ctx), department_id=department_id, program_id=program_id,
                 semester_number=semester_number, course_type=course_type, is_active=is_active,
                 limit=limit, cursor=cursor)


@reports_router.get("/attendance", response_model=Report)
def attendance_report(ctx: AnyRole, academic_session_id: RefQ = None, semester_id: RefQ = None, course_id: RefQ = None,
                      course_offering_id: RefQ = None, student_id: RefQ = None, faculty_id: RefQ = None,
                      from_date: FromDate = None, to_date: FromDate = None, limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: assigned offerings. STUDENT: own attendance only."""
    return _call(reports_svc.attendance_report, _viewer(ctx), academic_session_id=academic_session_id,
                 semester_id=semester_id, course_id=course_id, course_offering_id=course_offering_id,
                 student_id=student_id, faculty_id=faculty_id, from_date=from_date, to_date=to_date,
                 limit=limit, cursor=cursor)


@reports_router.get("/examinations", response_model=Report)
def examinations_report(ctx: AnyRole, academic_session_id: RefQ = None, semester_id: RefQ = None,
                        program_id: RefQ = None, department_id: RefQ = None, course_id: RefQ = None,
                        course_offering_id: RefQ = None, faculty_id: RefQ = None, from_date: FromDate = None,
                        to_date: FromDate = None, limit: Limit = 50, cursor: Cursor = None):
    """Exam schedules visible to the caller (same scoping as /exam-schedules)."""
    return _call(reports_svc.examination_report, _viewer(ctx), academic_session_id=academic_session_id,
                 semester_id=semester_id, program_id=program_id, department_id=department_id, course_id=course_id,
                 course_offering_id=course_offering_id, faculty_id=faculty_id, from_date=from_date,
                 to_date=to_date, limit=limit, cursor=cursor)


@reports_router.get("/results", response_model=Report)
def results_report(ctx: AnyRole, academic_session_id: RefQ = None, semester_id: RefQ = None, program_id: RefQ = None,
                   student_id: RefQ = None, status: ResultStatus | None = None, published: bool | None = None,
                   limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: course rows of assigned offerings. STUDENT: own published results."""
    return _call(reports_svc.result_report, _viewer(ctx), academic_session_id=academic_session_id,
                 semester_id=semester_id, program_id=program_id, student_id=student_id, status=status,
                 published=published, limit=limit, cursor=cursor)


@reports_router.get("/enrollments", response_model=Report)
def enrollments_report(ctx: AnyRole, academic_session_id: RefQ = None, semester_id: RefQ = None,
                       program_id: RefQ = None, course_id: RefQ = None, course_offering_id: RefQ = None,
                       student_id: RefQ = None, status: EnrollmentStatus | None = None, from_date: FromDate = None,
                       to_date: FromDate = None, limit: Limit = 50, cursor: Cursor = None):
    """ADMIN: all. FACULTY: assigned offerings. STUDENT: own enrollments."""
    return _call(reports_svc.enrollment_report, _viewer(ctx), academic_session_id=academic_session_id,
                 semester_id=semester_id, program_id=program_id, course_id=course_id,
                 course_offering_id=course_offering_id, student_id=student_id, status=status,
                 from_date=from_date, to_date=to_date, limit=limit, cursor=cursor)
