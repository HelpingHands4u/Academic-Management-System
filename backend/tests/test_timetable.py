import pytest

from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401

OFF = "cs101__btcs__2030-31__1__a"
OFF2 = "cs102__btcs__2030-31__1__a"


def mk_tt(client, offering=OFF, **kw):
    body = {"course_offering_id": offering, "day_of_week": "MONDAY", "start_time": "10:00:00",
            "end_time": "11:00:00", "room": "R1", "class_type": "LECTURE", **kw}
    return client.post("/api/v1/timetable", headers=AUTH, json=body)


@pytest.fixture
def tt(client, enrol, accounts):
    """cs101 (fac-1) and cs102 (fac-2); S-001 in both, S-002 only in cs101."""
    accounts["add"]("fac-2", "FACULTY", faculty_id="F-2")
    mk_course(client, code="CS102")
    assert mk_off(client, course="cs102", section="a", faculty_uid="fac-2", status="ACTIVE").status_code == 201
    mk_enr(client, "S-001")
    mk_enr(client, "S-002")
    mk_enr(client, "S-001", OFF2)
    return enrol


def test_admin_creates_timetable_entry(client, tt, store):
    r = mk_tt(client)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == b["timetable_id"] and b["id"].startswith("tt_")
    assert (b["course_id"], b["academic_session_id"], b["semester_id"], b["program_id"], b["department_id"],
            b["section"], b["faculty_uid"], b["is_active"], b["created_by_uid"]) == (
        "cs101", "2030-31", SEM, "btcs", "cse", "A", "fac-1", True, "admin-1")
    assert b["start_time"] == "10:00:00" and b["day_of_week"] == "MONDAY"
    assert mk_tt(client, offering=OFF2, room="R2", course_id="cs102", section="a",
                 faculty_uid="fac-2", day_of_week="TUESDAY").status_code == 201


@pytest.mark.parametrize("role", ["FACULTY", "STUDENT"])
def test_non_admin_cannot_mutate(client, identity, tt, role):
    entry = mk_tt(client).json()["id"]
    as_role(identity, role)
    assert mk_tt(client, room="R9").status_code == 403
    assert client.patch(f"/api/v1/timetable/{entry}", headers=AUTH, json={"room": "x"}).status_code == 403


def test_unauthenticated_401(client):
    for c in (client.get("/api/v1/timetable"), client.post("/api/v1/timetable", json={}),
              client.get("/api/v1/timetable/me"), client.get("/api/v1/timetable/faculty/me"),
              client.get("/api/v1/timetable/x"), client.patch("/api/v1/timetable/x", json={}),
              client.get("/api/v1/notices"), client.post("/api/v1/notices", json={}),
              client.get("/api/v1/notices/me"), client.get("/api/v1/notices/faculty/me"),
              client.patch("/api/v1/notices/x", json={})):
        assert c.status_code == 401


def test_timetable_validation(client, tt):
    assert mk_tt(client, day_of_week="FUNDAY").status_code == 422
    assert mk_tt(client, class_type="PARTY").status_code == 422
    assert mk_tt(client, start_time="11:00:00", end_time="10:00:00").status_code == 422
    assert mk_tt(client, start_time="10:00:00", end_time="10:00:00").status_code == 422
    assert mk_tt(client, room="").status_code == 422
    assert mk_tt(client, role="ADMIN").status_code == 422
    assert mk_tt(client, section="a!").status_code == 422
    assert client.post("/api/v1/timetable", headers=AUTH, json={}).status_code == 422
    assert mk_tt(client, offering="ghost").status_code == 404


@pytest.mark.parametrize("field,value", [
    ("course_id", "cs102"), ("semester_id", "other"), ("academic_session_id", "2031-32"),
    ("program_id", "other"), ("department_id", "other"), ("faculty_uid", "fac-2"), ("section", "b")])
def test_mismatched_relationships_400(client, tt, field, value):
    assert mk_tt(client, **{field: value}).status_code == 400


def test_cancelled_offering_rejected(client, tt):
    client.patch(f"/api/v1/course-offerings/{OFF}", headers=AUTH, json={"status": "CANCELLED"})
    assert mk_tt(client).status_code == 400


