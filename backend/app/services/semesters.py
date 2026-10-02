from __future__ import annotations

from app.core.errors import AcademicNotFoundError, AcademicValidationError, InvalidDateRangeError
from app.schemas.academic import Page, Semester, SemesterCreate, SemesterUpdate
from app.services import academic_common as common
from app.services.academic_common import Actor
from app.services.academic_sessions import get_session
from app.services.departments_programs import _apply, get_program

SEMESTERS = "semesters"


def semester_id(program_id: str, session_id: str, number: int) -> str:
    return f"{program_id}__{session_id}__{number}"


def create_semester(payload: SemesterCreate, actor: Actor) -> Semester:
    program = get_program(payload.program_id)  # 404 if missing
    session = get_session(payload.academic_session_id)  # 404 if missing
    if not program.is_active:
        raise AcademicValidationError("Program is not active.")
    if not session.is_active:
        raise AcademicValidationError("Academic session is not active.")
    if payload.semester_number > program.total_semesters:
        raise AcademicValidationError("semester_number exceeds the program's total_semesters.")
    # Deterministic id => Firestore create() enforces program+session+number uniqueness.
    doc_id = semester_id(program.id, session.id, payload.semester_number)
    ts = common.now()
    data = {
        **payload.model_dump(),
        "program_id": program.id,
        "academic_session_id": session.id,
        "name": payload.name or f"Semester {payload.semester_number}",
        "is_active": True,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(
        SEMESTERS,
        doc_id,
        data,
        create=True,
        conflict_message="A semester with this program, session and number already exists.",
        clear_current_where=[("program_id", program.id)] if payload.is_current else None,
    )
    common.audit(actor, "semester.create", "semester", doc_id, {"program_id": program.id})
    return Semester(id=doc_id, **data)


def get_semester(sem_id: str, *, include_inactive: bool = True) -> Semester:
    row = common.fetch(SEMESTERS, sem_id)
    if row is None or (not include_inactive and not row.get("is_active", True)):
        raise AcademicNotFoundError("Semester not found.")
    return Semester(**row)


def list_semesters(
    *,
    program_id: str | None,
    academic_session_id: str | None,
    semester_number: int | None,
    is_active: bool | None,
    is_current: bool | None,
    limit: int,
    cursor: str | None,
) -> Page[Semester]:
    rows, nxt = common.list_docs(
        SEMESTERS,
        [
            ("program_id", program_id),
            ("academic_session_id", academic_session_id),
            ("semester_number", semester_number),
            ("is_active", is_active),
            ("is_current", is_current),
        ],
        limit,
        cursor,
    )
    return Page[Semester](items=[Semester(**r) for r in rows], next_cursor=nxt)


def update_semester(sem_id: str, payload: SemesterUpdate, actor: Actor) -> Semester:
    current = get_semester(sem_id)
    changes = payload.model_dump(exclude_unset=True)
    for key in ("start_date", "end_date", "is_current", "is_active", "name"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    if changes.get("start_date", current.start_date) >= changes.get("end_date", current.end_date):
        raise InvalidDateRangeError("start_date must be before end_date.")
    if changes.get("is_active") is False and "is_current" not in changes:
        changes["is_current"] = False
    if changes.get("is_current", current.is_current) and not changes.get("is_active", current.is_active):
        raise AcademicValidationError("An inactive semester cannot be current.")
    if changes.get("is_current") and not current.is_current:
        changes["updated_at"] = common.now()
        common.write(SEMESTERS, sem_id, changes, create=False, clear_current_where=[("program_id", current.program_id)])
        common.audit(actor, "semester.update", "semester", sem_id, {"fields": sorted(changes)})
        return Semester(**{**current.model_dump(), **changes})
    return _apply(SEMESTERS, sem_id, current, changes, Semester, actor, "semester")


def has_active_semesters(program_id: str) -> bool:
    rows, _ = common.list_docs(SEMESTERS, [("program_id", program_id), ("is_active", True)], 1, None)
    return bool(rows)


def max_semester_number(program_id: str) -> int:
    rows, _ = common.list_docs(SEMESTERS, [("program_id", program_id)], 100, None)
    return max((r.get("semester_number", 0) for r in rows), default=0)

