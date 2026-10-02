from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.core.errors import (
    AcademicConflictError,
    AcademicForbiddenError,
    AcademicNotFoundError,
    AcademicValidationError,
)
from app.schemas.academic import Page
from app.schemas.attendance import (
    AttendanceBulkCreate,
    AttendanceCreate,
    AttendanceRecord,
    AttendanceStatus,
    AttendanceSummaryItem,
    AttendanceSummaryResponse,
    AttendanceUpdate,
    BulkAttendanceResponse,
)
from app.schemas.courses import OfferingStatus
from app.schemas.people import EnrollmentStatus
from app.schemas.user import UserRole
from app.services import academic_common as common
from app.services.academic_common import Actor, Viewer
from app.services.course_offerings import OFFERINGS
from app.services.courses import get_course
from app.services.departments_programs import slug
from app.services.enrollments import ENROLLMENTS, enrollment_id
from app.services.semesters import SEMESTERS
from app.services.students import get_student

ATTENDANCE = "attendance"
IN_LIMIT = 30  # Firestore `in` operator limit
MAX_SUMMARY_SCAN = 20000
ATTENDED = (AttendanceStatus.PRESENT.value, AttendanceStatus.LATE.value)


def today() -> date:
    """Server date (UTC). Isolated so tests can pin it."""
    return datetime.now(timezone.utc).date()


def attendance_id(student_doc_id: str, offering_id: str, on: date) -> str:
    # One record per student + offering + date. To allow several sessions per day
    # later, add a session component here (the only place that defines the key).
    return f"{student_doc_id}__{offering_id}__{on.isoformat()}"


def _admin(role: str | None) -> bool:
    return role == UserRole.ADMIN.value


def _actor(viewer: Viewer) -> Actor:
    return Actor(viewer.uid, viewer.role)


def _require_can_mark(viewer: Viewer, offering: dict[str, Any]) -> None:
    """ADMIN, or the FACULTY member currently assigned to this offering."""
    if _admin(viewer.role):
        return
    if viewer.role == UserRole.FACULTY.value and offering.get("faculty_uid") == viewer.uid:
        return
    raise AcademicForbiddenError("You are not allowed to manage attendance for this course offering.")


def _load_offering_for_marking(viewer: Viewer, offering_id: str, on: date) -> dict[str, Any]:
    """Validate the offering, its course/semester/session consistency, authorization and date."""
    offering = common.fetch(OFFERINGS, offering_id)
    if offering is None:
        raise AcademicNotFoundError("Course offering not found.")
    _require_can_mark(viewer, offering)
    if offering.get("status") != OfferingStatus.ACTIVE.value:
        raise AcademicValidationError("Attendance can only be marked for ACTIVE course offerings.")
    course = get_course(offering["course_id"])  # 404 if the course vanished
    if course.id != offering["course_id"] or not course.is_active:
        raise AcademicValidationError("Course for this offering is not valid or not active.")
    semester = common.fetch(SEMESTERS, offering["semester_id"])
    if semester is None:
        raise AcademicNotFoundError("Semester for this offering not found.")
    if (semester.get("academic_session_id") != offering["academic_session_id"]
            or semester.get("program_id") != offering["program_id"]):
        raise AcademicValidationError("Course offering has inconsistent semester/session/program relationships.")
    if on > today() + timedelta(days=1):  # one day of slack for time zones ahead of UTC
        raise AcademicValidationError("Attendance cannot be marked for a future date.")
    start, end = date.fromisoformat(semester["start_date"]), date.fromisoformat(semester["end_date"])
    if not start <= on <= end:
        raise AcademicValidationError("Attendance date is outside the semester's date range.")
    return offering


def _load_enrolled_student(student_id: str, offering: dict[str, Any]):
    student_doc = slug(student_id)
    student = get_student(student_doc)  # 404
    if not student.is_active:
        raise AcademicValidationError(f"Student {student.student_id} is not active.")
    enrollment = common.fetch(ENROLLMENTS, enrollment_id(student_doc, offering["id"]))
    if enrollment is None or enrollment.get("status") != EnrollmentStatus.ACTIVE.value:
        raise AcademicValidationError(f"Student {student.student_id} has no active enrollment in this offering.")
    return student


