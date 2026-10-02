from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.errors import AcademicForbiddenError, AcademicNotFoundError, AcademicValidationError
from app.schemas.academic import Page
from app.schemas.notices import Notice, NoticeAudience, NoticeCreate, NoticePriority, NoticeUpdate
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor, Viewer
from app.services.academic_sessions import get_session
from app.services.course_offerings import OFFERINGS
from app.services.departments_programs import _apply, get_department, get_program
from app.services.exams import _faculty_offerings, collect
from app.services.faculty import get_faculty_by_uid
from app.services.semesters import get_semester
from app.services.students import get_student_by_uid

NOTICES = "notices"
TARGET_KEYS = ("department_id", "program_id", "semester_id", "academic_session_id")
NOT_NULL = ("title", "description", "audience", "priority", "is_active", "is_published")


def _admin(role: str | None) -> bool:
    return role == UserRole.ADMIN.value


def _resolve_targets(audience: NoticeAudience, supplied: dict[str, str | None]) -> dict[str, str | None]:
    """Validate the target ids against Firestore and derive the academic chain from the most specific one.
    DEPARTMENT/PROGRAM/SEMESTER notices require their own target; other audiences take no target
    except an optional academic_session_id."""
    dept, prog, sem, sess = (supplied.get(k) for k in TARGET_KEYS)
    required = {NoticeAudience.DEPARTMENT: dept, NoticeAudience.PROGRAM: prog, NoticeAudience.SEMESTER: sem}
    if audience in required:
        if not required[audience]:
            raise AcademicValidationError(f"audience {audience.value} requires its target id.")
    elif dept or prog or sem:
        raise AcademicValidationError(
            f"audience {audience.value} does not accept department_id, program_id or semester_id.")
    out: dict[str, str | None] = {"department_id": None, "program_id": None, "semester_id": None,
                                  "academic_session_id": None}
    if sess:
        get_session(sess)  # 404
        out["academic_session_id"] = sess
    if sem:
        semester = get_semester(sem)  # 404
        program = get_program(semester.program_id)
        out.update(semester_id=sem, program_id=program.id, department_id=program.department_id)
        if sess and sess != semester.academic_session_id:
            raise AcademicValidationError("Semester does not belong to the specified academic session.")
        out["academic_session_id"] = semester.academic_session_id
        if prog and prog != program.id:
            raise AcademicValidationError("Semester does not belong to the specified program.")
        if dept and dept != program.department_id:
            raise AcademicValidationError("Program does not belong to the specified department.")
    elif prog:
        program = get_program(prog)  # 404
        out.update(program_id=prog, department_id=program.department_id)
        if dept and dept != program.department_id:
            raise AcademicValidationError("Program does not belong to the specified department.")
    elif dept:
        get_department(dept)  # 404
        out["department_id"] = dept
    return out


def create_notice(payload: NoticeCreate, actor: Actor) -> Notice:
    targets = _resolve_targets(payload.audience, payload.model_dump())
    doc_id = f"nt_{uuid.uuid4().hex[:20]}"
    ts = common.now()
    data = {
        "notice_id": doc_id,
        "title": payload.title,
        "description": payload.description,
        "audience": payload.audience.value,
        **targets,
        "creator_uid": actor.uid,
        "creator_role": actor.role,
        "priority": payload.priority.value,
        "publish_at": payload.publish_at,
        "expiry_at": payload.expiry_at,
        "is_published": payload.is_published,
        "is_active": True,
        "attachment_url": payload.attachment_url,
        "metadata": payload.metadata,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(NOTICES, doc_id, data, create=True, conflict_message="Notice already exists.")
    common.audit(actor, "notice.create", "notice", doc_id, {"audience": payload.audience.value})
    return Notice(id=doc_id, **data)


def update_notice(notice_id: str, payload: NoticeUpdate, actor: Actor) -> Notice:
    row = common.fetch(NOTICES, notice_id)
    if row is None:
        raise AcademicNotFoundError("Notice not found.")
    current = Notice(**row)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True)
    for key in NOT_NULL:
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    if any(k in changes for k in TARGET_KEYS) and "audience" not in changes:
        raise AcademicValidationError("Targets can only be changed together with audience.")
    if "audience" in changes:
        targets = _resolve_targets(payload.audience, {k: changes.get(k) for k in TARGET_KEYS})
        changes.update(targets)
    publish_at = changes.get("publish_at", current.publish_at)
    expiry_at = changes.get("expiry_at", current.expiry_at)
    if publish_at and expiry_at and expiry_at < publish_at:
        raise AcademicValidationError("expiry_at must not be before publish_at.")
    for key in ("audience", "priority"):  # store enum values, not members
        if key in changes:
            changes[key] = changes[key].value
    result = _apply(NOTICES, notice_id, current, changes, Notice, actor, "notice")
    for flag, on, off in (("is_active", "activate", "deactivate"), ("is_published", "publish", "unpublish")):
        if flag in changes and changes[flag] != getattr(current, flag):
            common.audit(actor, f"notice.{on if changes[flag] else off}", "notice", notice_id, {})
    return result