def test_list_get_filters_pagination(client, tt):
    ids = [mk_tt(client).json()["id"],
           mk_tt(client, day_of_week="TUESDAY").json()["id"],
           mk_tt(client, offering=OFF2, room="R2", day_of_week="WEDNESDAY").json()["id"]]
    items = client.get("/api/v1/timetable", headers=AUTH).json()["items"]
    assert len(items) == 3 and {"CS101", "CS102"} == {i["course_code"] for i in items}
    assert any(i["course_code"] == "CS101" and i["course_name"] == "Intro" for i in items)
    assert client.get(f"/api/v1/timetable/{ids[0]}", headers=AUTH).json()["id"] == ids[0]
    assert client.get("/api/v1/timetable/none", headers=AUTH).status_code == 404

    def count(q):
        return len(client.get(f"/api/v1/timetable?{q}", headers=AUTH).json()["items"])

    assert count(f"course_offering_id={OFF2}") == 1
    assert count("course_id=cs101") == 2
    assert count("day_of_week=TUESDAY") == 1
    assert count("room=R2") == 1
    assert count("faculty_uid=fac-2") == 1
    assert count("section=a") == 3
    assert count(f"semester_id={SEM}&program_id=btcs&department_id=cse&academic_session_id=2030-31") == 3
    assert count("program_id=ghost") == 0
    p1 = client.get("/api/v1/timetable?limit=2", headers=AUTH).json()
    assert len(p1["items"]) == 2 and p1["next_cursor"]
    p2 = client.get(f"/api/v1/timetable?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert len(p2["items"]) == 1 and p2["next_cursor"] is None
    assert client.get("/api/v1/timetable?limit=0", headers=AUTH).status_code == 422


def test_update_and_deactivate(client, tt, store):
    e = mk_tt(client).json()["id"]
    r = client.patch(f"/api/v1/timetable/{e}", headers=AUTH, json={"room": "R5", "class_type": "LAB"})
    assert r.status_code == 200 and r.json()["room"] == "R5" and r.json()["class_type"] == "LAB"
    assert client.patch(f"/api/v1/timetable/{e}", headers=AUTH,
                        json={"start_time": "12:00:00"}).status_code == 422  # end 11:00 now precedes start
    for protected in ({"course_offering_id": OFF2}, {"faculty_uid": "x"}, {"section": "B"}, {"semester_id": "x"}):
        assert client.patch(f"/api/v1/timetable/{e}", headers=AUTH, json=protected).status_code == 422
    assert client.patch(f"/api/v1/timetable/{e}", headers=AUTH, json={"room": None}).status_code == 400
    assert client.patch("/api/v1/timetable/none", headers=AUTH, json={"room": "x"}).status_code == 404
    assert client.patch(f"/api/v1/timetable/{e}", headers=AUTH, json={"is_active": False}).json()["is_active"] is False
    assert [k for k in store.docs if k[0] == "timetable"]  # soft-deactivated, not deleted


# ---- conflicts ------------------------------------------------------------
def test_offering_conflict(client, tt):
    mk_tt(client)
    assert mk_tt(client, room="R2", start_time="10:30:00", end_time="11:30:00").status_code == 409
    assert mk_tt(client, room="R2", start_time="11:00:00", end_time="12:00:00").status_code == 201  # back-to-back
    assert mk_tt(client, room="R2", day_of_week="WEDNESDAY").status_code == 201


def test_room_conflict(client, tt):
    mk_tt(client, room="R1")
    r = mk_tt(client, offering=OFF2, room="r1", start_time="10:30:00", end_time="11:30:00")
    assert r.status_code == 409 and "room" in r.json()["detail"]
    assert mk_tt(client, offering=OFF2, room="R1", start_time="11:00:00", end_time="12:00:00").status_code == 201


def test_faculty_conflict(client, tt):
    client.patch(f"/api/v1/course-offerings/{OFF2}", headers=AUTH, json={"faculty_uid": "fac-1"})
    mk_tt(client)
    r = mk_tt(client, offering=OFF2, room="R2", start_time="10:30:00", end_time="11:30:00")
    assert r.status_code == 409 and "faculty" in r.json()["detail"]


def test_student_conflict(client, tt):
    mk_tt(client)
    r = mk_tt(client, offering=OFF2, room="R2", start_time="10:30:00", end_time="11:30:00")
    assert r.status_code == 409 and "students" in r.json()["detail"]
    assert mk_tt(client, offering=OFF2, room="R2", day_of_week="FRIDAY").status_code == 201


def test_no_student_conflict_without_shared_students(client, tt):
    client.patch("/api/v1/enrollments/s-001__" + OFF2, headers=AUTH, json={"status": "DROPPED"})
    mk_tt(client)
    assert mk_tt(client, offering=OFF2, room="R2", start_time="10:30:00", end_time="11:30:00").status_code == 201


def test_deactivated_entry_frees_slot_and_reactivation_conflicts(client, tt):
    a = mk_tt(client).json()["id"]
    b = mk_tt(client, offering=OFF2, room="R2", day_of_week="TUESDAY").json()["id"]
    assert client.patch(f"/api/v1/timetable/{b}", headers=AUTH, json={"day_of_week": "MONDAY"}).status_code == 409
    client.patch(f"/api/v1/timetable/{a}", headers=AUTH, json={"is_active": False})
    assert client.patch(f"/api/v1/timetable/{b}", headers=AUTH, json={"day_of_week": "MONDAY"}).status_code == 200
    assert client.patch(f"/api/v1/timetable/{a}", headers=AUTH, json={"is_active": True}).status_code == 409


# ---- role views -----------------------------------------------------------
def test_student_timetable(client, identity, tt):
    mk_tt(client, day_of_week="TUESDAY", start_time="09:00:00", end_time="10:00:00", room="R1")
    a = mk_tt(client, day_of_week="MONDAY", start_time="14:00:00", end_time="15:00:00", room="R3").json()["id"]
    c = mk_tt(client, offering=OFF2, day_of_week="MONDAY", start_time="09:00:00", end_time="10:00:00",
              room="R2").json()["id"]
    login(identity, "stu-2", "STUDENT")
    items = client.get("/api/v1/timetable/me", headers=AUTH).json()["items"]
    assert [i["day_of_week"] for i in items] == ["MONDAY", "TUESDAY"]  # S-002 is only in cs101
    assert client.get(f"/api/v1/timetable/{c}", headers=AUTH).status_code == 404  # unrelated offering
    assert client.get(f"/api/v1/timetable/{a}", headers=AUTH).status_code == 200
    assert [i["id"] for i in client.get("/api/v1/timetable", headers=AUTH).json()["items"]] == [a, items[1]["id"]]
    assert client.get(f"/api/v1/timetable?course_offering_id={OFF2}", headers=AUTH).json()["items"] == []
    assert client.get("/api/v1/timetable/faculty/me", headers=AUTH).status_code == 403
    login(identity, "stu-1", "STUDENT")
    mine = client.get("/api/v1/timetable/me", headers=AUTH).json()["items"]
    assert [(i["day_of_week"], i["start_time"]) for i in mine] == [
        ("MONDAY", "09:00:00"), ("MONDAY", "14:00:00"), ("TUESDAY", "09:00:00")]
    assert mine[0]["course_code"] == "CS102" and mine[0]["room"] == "R2" and mine[0]["section"] == "A"
    assert mine[0]["class_type"] == "LECTURE" and mine[0]["course_offering_id"] == OFF2
    login(identity, "stu-3", "STUDENT")  # not enrolled anywhere
    assert client.get("/api/v1/timetable/me", headers=AUTH).json()["items"] == []


def test_student_does_not_see_inactive_entries(client, identity, tt):
    e = mk_tt(client).json()["id"]
    client.patch(f"/api/v1/timetable/{e}", headers=AUTH, json={"is_active": False})
    login(identity, "stu-1", "STUDENT")
    assert client.get("/api/v1/timetable/me", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/timetable/{e}", headers=AUTH).status_code == 404


def test_student_pagination_sorted(client, identity, tt):
    for h in (9, 10, 11):
        mk_tt(client, start_time=f"{h:02d}:00:00", end_time=f"{h:02d}:50:00")
    login(identity, "stu-1", "STUDENT")
    p1 = client.get("/api/v1/timetable/me?limit=2", headers=AUTH).json()
    p2 = client.get(f"/api/v1/timetable/me?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    got = [i["start_time"] for i in p1["items"] + p2["items"]]
    assert got == ["09:00:00", "10:00:00", "11:00:00"] and p2["next_cursor"] is None


def test_faculty_timetable(client, identity, tt):
    assert mk_fac(client).status_code == 201
    a = mk_tt(client).json()["id"]
    b = mk_tt(client, offering=OFF2, room="R2", day_of_week="TUESDAY").json()["id"]
    login(identity, "fac-1", "FACULTY")
    items = client.get("/api/v1/timetable/faculty/me", headers=AUTH).json()["items"]
    assert [i["id"] for i in items] == [a] and items[0]["faculty_name"] == "Fac-1"
    assert client.get(f"/api/v1/timetable/{a}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/timetable/{b}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/timetable", headers=AUTH).json()["items"][0]["id"] == a
    assert client.get("/api/v1/timetable/me", headers=AUTH).status_code == 403
    login(identity, "fac-9", "FACULTY")
    assert client.get("/api/v1/timetable/faculty/me", headers=AUTH).json()["items"] == []


def test_inactive_user_blocked(client, identity, tt):
    from app.schemas.user import UserProfile, UserRole
    identity["claims"] = {"uid": "stu-1", "role": "STUDENT"}
    identity["profile"] = UserProfile(uid="stu-1", role=UserRole.STUDENT, is_active=False)
    assert client.get("/api/v1/timetable/me", headers=AUTH).status_code == 403
    assert client.get("/api/v1/notices/me", headers=AUTH).status_code == 403



def test_timetable_audit_events(client, tt, monkeypatch):
    events = []
    from app.services import academic_common
    monkeypatch.setattr(academic_common, "record_audit_event", lambda **kw: events.append(kw))
    e = mk_tt(client).json()["id"]
    client.patch(f"/api/v1/timetable/{e}", headers=AUTH, json={"room": "R7"})
    assert [x["action"] for x in events] == ["timetable.create", "timetable.update"]
    assert "password" not in str(events).lower() and "token" not in str(events).lower()