def _build_record(student, offering: dict[str, Any], on: date, status: AttendanceStatus,
                  remarks: str | None, marker_uid: str, ts) -> tuple[str, dict[str, Any]]:
    doc_id = attendance_id(slug(student.student_id), offering["id"], on)
    return doc_id, {
        "attendance_id": doc_id,
        "student_uid": student.uid,
        "student_id": student.student_id,
        "course_offering_id": offering["id"],
        "course_id": offering["course_id"],
        "academic_session_id": offering["academic_session_id"],
        "semester_id": offering["semester_id"],
        "faculty_uid": offering.get("faculty_uid"),
        "attendance_date": on.isoformat(),
        "status": status.value,
        "remarks": remarks,
        "marked_by_uid": marker_uid,
        "created_at": ts,
        "updated_at": ts,
    }


_DUPLICATE = "Attendance is already recorded for this student, course offering and date."


def create_attendance(payload: AttendanceCreate, viewer: Viewer) -> AttendanceRecord:
    offering = _load_offering_for_marking(viewer, payload.course_offering_id, payload.attendance_date)
    student = _load_enrolled_student(payload.student_id, offering)
    doc_id, data = _build_record(student, offering, payload.attendance_date, payload.status,
                                 payload.remarks, viewer.uid, common.now())
    common.write(ATTENDANCE, doc_id, data, create=True, conflict_message=_DUPLICATE)  # atomic duplicate guard
    common.audit(_actor(viewer), "attendance.create", "attendance", doc_id, {"status": payload.status.value})
    return AttendanceRecord(id=doc_id, **data)


def create_bulk(payload: AttendanceBulkCreate, viewer: Viewer) -> BulkAttendanceResponse:
    """All-or-nothing: every entry is validated first, then written in one batch."""
    offering = _load_offering_for_marking(viewer, payload.course_offering_id, payload.attendance_date)
    ts = common.now()
    built: list[tuple[str, dict[str, Any]]] = []
    for entry in payload.entries:
        student = _load_enrolled_student(entry.student_id, offering)
        doc_id, data = _build_record(student, offering, payload.attendance_date, entry.status,
                                     entry.remarks, viewer.uid, ts)
        if common.fetch(ATTENDANCE, doc_id) is not None:
            raise AcademicConflictError(f"{_DUPLICATE} (student {student.student_id})")
        built.append((doc_id, data))
    common.commit_batch([("create", ATTENDANCE, i, d) for i, d in built], _DUPLICATE)
    common.audit(_actor(viewer), "attendance.bulk_create", "course_offering", offering["id"],
                 {"count": len(built), "date": payload.attendance_date.isoformat()})
    return BulkAttendanceResponse(created=len(built), items=[AttendanceRecord(id=i, **d) for i, d in built])


def _viewable(viewer: Viewer, row: dict[str, Any]) -> bool:
    if _admin(viewer.role):
        return True
    if viewer.role == UserRole.STUDENT.value:
        return row.get("student_uid") == viewer.uid
    if viewer.role == UserRole.FACULTY.value:
        offering = common.fetch(OFFERINGS, row.get("course_offering_id", ""))
        return offering is not None and offering.get("faculty_uid") == viewer.uid
    return False


def get_attendance(attendance_id_: str, viewer: Viewer | None = None) -> AttendanceRecord:
    row = common.fetch(ATTENDANCE, attendance_id_)
    if row is None or (viewer is not None and not _viewable(viewer, row)):
        raise AcademicNotFoundError("Attendance record not found.")
    return AttendanceRecord(**row)


def update_attendance(attendance_id_: str, payload: AttendanceUpdate, viewer: Viewer) -> AttendanceRecord:
    row = common.fetch(ATTENDANCE, attendance_id_)
    if row is None:
        raise AcademicNotFoundError("Attendance record not found.")
    offering = common.fetch(OFFERINGS, row["course_offering_id"])
    if offering is None:
        raise AcademicNotFoundError("Course offering not found.")
    _require_can_mark(viewer, offering)
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, mode="json")
    if changes.get("status", "") is None:
        raise AcademicValidationError("status cannot be null.")
    current = AttendanceRecord(**row)
    if not changes:
        return current
    changes["updated_at"] = common.now()
    common.write(ATTENDANCE, attendance_id_, changes, create=False)
    common.audit(_actor(viewer), "attendance.update", "attendance", attendance_id_,
                 {"fields": sorted(k for k in changes if k != "updated_at")})
    return AttendanceRecord(**{**current.model_dump(), **changes})


