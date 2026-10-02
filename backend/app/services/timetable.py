from __future__ import annotations

import uuid
from datetime import time
from typing import Any

from app.core.errors import (
    AcademicConflictError,
    AcademicNotFoundError,
    AcademicValidationError,
    UnprocessableAcademicError,
)
from app.schemas.academic import Page
from app.schemas.courses import OfferingStatus
from app.schemas.timetable import (
    DAY_ORDER,
    TimetableCreate,
    TimetableEntry,
    TimetableUpdate,
    TimetableView,
)
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor, Viewer
from app.services.academic_sessions import get_session
from app.services.course_offerings import OFFERINGS
from app.services.courses import get_course
from app.services.departments_programs import _apply, get_program
from app.services.exams import _chunks, _faculty_offerings, _offering_students, _student_offering_ids, collect
from app.services.semesters import get_semester

TIMETABLE = "timetable"
FACULTY = "faculty"
OPEN_OFFERING = {OfferingStatus.PLANNED.value, OfferingStatus.ACTIVE.value}


def _admin(role: str | None) -> bool:
    return role == UserRole.ADMIN.value


def _t(value: Any) -> time:
    return value if isinstance(value, time) else time.fromisoformat(str(value))


def new_id() -> str:
    return f"tt_{uuid.uuid4().hex[:20]}"


def check_conflicts(*, own_id: str | None, offering_id: str, session_id: str, faculty_uid: str | None,
                    room: str, day: str, start: time, end: time) -> None:
    """Compare against active entries of the same academic session and weekday.
    Overlap is strict (existing_start < new_end and new_start < existing_end): back-to-back is fine."""
    same_day = collect(TIMETABLE, [("academic_session_id", session_id), ("day_of_week", day),
                                   ("is_active", True)])
    mine: set[str] | None = None
    for other in same_day:
        if other["id"] == own_id:
            continue
        if not (_t(other["start_time"]) < end and start < _t(other["end_time"])):
            continue
        if other["course_offering_id"] == offering_id:
            raise AcademicConflictError("This course offering already has an overlapping timetable entry.")
        if other["room"].casefold() == room.casefold():
            raise AcademicConflictError("The room is already booked for an overlapping timetable entry.")
        if faculty_uid and other.get("faculty_uid") == faculty_uid:
            raise AcademicConflictError("The assigned faculty member has an overlapping timetable entry.")
        if mine is None:
            mine = _offering_students(offering_id)
        if mine and mine & _offering_students(other["course_offering_id"]):
            raise AcademicConflictError("Enrolled students have an overlapping timetable entry.")


