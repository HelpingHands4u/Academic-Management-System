from __future__ import annotations

from datetime import date, time
from typing import Any

from app.core.errors import (
    AcademicConflictError,
    AcademicNotFoundError,
    AcademicValidationError,
    UnprocessableAcademicError,
)
from app.schemas.academic import Page
from app.schemas.courses import OfferingStatus
from app.schemas.exams import (
    Examination,
    ExaminationCreate,
    ExaminationStatus,
    ExaminationType,
    ExaminationUpdate,
    ExamSchedule,
    ExamScheduleCreate,
    ExamScheduleUpdate,
    ExamScheduleView,
    ScheduleStatus,
)
from app.schemas.people import EnrollmentStatus
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor, Viewer
from app.services.academic_sessions import get_session
from app.services.course_offerings import OFFERINGS
from app.services.courses import get_course
from app.services.departments_programs import _apply, get_program, slug
from app.services.enrollments import ENROLLMENTS
from app.services.semesters import get_semester

EXAMINATIONS = "examinations"
EXAM_SCHEDULES = "exam_schedules"
IN_LIMIT = 30  # Firestore `in` operator limit
MAX_SCAN = 2000  # upper bound for in-memory collection of role-scoped / conflict candidates
CLOSED_EXAMS = {ExaminationStatus.COMPLETED.value, ExaminationStatus.CANCELLED.value}


def _admin(role: str | None) -> bool:
    return role == UserRole.ADMIN.value


def examination_id(semester_id: str, exam_type: str, name: str) -> str:
    return f"{semester_id}__{exam_type.lower()}__{slug(name)}"


def schedule_id(exam_id: str, offering_id: str) -> str:
    return f"{exam_id}__{offering_id}"


def _collect(collection: str, filters: list[tuple], cap: int = MAX_SCAN) -> list[dict[str, Any]]:
    """Read every matching document (bounded) using the shared paginated helper."""
    rows: list[dict[str, Any]] = []
    cursor = None
    while True:
        page, cursor = common.list_docs(collection, filters, common.MAX_PAGE_SIZE, cursor)
        rows.extend(page)
        if len(rows) > cap:
            raise AcademicValidationError("Too many records; narrow the filters.")
        if cursor is None:
            return rows


collect = _collect  # shared with the marks/results services


def _chunks(values: list[str]):
    for i in range(0, len(values), IN_LIMIT):
        yield values[i:i + IN_LIMIT]


