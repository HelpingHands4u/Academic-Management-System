from datetime import date

import pytest

from app.services import attendance as svc
from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401

OFF = "cs101__btcs__2030-31__1__a"
D1, D2, D3 = "2030-08-01", "2030-08-02", "2030-08-03"


@pytest.fixture(autouse=True)
def pin_today(monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: date(2030, 8, 10))


@pytest.fixture
def att(client, enrol):
    """Students S-001/S-002 actively enrolled in OFF (faculty fac-1); S-003 not enrolled."""
    mk_enr(client, "S-001")
    mk_enr(client, "S-002")
    return enrol


def mark(client, sid="S-001", on=D1, status="PRESENT", offering=OFF, **kw):
    return client.post("/api/v1/attendance", headers=AUTH,
                       json={"student_id": sid, "course_offering_id": offering, "attendance_date": on,
                             "status": status, **kw})


# ---- creation -------------------------------------------------------------
@pytest.mark.parametrize("status", ["PRESENT", "ABSENT", "LATE", "EXCUSED"])
def test_admin_creates_each_status(client, att, status):
    r = mark(client, status=status, remarks="note")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == f"s-001__{OFF}__{D1}" == b["attendance_id"]
    assert (b["status"], b["student_uid"], b["student_id"], b["course_id"], b["semester_id"],
            b["academic_session_id"], b["faculty_uid"], b["marked_by_uid"], b["remarks"]) == (
        status, "stu-1", "S-001", "cs101", SEM, "2030-31", "fac-1", "admin-1", "note")
    assert b["created_at"] and b["updated_at"] and b["attendance_date"] == D1


def test_assigned_faculty_creates(client, identity, att):
    login(identity, "fac-1", "FACULTY")
    r = mark(client, status="LATE")
    assert r.status_code == 201 and r.json()["marked_by_uid"] == "fac-1"


def test_wrong_faculty_cannot_mark(client, identity, att, store):
    login(identity, "fac-2", "FACULTY")
    assert mark(client).status_code == 403
    assert client.post("/api/v1/attendance/bulk", headers=AUTH, json={
        "course_offering_id": OFF, "attendance_date": D1,
        "entries": [{"student_id": "S-001", "status": "PRESENT"}]}).status_code == 403
    assert not [k for k in store.docs if k[0] == "attendance"]


def test_student_cannot_create_or_update(client, identity, att):
    rid = mark(client).json()["id"]
    login(identity, "stu-1", "STUDENT")
    assert mark(client, on=D2).status_code == 403
    assert client.patch(f"/api/v1/attendance/{rid}", headers=AUTH, json={"status": "ABSENT"}).status_code == 403
    assert client.post("/api/v1/attendance/bulk", headers=AUTH, json={}).status_code == 403


def test_unauthenticated_401(client):
    for call in (client.get("/api/v1/attendance"), client.post("/api/v1/attendance", json={}),
                 client.get("/api/v1/attendance/summary"), client.get("/api/v1/attendance/me/summary"),
                 client.post("/api/v1/attendance/bulk", json={}), client.patch("/api/v1/attendance/x", json={})):
        assert call.status_code == 401


def test_invalid_status_and_fields_422(client, att):
    assert mark(client, status="SICK").status_code == 422
    assert mark(client, on="not-a-date").status_code == 422
    assert mark(client, faculty_uid="evil").status_code == 422  # derived server-side
    assert mark(client, attendance_percentage=100).status_code == 422
    assert client.post("/api/v1/attendance", headers=AUTH, json={}).status_code == 422


def test_nonexistent_student_and_offering_404(client, att):
    assert mark(client, sid="NOPE").status_code == 404
    assert mark(client, offering="ghost").status_code == 404


def test_inactive_student_400(client, att):
    client.patch("/api/v1/students/s-001", headers=AUTH, json={"is_active": False})
    assert mark(client).status_code == 400


def test_invalid_enrollment_400(client, att):
    assert mark(client, sid="S-003").status_code == 404  # no student profile
    mk_student(client, "stu-3", "S-003")
    assert mark(client, sid="S-003").status_code == 400  # student exists, not enrolled
    eid = f"s-002__{OFF}"
    client.patch(f"/api/v1/enrollments/{eid}", headers=AUTH, json={"status": "DROPPED"})
    assert mark(client, sid="S-002").status_code == 400  # dropped enrollment