def create_entry(payload: TimetableCreate, actor: Actor) -> TimetableEntry:
    row = common.fetch(OFFERINGS, payload.course_offering_id)
    if row is None:
        raise AcademicNotFoundError("Course offering not found.")
    get_course(row["course_id"])  # 404 if the course vanished
    session = get_session(row["academic_session_id"])  # 404
    semester = get_semester(row["semester_id"])  # 404
    program = get_program(row["program_id"])  # 404
    if row.get("status") not in OPEN_OFFERING:
        raise AcademicValidationError("Course offering is not open for timetabling.")
    if (semester.program_id != row["program_id"] or semester.academic_session_id != session.id
            or program.department_id != row["department_id"]):
        raise AcademicValidationError("Course offering has inconsistent academic relationships.")
    derived = {
        "course_id": row["course_id"], "academic_session_id": row["academic_session_id"],
        "semester_id": row["semester_id"], "program_id": row["program_id"],
        "department_id": row["department_id"], "faculty_uid": row.get("faculty_uid"),
        "section": row["section"],
    }
    for key, expected in derived.items():
        supplied = getattr(payload, key)
        if supplied is not None and supplied != expected:
            raise AcademicValidationError(f"{key} does not match the course offering.")

    check_conflicts(own_id=None, offering_id=row["id"], session_id=derived["academic_session_id"],
                    faculty_uid=derived["faculty_uid"], room=payload.room, day=payload.day_of_week.value,
                    start=payload.start_time, end=payload.end_time)
    doc_id = new_id()
    ts = common.now()
    data = {
        "timetable_id": doc_id,
        "course_offering_id": row["id"],
        **derived,
        "day_of_week": payload.day_of_week.value,
        "start_time": payload.start_time.isoformat(),
        "end_time": payload.end_time.isoformat(),
        "room": payload.room,
        "class_type": payload.class_type.value,
        "is_active": True,
        "created_by_uid": actor.uid,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(TIMETABLE, doc_id, data, create=True, conflict_message="Timetable entry already exists.")
    common.audit(actor, "timetable.create", "timetable", doc_id, {"course_offering_id": row["id"]})
    return TimetableEntry(id=doc_id, **data)


def update_entry(entry_id: str, payload: TimetableUpdate, actor: Actor) -> TimetableEntry:
    row = common.fetch(TIMETABLE, entry_id)
    if row is None:
        raise AcademicNotFoundError("Timetable entry not found.")
    current = TimetableEntry(**row)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    for key, value in changes.items():
        if value is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    day = changes.get("day_of_week", current.day_of_week.value)
    start = _t(changes.get("start_time", current.start_time))
    end = _t(changes.get("end_time", current.end_time))
    if end <= start:
        raise UnprocessableAcademicError("end_time must be after start_time.")
    room = changes.get("room", current.room)
    active = changes.get("is_active", current.is_active)
    if active and any(k in changes for k in ("day_of_week", "start_time", "end_time", "room", "is_active")):
        check_conflicts(own_id=entry_id, offering_id=current.course_offering_id,
                        session_id=current.academic_session_id, faculty_uid=current.faculty_uid,
                        room=room, day=day, start=start, end=end)
    result = _apply(TIMETABLE, entry_id, current, changes, TimetableEntry, actor, "timetable")
    if "is_active" in changes and changes["is_active"] != current.is_active:
        common.audit(actor, "timetable.activate" if changes["is_active"] else "timetable.deactivate", "timetable", entry_id, {})
    return result


def _enrich(rows: list[dict[str, Any]]) -> list[TimetableView]:
    courses: dict[str, Any] = {}
    faculty: dict[str, str | None] = {}
    out = []
    for r in rows:
        if r["course_id"] not in courses:
            try:
                courses[r["course_id"]] = get_course(r["course_id"])
            except AcademicNotFoundError:
                courses[r["course_id"]] = None
        uid = r.get("faculty_uid")
        if uid and uid not in faculty:
            found, _ = common.list_docs(FACULTY, [("uid", uid)], 1, None)
            faculty[uid] = found[0].get("display_name") if found else None
        course = courses[r["course_id"]]
        out.append(TimetableView(**r, course_code=course.code if course else None,
                                 course_name=course.name if course else None,
                                 faculty_name=faculty.get(uid) if uid else None))
    return out


def _allowed_offerings(viewer: Viewer) -> set[str]:
    if viewer.role == UserRole.FACULTY.value:
        return {o["id"] for o in _faculty_offerings(viewer.uid)}
    if viewer.role == UserRole.STUDENT.value:
        return set(_student_offering_ids(viewer.uid))
    return set()


def get_entry(entry_id: str, viewer: Viewer) -> TimetableView:
    row = common.fetch(TIMETABLE, entry_id)
    if row is None:
        raise AcademicNotFoundError("Timetable entry not found.")
    if not _admin(viewer.role):
        if not row.get("is_active", True) or row["course_offering_id"] not in _allowed_offerings(viewer):
            raise AcademicNotFoundError("Timetable entry not found.")
    return _enrich([row])[0]


def list_entries(*, viewer: Viewer, limit: int, cursor: str | None, **f) -> Page[TimetableView]:
    """Admin: any scope, Firestore-paginated. Faculty/student: scoped through offerings derived from the
    verified identity (assigned / actively enrolled); request filters can only narrow. Non-admins only
    see active entries, sorted by weekday then start time."""
    day = f.get("day_of_week")
    section = f.get("section")
    filters: list[tuple] = [
        ("academic_session_id", f.get("academic_session_id")),
        ("semester_id", f.get("semester_id")),
        ("program_id", f.get("program_id")),
        ("department_id", f.get("department_id")),
        ("section", section.upper() if section else None),
        ("course_offering_id", f.get("course_offering_id")),
        ("course_id", f.get("course_id")),
        ("faculty_uid", f.get("faculty_uid")),
        ("day_of_week", day.value if day else None),
        ("room", f.get("room")),
        ("is_active", f.get("is_active")),
    ]
    if _admin(viewer.role):
        rows, nxt = common.list_docs(TIMETABLE, filters, limit, cursor)
        return Page[TimetableView](items=_enrich(rows), next_cursor=nxt)
    offering_ids = sorted(_allowed_offerings(viewer))
    if f.get("course_offering_id"):
        offering_ids = [o for o in offering_ids if o == f["course_offering_id"]]
    base = [x for x in filters if x[0] not in ("course_offering_id", "is_active")] + [("is_active", True)]
    rows = []
    for chunk in _chunks(offering_ids):
        rows += collect(TIMETABLE, base + [("course_offering_id", chunk, "in")])
    rows.sort(key=lambda r: (DAY_ORDER[r["day_of_week"]], str(r["start_time"]), r["id"]))
    start = 0
    if cursor:
        start = next((i + 1 for i, r in enumerate(rows) if r["id"] == cursor), 0)
    limit = max(1, min(limit, common.MAX_PAGE_SIZE))
    page = rows[start:start + limit]
    nxt = page[-1]["id"] if start + limit < len(rows) and page else None
    return Page[TimetableView](items=_enrich(page), next_cursor=nxt)