# ---- Examinations ---------------------------------------------------------
def create_examination(payload: ExaminationCreate, actor: Actor) -> Examination:
    semester = get_semester(payload.semester_id)  # 404
    if payload.academic_session_id:
        get_session(payload.academic_session_id)  # 404
    if payload.program_id:
        get_program(payload.program_id)  # 404
    session = get_session(semester.academic_session_id)
    program = get_program(semester.program_id)
    if payload.academic_session_id and payload.academic_session_id != session.id:
        raise AcademicValidationError("Semester does not belong to the specified academic session.")
    if payload.program_id and payload.program_id != program.id:
        raise AcademicValidationError("Semester does not belong to the specified program.")
    if payload.department_id and payload.department_id != program.department_id:
        raise AcademicValidationError("Program does not belong to the specified department.")
    for label, active in (("Semester", semester.is_active), ("Academic session", session.is_active),
                          ("Program", program.is_active)):
        if not active:
            raise AcademicValidationError(f"{label} is not active.")

    doc_id = examination_id(semester.id, payload.examination_type.value, payload.name)
    ts = common.now()
    data = {
        "examination_id": doc_id,
        "name": payload.name,
        "examination_type": payload.examination_type.value,
        "academic_session_id": session.id,
        "semester_id": semester.id,
        "program_id": program.id,
        "department_id": program.department_id,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "status": payload.status.value,
        "description": payload.description,
        "created_by_uid": actor.uid,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(EXAMINATIONS, doc_id, data, create=True,
                 conflict_message="An examination with this name and type already exists for the semester.")
    common.audit(actor, "examination.create", "examination", doc_id, {"semester_id": semester.id})
    return Examination(id=doc_id, **data)


def _faculty_offerings(uid: str) -> list[dict[str, Any]]:
    return _collect(OFFERINGS, [("faculty_uid", uid)])


def _student_offering_ids(uid: str) -> list[str]:
    rows = _collect(ENROLLMENTS, [("student_uid", uid), ("status", EnrollmentStatus.ACTIVE.value)])
    return sorted({r["course_offering_id"] for r in rows})


def _can_see_examination(viewer: Viewer, exam: Examination) -> bool:
    if _admin(viewer.role):
        return True
    if exam.status == ExaminationStatus.DRAFT:
        return False
    if viewer.role == UserRole.FACULTY.value:
        return any(o.get("semester_id") == exam.semester_id for o in _faculty_offerings(viewer.uid))
    if viewer.role == UserRole.STUDENT.value:
        return bool(viewer.semester_id) and viewer.semester_id == exam.semester_id
    return False


def get_examination(exam_id: str, viewer: Viewer | None = None) -> Examination:
    row = common.fetch(EXAMINATIONS, exam_id)
    if row is None:
        raise AcademicNotFoundError("Examination not found.")
    exam = Examination(**row)
    if viewer is not None and not _can_see_examination(viewer, exam):
        raise AcademicNotFoundError("Examination not found.")
    return exam


def list_examinations(*, viewer: Viewer, academic_session_id, semester_id, program_id, department_id,
                      examination_type: ExaminationType | None, status: ExaminationStatus | None,
                      limit: int, cursor: str | None) -> Page[Examination]:
    filters: list[tuple] = []
    visible = [s.value for s in ExaminationStatus if s != ExaminationStatus.DRAFT]
    drop_semesters: set[str] | None = None
    if viewer.role == UserRole.STUDENT.value:
        if not viewer.semester_id:
            return Page[Examination](items=[], next_cursor=None)
        if semester_id and semester_id != viewer.semester_id:
            return Page[Examination](items=[], next_cursor=None)
        semester_id = viewer.semester_id
    elif viewer.role == UserRole.FACULTY.value:
        drop_semesters = {o["semester_id"] for o in _faculty_offerings(viewer.uid)}
        if semester_id and semester_id not in drop_semesters:
            return Page[Examination](items=[], next_cursor=None)
        if not drop_semesters:
            return Page[Examination](items=[], next_cursor=None)
    elif not _admin(viewer.role):
        return Page[Examination](items=[], next_cursor=None)
    if not _admin(viewer.role):
        if status is not None and status.value not in visible:
            return Page[Examination](items=[], next_cursor=None)
        filters.append(("status", visible if status is None else status.value,
                        "in" if status is None else "=="))
        status = None
    filters += [
        ("academic_session_id", academic_session_id),
        ("semester_id", semester_id),
        ("program_id", program_id),
        ("department_id", department_id),
        ("examination_type", examination_type.value if examination_type else None),
        ("status", status.value if status else None),
    ]
    rows, nxt = common.list_docs(EXAMINATIONS, filters, limit, cursor)
    items = [Examination(**r) for r in rows]
    if drop_semesters is not None:  # faculty: only semesters of their assigned offerings
        items = [e for e in items if e.semester_id in drop_semesters]
    return Page[Examination](items=items, next_cursor=nxt)


def update_examination(exam_id: str, payload: ExaminationUpdate, actor: Actor) -> Examination:
    current = get_examination(exam_id)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    for key in ("name", "start_date", "end_date", "status"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    if "name" in changes and changes["name"] != current.name:
        # The id embeds the name; renaming would silently diverge from it.
        raise AcademicValidationError("Examination name is immutable.")
    start = date.fromisoformat(changes.get("start_date", current.start_date.isoformat()))
    end = date.fromisoformat(changes.get("end_date", current.end_date.isoformat()))
    if start > end:
        raise UnprocessableAcademicError("start_date must not be after end_date.")
    if "start_date" in changes or "end_date" in changes:
        for sched in _collect(EXAM_SCHEDULES, [("examination_id", exam_id)]):
            if sched["status"] != ScheduleStatus.CANCELLED.value and not (
                    start <= date.fromisoformat(str(sched["exam_date"])) <= end):
                raise AcademicConflictError("Existing exam schedules fall outside the new date range.")
    return _apply(EXAMINATIONS, exam_id, current, changes, Examination, actor, "examination")


# ---- Exam schedules -------------------------------------------------------
def _t(value: Any) -> time:
    return value if isinstance(value, time) else time.fromisoformat(str(value))


def _d(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _require_in_range(exam: Examination, on: date) -> None:
    if not (exam.start_date <= on <= exam.end_date):
        raise UnprocessableAcademicError("exam_date must fall within the examination's date range.")


def _offering_students(offering_id: str) -> set[str]:
    rows = _collect(ENROLLMENTS, [("course_offering_id", offering_id),
                                  ("status", EnrollmentStatus.ACTIVE.value)])
    return {r["student_uid"] for r in rows}


def _check_conflicts(*, own_id: str | None, offering_id: str, faculty_uid: str | None, room: str | None,
                     on: date, start: time, end: time) -> None:
    """Compare against SCHEDULED schedules on the same day (other examinations included).
    Overlap is strict: back-to-back slots (end == start) do not conflict."""
    same_day = _collect(EXAM_SCHEDULES, [("exam_date", on.isoformat()),
                                         ("status", ScheduleStatus.SCHEDULED.value)])
    exam_status: dict[str, str | None] = {}
    mine: set[str] | None = None
    for other in same_day:
        if other["id"] == own_id:
            continue
        if not (start < _t(other["end_time"]) and _t(other["start_time"]) < end):
            continue
        ex_id = other["examination_id"]
        if ex_id not in exam_status:
            row = common.fetch(EXAMINATIONS, ex_id)
            exam_status[ex_id] = row.get("status") if row else None
        if exam_status[ex_id] == ExaminationStatus.CANCELLED.value:
            continue
        if other["course_offering_id"] == offering_id:
            raise AcademicConflictError("This course offering already has an overlapping exam schedule.")
        if room and other.get("room") and other["room"].casefold() == room.casefold():
            raise AcademicConflictError("The room is already booked for an overlapping exam schedule.")
        if faculty_uid and other.get("faculty_uid") == faculty_uid:
            raise AcademicConflictError("The assigned faculty member has an overlapping exam schedule.")
        if mine is None:
            mine = _offering_students(offering_id)
        if mine and mine & _offering_students(other["course_offering_id"]):
            raise AcademicConflictError("Enrolled students have an overlapping exam schedule.")


def create_schedule(payload: ExamScheduleCreate, actor: Actor) -> ExamSchedule:
    exam = get_examination(payload.examination_id)  # 404
    row = common.fetch(OFFERINGS, payload.course_offering_id)
    if row is None:
        raise AcademicNotFoundError("Course offering not found.")
    course = get_course(row["course_id"])  # 404
    if exam.status.value in CLOSED_EXAMS:
        raise AcademicValidationError("Examination is not open for scheduling.")
    if row.get("status") == OfferingStatus.CANCELLED.value:
        raise AcademicValidationError("Course offering is cancelled.")
    if row["semester_id"] != exam.semester_id:
        raise AcademicValidationError("Course offering does not belong to the examination's semester.")
    derived = {
        "course_id": row["course_id"], "academic_session_id": row["academic_session_id"],
        "semester_id": row["semester_id"], "program_id": row["program_id"],
        "department_id": row["department_id"], "faculty_uid": row.get("faculty_uid"),
    }
    for key, expected in derived.items():
        supplied = getattr(payload, key)
        if supplied is not None and supplied != expected:
            raise AcademicValidationError(f"{key} does not match the course offering.")
    if exam.academic_session_id != row["academic_session_id"] or exam.program_id != row["program_id"]:
        raise AcademicValidationError("Course offering does not match the examination's session/program.")
    _require_in_range(exam, payload.exam_date)

    doc_id = schedule_id(exam.id, row["id"])
    _check_conflicts(own_id=doc_id, offering_id=row["id"], faculty_uid=derived["faculty_uid"],
                     room=payload.room, on=payload.exam_date, start=payload.start_time, end=payload.end_time)
    ts = common.now()
    data = {
        "exam_schedule_id": doc_id,
        "examination_id": exam.id,
        "course_offering_id": row["id"],
        **derived,
        "exam_date": payload.exam_date.isoformat(),
        "start_time": payload.start_time.isoformat(),
        "end_time": payload.end_time.isoformat(),
        "room": payload.room,
        "max_marks": payload.max_marks or course.max_marks,
        "instructions": payload.instructions,
        "status": ScheduleStatus.SCHEDULED.value,
        "created_at": ts,
        "updated_at": ts,
    }
    common.write(EXAM_SCHEDULES, doc_id, data, create=True,
                 conflict_message="This course offering is already scheduled for the examination.")
    common.audit(actor, "exam_schedule.create", "exam_schedule", doc_id, {"examination_id": exam.id})
    return ExamSchedule(id=doc_id, **data)


def update_schedule(schedule_id_: str, payload: ExamScheduleUpdate, actor: Actor) -> ExamSchedule:
    row = common.fetch(EXAM_SCHEDULES, schedule_id_)
    if row is None:
        raise AcademicNotFoundError("Exam schedule not found.")
    current = ExamSchedule(**row)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    for key in ("exam_date", "start_time", "end_time", "max_marks", "status"):
        if key in changes and changes[key] is None:
            raise AcademicValidationError(f"{key} cannot be null.")
    on = _d(changes.get("exam_date", current.exam_date))
    start = _t(changes.get("start_time", current.start_time))
    end = _t(changes.get("end_time", current.end_time))
    if end <= start:
        raise UnprocessableAcademicError("end_time must be after start_time.")
    room = changes["room"] if "room" in changes else current.room
    new_status = changes.get("status", current.status.value)
    if new_status == ScheduleStatus.SCHEDULED.value and any(
            k in changes for k in ("exam_date", "start_time", "end_time", "room", "status")):
        exam = get_examination(current.examination_id)
        _require_in_range(exam, on)
        _check_conflicts(own_id=schedule_id_, offering_id=current.course_offering_id,
                         faculty_uid=current.faculty_uid, room=room, on=on, start=start, end=end)
    return _apply(EXAM_SCHEDULES, schedule_id_, current, changes, ExamSchedule, actor, "exam_schedule")


def _enrich(rows: list[dict[str, Any]]) -> list[ExamScheduleView]:
    exams: dict[str, Any] = {}
    courses: dict[str, Any] = {}
    offerings: dict[str, Any] = {}
    out = []
    for r in rows:
        ex = exams.setdefault(r["examination_id"], common.fetch(EXAMINATIONS, r["examination_id"]))
        if r["course_id"] not in courses:
            try:
                courses[r["course_id"]] = get_course(r["course_id"])
            except AcademicNotFoundError:
                courses[r["course_id"]] = None
        off = offerings.setdefault(r["course_offering_id"], common.fetch(OFFERINGS, r["course_offering_id"]))
        course = courses[r["course_id"]]
        out.append(ExamScheduleView(
            **r,
            examination_name=ex.get("name") if ex else None,
            examination_type=ex.get("examination_type") if ex else None,
            examination_status=ex.get("status") if ex else None,
            course_code=course.code if course else None,
            course_name=course.name if course else None,
            section=off.get("section") if off else None,
        ))
    return out


def _can_see_schedule(viewer: Viewer, row: dict[str, Any]) -> bool:
    if _admin(viewer.role):
        return True
    ex = common.fetch(EXAMINATIONS, row["examination_id"])
    if ex is None or ex.get("status") == ExaminationStatus.DRAFT.value:
        return False
    if viewer.role == UserRole.FACULTY.value:
        off = common.fetch(OFFERINGS, row["course_offering_id"])
        return bool(off) and off.get("faculty_uid") == viewer.uid
    if viewer.role == UserRole.STUDENT.value:
        return row["course_offering_id"] in _student_offering_ids(viewer.uid)
    return False


def get_schedule(schedule_id_: str, viewer: Viewer) -> ExamScheduleView:
    row = common.fetch(EXAM_SCHEDULES, schedule_id_)
    if row is None or not _can_see_schedule(viewer, row):
        raise AcademicNotFoundError("Exam schedule not found.")
    return _enrich([row])[0]


def list_schedules(*, viewer: Viewer, limit: int, cursor: str | None, **f) -> Page[ExamScheduleView]:
    """Admin: any scope (Firestore-paginated). Faculty/student: scoped through their own
    offerings, derived from the verified identity; request filters can only narrow."""
    date_f = f.get("exam_date")
    status_f = f.get("status")
    filters: list[tuple] = [
        ("examination_id", f.get("examination_id")),
        ("course_offering_id", f.get("course_offering_id")),
        ("course_id", f.get("course_id")),
        ("academic_session_id", f.get("academic_session_id")),
        ("semester_id", f.get("semester_id")),
        ("program_id", f.get("program_id")),
        ("department_id", f.get("department_id")),
        ("faculty_uid", f.get("faculty_uid")),
        ("exam_date", date_f.isoformat() if date_f else None),
        ("status", status_f.value if status_f else None),
    ]
    if _admin(viewer.role):
        rows, nxt = common.list_docs(EXAM_SCHEDULES, filters, limit, cursor)
        return Page[ExamScheduleView](items=_enrich(rows), next_cursor=nxt)
    if viewer.role == UserRole.FACULTY.value:
        offering_ids = [o["id"] for o in _faculty_offerings(viewer.uid)]
    elif viewer.role == UserRole.STUDENT.value:
        offering_ids = _student_offering_ids(viewer.uid)
    else:
        offering_ids = []
    if f.get("course_offering_id"):
        offering_ids = [o for o in offering_ids if o == f["course_offering_id"]]
    rows = []
    for chunk in _chunks(offering_ids):
        rows += _collect(EXAM_SCHEDULES, [x for x in filters if x[0] != "course_offering_id"]
                         + [("course_offering_id", chunk, "in")])
    visible: dict[str, bool] = {}
    kept = []
    for r in rows:  # hide schedules of DRAFT / missing examinations
        ex_id = r["examination_id"]
        if ex_id not in visible:
            ex = common.fetch(EXAMINATIONS, ex_id)
            visible[ex_id] = bool(ex) and ex.get("status") != ExaminationStatus.DRAFT.value
        if visible[ex_id]:
            kept.append(r)
    kept.sort(key=lambda r: (str(r["exam_date"]), str(r["start_time"]), r["id"]))
    start = 0
    if cursor:
        start = next((i + 1 for i, r in enumerate(kept) if r["id"] == cursor), 0)
    limit = max(1, min(limit, common.MAX_PAGE_SIZE))
    page = kept[start:start + limit]
    nxt = page[-1]["id"] if start + limit < len(kept) and page else None
    return Page[ExamScheduleView](items=_enrich(page), next_cursor=nxt)