def test_offering_must_be_active(client, att):
    client.patch(f"/api/v1/course-offerings/{OFF}", headers=AUTH, json={"status": "COMPLETED"})
    assert mark(client).status_code == 400


def test_date_validation(client, att):
    assert mark(client, on="2030-09-01").status_code == 400  # future
    assert mark(client, on="2030-06-01").status_code == 400  # before semester starts


def test_duplicate_attendance_409(client, att):
    assert mark(client).status_code == 201
    assert mark(client, status="ABSENT").status_code == 409
    assert mark(client, on=D2).status_code == 201
    assert mark(client, sid="S-002").status_code == 201


# ---- update ---------------------------------------------------------------
def test_update_admin_and_assigned_faculty(client, identity, att):
    rid = mark(client).json()["id"]
    r = client.patch(f"/api/v1/attendance/{rid}", headers=AUTH, json={"status": "EXCUSED", "remarks": "doc"})
    assert r.status_code == 200 and r.json()["status"] == "EXCUSED" and r.json()["remarks"] == "doc"
    login(identity, "fac-1", "FACULTY")
    r = client.patch(f"/api/v1/attendance/{rid}", headers=AUTH, json={"status": "LATE"})
    assert r.status_code == 200 and r.json()["status"] == "LATE" and r.json()["marked_by_uid"] == "admin-1"


def test_update_unauthorized_and_immutable(client, identity, att):
    rid = mark(client).json()["id"]
    for bad in ({"student_id": "S-002"}, {"course_offering_id": "x"}, {"faculty_uid": "x"},
                {"attendance_date": D2}, {"marked_by_uid": "x"}, {"student_uid": "x"}):
        assert client.patch(f"/api/v1/attendance/{rid}", headers=AUTH, json=bad).status_code == 422
    assert client.patch(f"/api/v1/attendance/{rid}", headers=AUTH, json={"status": None}).status_code == 400
    assert client.patch("/api/v1/attendance/none", headers=AUTH, json={"status": "ABSENT"}).status_code == 404
    login(identity, "fac-2", "FACULTY")
    assert client.patch(f"/api/v1/attendance/{rid}", headers=AUTH, json={"status": "ABSENT"}).status_code == 403


# ---- read / list ----------------------------------------------------------
def test_get_single_authorization(client, identity, att):
    mine = mark(client, "S-001").json()["id"]
    other = mark(client, "S-002").json()["id"]
    assert client.get(f"/api/v1/attendance/{mine}", headers=AUTH).status_code == 200
    assert client.get("/api/v1/attendance/none", headers=AUTH).status_code == 404
    login(identity, "stu-1", "STUDENT")
    assert client.get(f"/api/v1/attendance/{mine}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/attendance/{other}", headers=AUTH).status_code == 404
    login(identity, "fac-1", "FACULTY")
    assert client.get(f"/api/v1/attendance/{other}", headers=AUTH).status_code == 200
    login(identity, "fac-2", "FACULTY")
    assert client.get(f"/api/v1/attendance/{mine}", headers=AUTH).status_code == 404