# ---- Audience model -------------------------------------------------------
def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def is_live(row: dict[str, Any], at: datetime) -> bool:
    """Active, published, started and not expired at `at`."""
    if not row.get("is_active", True) or not row.get("is_published", True):
        return False
    start, end = _aware(row.get("publish_at")), _aware(row.get("expiry_at"))
    return (start is None or start <= at) and (end is None or at < end)


def audience_context(viewer: Viewer) -> dict[str, set[str]]:
    """Trusted academic scope of the caller, from Firestore (never from request data)."""
    ctx: dict[str, set[str]] = {"departments": set(), "programs": set(), "semesters": set()}
    if viewer.role == UserRole.STUDENT.value:
        try:
            s = get_student_by_uid(viewer.uid)
        except AcademicNotFoundError:
            return ctx
        ctx["departments"].add(s.department_id)
        ctx["programs"].add(s.program_id)
        if s.current_semester_id:
            ctx["semesters"].add(s.current_semester_id)
    elif viewer.role == UserRole.FACULTY.value:
        try:
            ctx["departments"].add(get_faculty_by_uid(viewer.uid).department_id)
        except AcademicNotFoundError:
            pass
        for o in _faculty_offerings(viewer.uid):
            ctx["programs"].add(o["program_id"])
            ctx["semesters"].add(o["semester_id"])
    return ctx


def matches_audience(row: dict[str, Any], role: str | None, ctx: dict[str, set[str]]) -> bool:
    audience = row.get("audience")
    if audience == NoticeAudience.ALL.value:
        return True
    if audience == NoticeAudience.STUDENTS.value:
        return role == UserRole.STUDENT.value
    if audience == NoticeAudience.FACULTY.value:
        return role == UserRole.FACULTY.value
    if role not in (UserRole.STUDENT.value, UserRole.FACULTY.value):
        return False
    if audience == NoticeAudience.DEPARTMENT.value:
        return row.get("department_id") in ctx["departments"]
    if audience == NoticeAudience.PROGRAM.value:
        return row.get("program_id") in ctx["programs"]
    if audience == NoticeAudience.SEMESTER.value:
        return row.get("semester_id") in ctx["semesters"]
    return False


def _feed(viewer: Viewer, filters: list[tuple]) -> list[dict[str, Any]]:
    at = common.now()
    ctx = audience_context(viewer)
    rows = collect(NOTICES, [*filters, ("is_active", True), ("is_published", True)])
    kept = [r for r in rows if is_live(r, at) and matches_audience(r, viewer.role, ctx)]
    kept.sort(key=lambda r: (_aware(r.get("created_at")) or at, r["id"]), reverse=True)
    return kept


def get_notice(notice_id: str, viewer: Viewer) -> Notice:
    row = common.fetch(NOTICES, notice_id)
    if row is None:
        raise AcademicNotFoundError("Notice not found.")
    if not _admin(viewer.role):
        if not is_live(row, common.now()) or not matches_audience(row, viewer.role, audience_context(viewer)):
            raise AcademicNotFoundError("Notice not found.")
    return Notice(**row)


def list_notices(*, viewer: Viewer, limit: int, cursor: str | None, **f) -> Page[Notice]:
    """Admin: every notice (Firestore-paginated, any filter). Others: only their live, audience-matching
    feed; filters can only narrow it."""
    audience, priority = f.get("audience"), f.get("priority")
    filters: list[tuple] = [
        ("audience", audience.value if audience else None),
        ("department_id", f.get("department_id")),
        ("program_id", f.get("program_id")),
        ("semester_id", f.get("semester_id")),
        ("academic_session_id", f.get("academic_session_id")),
        ("priority", priority.value if priority else None),
    ]
    if _admin(viewer.role):
        filters += [("is_active", f.get("is_active")), ("is_published", f.get("is_published"))]
        rows, nxt = common.list_docs(NOTICES, filters, limit, cursor)
        return Page[Notice](items=[Notice(**r) for r in rows], next_cursor=nxt)
    if viewer.role not in (UserRole.STUDENT.value, UserRole.FACULTY.value):
        raise AcademicForbiddenError("Not permitted.")
    if f.get("is_active") is False or f.get("is_published") is False:
        return Page[Notice](items=[], next_cursor=None)
    rows = _feed(viewer, filters)
    start = 0
    if cursor:
        start = next((i + 1 for i, r in enumerate(rows) if r["id"] == cursor), 0)
    limit = max(1, min(limit, common.MAX_PAGE_SIZE))
    page = rows[start:start + limit]
    nxt = page[-1]["id"] if start + limit < len(rows) and page else None
    return Page[Notice](items=[Notice(**r) for r in page], next_cursor=nxt)