def _scoped_filters(
    viewer: Viewer, *, student_id, student_uid, course_offering_id, course_id, semester_id,
    academic_session_id, faculty_uid, attendance_date, status,
) -> list[tuple] | None:
    """Role-scoped filters; None means the caller can see nothing. Scope is derived from the
    verified identity, so request filters can only narrow, never widen, what is visible."""
    filters: list[tuple] = []
    if viewer.role == UserRole.STUDENT.value:
        student_uid = viewer.uid
    elif viewer.role == UserRole.FACULTY.value:
        if course_offering_id:
            offering = common.fetch(OFFERINGS, course_offering_id)
            if offering is None or offering.get("faculty_uid") != viewer.uid:
                return None
        else:
            owned, _ = common.list_docs(OFFERINGS, [("faculty_uid", viewer.uid)], IN_LIMIT + 1, None)
            if not owned:
                return None
            if len(owned) > IN_LIMIT:
                raise AcademicValidationError("Too many assigned offerings; filter by course_offering_id.")
            filters.append(("course_offering_id", [o["id"] for o in owned], "in"))
        faculty_uid = None  # scope already enforced through offering ownership
    elif not _admin(viewer.role):
        return None
    filters += [
        ("student_id", student_id.upper() if student_id else None),
        ("student_uid", student_uid),
        ("course_offering_id", course_offering_id),
        ("course_id", course_id),
        ("semester_id", semester_id),
        ("academic_session_id", academic_session_id),
        ("faculty_uid", faculty_uid),
        ("attendance_date", attendance_date.isoformat() if attendance_date else None),
        ("status", status.value if status else None),
    ]
    return filters


def list_attendance(*, viewer: Viewer, limit: int, cursor: str | None, **filters) -> Page[AttendanceRecord]:
    scoped = _scoped_filters(viewer, **filters)
    if scoped is None:
        return Page[AttendanceRecord](items=[], next_cursor=None)
    rows, nxt = common.list_docs(ATTENDANCE, scoped, limit, cursor)
    return Page[AttendanceRecord](items=[AttendanceRecord(**r) for r in rows], next_cursor=nxt)


def percentage(attended: int, total: int) -> float:
    return round(attended / total * 100, 2) if total > 0 else 0.0


def summarize(rows: list[dict[str, Any]]) -> list[AttendanceSummaryItem]:
    """Aggregate records per (student, course offering). Percentages are always computed here."""
    groups: dict[tuple[str, str], tuple[dict[str, Any], dict[str, int]]] = {}
    for r in rows:
        key = (r["student_uid"], r["course_offering_id"])
        _, counts = groups.setdefault(key, (r, {s.value: 0 for s in AttendanceStatus}))
        if r.get("status") in counts:
            counts[r["status"]] += 1
    courses: dict[str, Any] = {}
    items = []
    for (uid, offering_id), (r, counts) in sorted(groups.items()):
        total = sum(counts.values())
        attended = sum(counts[s] for s in ATTENDED)
        course_id = r.get("course_id")
        if course_id not in courses:
            try:
                courses[course_id] = get_course(course_id)
            except AcademicNotFoundError:
                courses[course_id] = None
        course = courses[course_id]
        items.append(AttendanceSummaryItem(
            student_uid=uid, student_id=r.get("student_id"), course_id=course_id,
            course_code=course.code if course else None, course_name=course.name if course else None,
            course_offering_id=offering_id, total_classes=total,
            present_count=counts["PRESENT"], absent_count=counts["ABSENT"], late_count=counts["LATE"],
            excused_count=counts["EXCUSED"], attended_count=attended,
            attendance_percentage=percentage(attended, total),
        ))
    return items

def attendance_summary(*, viewer: Viewer, **filters) -> AttendanceSummaryResponse:
    scoped = _scoped_filters(viewer, **filters)
    if scoped is None:
        return AttendanceSummaryResponse(items=[])
    rows: list[dict[str, Any]] = []
    cursor = None
    while True:
        page, cursor = common.list_docs(ATTENDANCE, scoped, common.MAX_PAGE_SIZE, cursor)
        rows.extend(page)
        if len(rows) > MAX_SUMMARY_SCAN:
            raise AcademicValidationError("Too many attendance records to summarize; narrow the filters.")
        if cursor is None:
            break
    return AttendanceSummaryResponse(items=summarize(rows))