def test_list_filters_and_pagination(client, att):
    mark(client, "S-001", D1, "PRESENT")
    mark(client, "S-001", D2, "ABSENT")
    mark(client, "S-002", D1, "LATE")
    ids = lambda q: sorted(a["id"] for a in client.get(f"/api/v1/attendance{q}", headers=AUTH).json()["items"])
    assert len(ids("")) == 3
    assert len(ids("?student_id=S-001")) == 2
    assert len(ids("?student_uid=stu-2")) == 1
    assert len(ids(f"?course_offering_id={OFF}")) == 3
    assert len(ids("?course_id=cs101")) == 3
    assert len(ids(f"?semester_id={SEM}&academic_session_id=2030-31")) == 3
    assert len(ids("?faculty_uid=fac-1")) == 3 and ids("?faculty_uid=nobody") == []
    assert len(ids(f"?attendance_date={D1}")) == 2
    assert len(ids("?status=ABSENT")) == 1
    assert client.get("/api/v1/attendance?status=BAD", headers=AUTH).status_code == 422
    p1 = client.get("/api/v1/attendance?limit=2", headers=AUTH).json()
    assert len(p1["items"]) == 2 and p1["next_cursor"]
    p2 = client.get(f"/api/v1/attendance?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert len(p2["items"]) == 1 and p2["next_cursor"] is None


def test_student_lists_only_own(client, identity, att):
    mark(client, "S-001")
    mark(client, "S-002")
    login(identity, "stu-1", "STUDENT")
    items = client.get("/api/v1/attendance", headers=AUTH).json()["items"]
    assert [a["student_id"] for a in items] == ["S-001"]
    assert client.get("/api/v1/attendance?student_uid=stu-2&student_id=S-002", headers=AUTH).json()["items"] == []


def test_faculty_lists_only_assigned(client, identity, att, accounts):
    accounts["add"]("fac-2", "FACULTY")
    mk_course(client, "CS102")
    mk_off(client, course="cs102", section="a", faculty_uid="fac-2", status="ACTIVE")
    mark(client, "S-001")
    mk_enr(client, "S-001", "cs102__btcs__2030-31__1__a")
    mark(client, "S-001", offering="cs102__btcs__2030-31__1__a")
    login(identity, "fac-1", "FACULTY")
    items = client.get("/api/v1/attendance", headers=AUTH).json()["items"]
    assert [a["course_offering_id"] for a in items] == [OFF]
    assert client.get("/api/v1/attendance?course_offering_id=cs102__btcs__2030-31__1__a",
                      headers=AUTH).json()["items"] == []
    login(identity, "fac-9", "FACULTY")
    assert client.get("/api/v1/attendance", headers=AUTH).json()["items"] == []


# ---- summaries ------------------------------------------------------------
def seed_week(client):
    for on, st in ((D1, "PRESENT"), (D2, "LATE"), (D3, "ABSENT"), ("2030-08-04", "EXCUSED")):
        assert mark(client, "S-001", on, st).status_code == 201
    mark(client, "S-002", D1, "ABSENT")


def test_percentage_function():
    assert svc.percentage(0, 0) == 0.0
    assert svc.percentage(3, 4) == 75.0
    assert svc.percentage(1, 3) == 33.33
    assert svc.summarize([]) == []


def test_student_summary(client, identity, att):
    seed_week(client)
    login(identity, "stu-1", "STUDENT")
    items = client.get("/api/v1/attendance/me/summary", headers=AUTH).json()["items"]
    assert len(items) == 1
    s = items[0]
    assert (s["course_id"], s["course_code"], s["course_name"], s["course_offering_id"]) == (
        "cs101", "CS101", "Intro", OFF)
    assert (s["total_classes"], s["present_count"], s["absent_count"], s["late_count"], s["excused_count"],
            s["attended_count"], s["attendance_percentage"]) == (4, 1, 1, 1, 1, 2, 50.0)
    # another student's data never appears, even when asking for it
    r = client.get("/api/v1/attendance/me/summary?course_id=cs101", headers=AUTH).json()["items"]
    assert [i["student_uid"] for i in r] == ["stu-1"]


def test_student_with_no_records_gets_empty_summary(client, identity, att):
    login(identity, "stu-2", "STUDENT")
    assert client.get("/api/v1/attendance/me/summary", headers=AUTH).json() == {"items": []}


def test_student_cannot_use_general_summary_or_other_summary(client, identity, att):
    seed_week(client)
    login(identity, "stu-1", "STUDENT")
    assert client.get("/api/v1/attendance/summary", headers=AUTH).status_code == 403
    login(identity, "fac-1", "FACULTY")
    assert client.get("/api/v1/attendance/me/summary", headers=AUTH).status_code == 403


def test_admin_summary(client, att):
    seed_week(client)
    items = client.get("/api/v1/attendance/summary", headers=AUTH).json()["items"]
    by = {i["student_id"]: i for i in items}
    assert by["S-001"]["attendance_percentage"] == 50.0 and by["S-001"]["total_classes"] == 4
    assert by["S-002"]["attendance_percentage"] == 0.0 and by["S-002"]["absent_count"] == 1
    one = client.get("/api/v1/attendance/summary?student_id=S-002", headers=AUTH).json()["items"]
    assert [i["student_id"] for i in one] == ["S-002"]
    q = f"?course_offering_id={OFF}&course_id=cs101&semester_id={SEM}&academic_session_id=2030-31&faculty_uid=fac-1"
    assert len(client.get(f"/api/v1/attendance/summary{q}", headers=AUTH).json()["items"]) == 2


def test_faculty_summary_scoped(client, identity, att, accounts):
    seed_week(client)
    accounts["add"]("fac-2", "FACULTY")
    mk_course(client, "CS102")
    mk_off(client, course="cs102", section="a", faculty_uid="fac-2", status="ACTIVE")
    mk_enr(client, "S-001", "cs102__btcs__2030-31__1__a")
    mark(client, "S-001", offering="cs102__btcs__2030-31__1__a")
    login(identity, "fac-1", "FACULTY")
    items = client.get("/api/v1/attendance/summary", headers=AUTH).json()["items"]
    assert {i["course_offering_id"] for i in items} == {OFF}
    assert client.get("/api/v1/attendance/summary?course_offering_id=cs102__btcs__2030-31__1__a",
                      headers=AUTH).json()["items"] == []


def test_zero_class_summary_item_percentage():
    # a summary group can never have zero classes via the API, so check the guard directly
    assert svc.percentage(0, 0) == 0.0 and svc.percentage(5, 0) == 0.0


# ---- bulk -----------------------------------------------------------------
def bulk(client, entries, on=D1, offering=OFF):
    return client.post("/api/v1/attendance/bulk", headers=AUTH,
                       json={"course_offering_id": offering, "attendance_date": on, "entries": entries})


def test_bulk_success(client, identity, att, store):
    r = bulk(client, [{"student_id": "S-001", "status": "PRESENT"},
                      {"student_id": "S-002", "status": "ABSENT", "remarks": "ill"}])
    assert r.status_code == 201, r.text
    assert r.json()["created"] == 2 and {i["student_id"] for i in r.json()["items"]} == {"S-001", "S-002"}
    assert len(client.get("/api/v1/attendance", headers=AUTH).json()["items"]) == 2
    login(identity, "fac-1", "FACULTY")
    assert bulk(client, [{"student_id": "S-001", "status": "LATE"}], on=D2).status_code == 201


def test_bulk_validation_is_all_or_nothing(client, att, store):
    count = lambda: len([k for k in store.docs if k[0] == "attendance"])
    assert bulk(client, [{"student_id": "S-001", "status": "PRESENT"},
                         {"student_id": "NOPE", "status": "PRESENT"}]).status_code == 404
    mk_student(client, "stu-3", "S-003")
    assert bulk(client, [{"student_id": "S-001", "status": "PRESENT"},
                         {"student_id": "S-003", "status": "PRESENT"}]).status_code == 400
    assert bulk(client, [{"student_id": "S-001", "status": "SICK"}]).status_code == 422
    assert bulk(client, []).status_code == 422
    assert bulk(client, [{"student_id": "S-001", "status": "PRESENT"},
                         {"student_id": "s-001", "status": "ABSENT"}]).status_code == 422  # repeated student
    assert count() == 0


def test_bulk_duplicate_409_creates_nothing(client, att, store):
    assert mark(client, "S-002").status_code == 201
    r = bulk(client, [{"student_id": "S-001", "status": "PRESENT"}, {"student_id": "S-002", "status": "PRESENT"}])
    assert r.status_code == 409
    assert len([k for k in store.docs if k[0] == "attendance"]) == 1


def test_swagger_attendance_endpoints(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p in ("/api/v1/attendance", "/api/v1/attendance/bulk", "/api/v1/attendance/summary",
              "/api/v1/attendance/me/summary", "/api/v1/attendance/{attendance_id}"):
        assert p in paths
    for name in ("AttendanceCreate", "AttendanceUpdate", "AttendanceRecord", "AttendanceSummaryResponse",
                 "AttendanceBulkCreate"):
        assert name in spec["components"]["schemas"]
    assert "422" in paths["/api/v1/attendance"]["post"]["responses"]

