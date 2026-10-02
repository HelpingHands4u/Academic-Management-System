import pytest

from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401

PAST = "2000-01-01T00:00:00Z"
FUTURE = "2999-01-01T00:00:00Z"
ECE_SEM = "btec__2030-31__1"


def mk_notice(client, **kw):
    body = {"title": "Holiday", "description": "Campus closed.", "audience": "ALL", **kw}
    return client.post("/api/v1/notices", headers=AUTH, json=body)


@pytest.fixture
def nt(client, enrol):
    """stu-1 (CSE/BTCS/sem1), stu-3 (ECE/BTEC/sem1), fac-1 (CSE, teaches BTCS sem1)."""
    assert mk_fac(client).status_code == 201
    mk_dept(client, "ECE", name="Electronics")
    mk_prog(client, dept="ece", code="BTEC")
    mk_sem(client, program="btec")
    assert mk_student(client, "stu-3", "S-003", department_id="ece", program_id="btec",
                      current_semester_id=ECE_SEM).status_code == 201
    return enrol


def feed(client, identity, uid, role="STUDENT", path="notices/me"):
    login(identity, uid, role)
    r = client.get(f"/api/v1/{path}", headers=AUTH)
    assert r.status_code == 200, r.text
    return {i["title"] for i in r.json()["items"]}


def test_admin_creates_notice(client, nt, store):
    r = mk_notice(client, priority="URGENT", attachment_url="https://example.com/a.pdf", metadata={"k": 1})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == b["notice_id"] and b["creator_uid"] == "admin-1" and b["creator_role"] == "ADMIN"
    assert (b["priority"], b["is_active"], b["is_published"], b["audience"]) == ("URGENT", True, True, "ALL")
    assert b["created_at"] and b["metadata"] == {"k": 1}


@pytest.mark.parametrize("role", ["FACULTY", "STUDENT"])
def test_non_admin_cannot_mutate(client, identity, nt, role):
    n = mk_notice(client).json()["id"]
    as_role(identity, role)
    assert mk_notice(client).status_code == 403
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"title": "x"}).status_code == 403


def test_notice_validation(client, nt):
    assert mk_notice(client, title="").status_code == 422
    assert mk_notice(client, title="   ").status_code == 422
    assert mk_notice(client, description="").status_code == 422
    assert mk_notice(client, audience="EVERYONE").status_code == 422
    assert mk_notice(client, priority="HIGH").status_code == 422
    assert mk_notice(client, publish_at="not-a-date").status_code == 422
    assert mk_notice(client, publish_at="2030-02-01T00:00:00Z", expiry_at="2030-01-01T00:00:00Z").status_code == 422
    assert mk_notice(client, attachment_url="javascript:alert(1)").status_code == 422
    assert mk_notice(client, creator_uid="x").status_code == 422
    assert mk_notice(client, creator_role="ADMIN").status_code == 422
    assert client.post("/api/v1/notices", headers=AUTH, json={}).status_code == 422
    assert mk_notice(client, publish_at="2030-01-01T00:00:00Z", expiry_at="2030-01-01T00:00:00Z").status_code == 201


def test_notice_targets_validated(client, nt):
    assert mk_notice(client, audience="DEPARTMENT").status_code == 400  # missing target
    assert mk_notice(client, audience="ALL", department_id="cse").status_code == 400
    assert mk_notice(client, audience="DEPARTMENT", department_id="ghost").status_code == 404
    assert mk_notice(client, audience="PROGRAM", program_id="ghost").status_code == 404
    assert mk_notice(client, audience="SEMESTER", semester_id="ghost").status_code == 404
    assert mk_notice(client, audience="ALL", academic_session_id="ghost").status_code == 404
    assert mk_notice(client, audience="PROGRAM", program_id="btcs", department_id="ece").status_code == 400
    assert mk_notice(client, audience="SEMESTER", semester_id=SEM, program_id="btec").status_code == 400
    assert mk_notice(client, audience="SEMESTER", semester_id=SEM, academic_session_id="2031-32").status_code == 400
    b = mk_notice(client, audience="SEMESTER", semester_id=SEM).json()  # chain derived from semester
    assert (b["program_id"], b["department_id"], b["academic_session_id"]) == ("btcs", "cse", "2030-31")
    assert mk_notice(client, audience="PROGRAM", program_id="btcs").json()["department_id"] == "cse"


def test_list_get_filters_pagination(client, nt):
    a = mk_notice(client, title="A").json()["id"]
    mk_notice(client, title="B", audience="STUDENTS", priority="IMPORTANT")
    mk_notice(client, title="C", audience="DEPARTMENT", department_id="cse")
    assert client.get(f"/api/v1/notices/{a}", headers=AUTH).json()["title"] == "A"
    assert client.get("/api/v1/notices/none", headers=AUTH).status_code == 404

    def titles(q):
        return {i["title"] for i in client.get(f"/api/v1/notices?{q}", headers=AUTH).json()["items"]}

    assert titles("") == {"A", "B", "C"}
    assert titles("audience=STUDENTS") == {"B"}
    assert titles("priority=IMPORTANT") == {"B"}
    assert titles("department_id=cse") == {"C"}
    assert titles("program_id=btcs") == set()
    assert titles("is_active=false") == set()
    p1 = client.get("/api/v1/notices?limit=2", headers=AUTH).json()
    p2 = client.get(f"/api/v1/notices?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None


def test_update_notice(client, nt, store):
    n = mk_notice(client).json()["id"]
    r = client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"title": "New", "priority": "URGENT"})
    assert r.status_code == 200 and r.json()["title"] == "New" and r.json()["priority"] == "URGENT"
    assert store.docs[("notices", n)]["priority"] == "URGENT"  # stored as plain value
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"title": None}).status_code == 400
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"creator_uid": "x"}).status_code == 422
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"department_id": "cse"}).status_code == 400
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"expiry_at": PAST}).status_code == 200
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"publish_at": FUTURE}).status_code == 400
    r = client.patch(f"/api/v1/notices/{n}", headers=AUTH,
                     json={"audience": "PROGRAM", "program_id": "btcs", "expiry_at": None, "publish_at": None})
    assert r.status_code == 200 and r.json()["department_id"] == "cse" and r.json()["audience"] == "PROGRAM"
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"audience": "ALL"}).json()["program_id"] is None
    assert client.patch("/api/v1/notices/none", headers=AUTH, json={"title": "x"}).status_code == 404


def test_activate_deactivate_publish_unpublish(client, identity, nt, store):
    n = mk_notice(client).json()["id"]
    assert "Holiday" in feed(client, identity, "stu-1")
    as_role(identity, "ADMIN")
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"is_active": False}).json()["is_active"] is False
    assert "Holiday" not in feed(client, identity, "stu-1")
    assert client.get(f"/api/v1/notices/{n}", headers=AUTH).status_code == 404
    as_role(identity, "ADMIN")
    assert client.get(f"/api/v1/notices/{n}", headers=AUTH).status_code == 200  # preserved for admin
    client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"is_active": True})
    assert "Holiday" in feed(client, identity, "stu-1")
    as_role(identity, "ADMIN")
    assert client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"is_published": False}).json()["is_published"] is False
    assert "Holiday" not in feed(client, identity, "stu-1")
    as_role(identity, "ADMIN")
    assert client.get("/api/v1/notices?is_published=false", headers=AUTH).json()["items"][0]["id"] == n
    client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"is_published": True})
    assert "Holiday" in feed(client, identity, "stu-1")
    assert ("notices", n) in store.docs


def test_unpublished_on_create_and_schedule_window(client, identity, nt):
    mk_notice(client, title="Draft", is_published=False)
    mk_notice(client, title="Later", publish_at=FUTURE)
    mk_notice(client, title="Expired", publish_at=PAST, expiry_at="2001-01-01T00:00:00Z")
    mk_notice(client, title="Live", publish_at=PAST, expiry_at=FUTURE)
    assert feed(client, identity, "stu-1") == {"Live"}
    assert feed(client, identity, "fac-1", "FACULTY", "notices/faculty/me") == {"Live"}
    as_role(identity, "ADMIN")
    assert len(client.get("/api/v1/notices", headers=AUTH).json()["items"]) == 4


def test_student_feed_audience(client, identity, nt):
    mk_notice(client, title="all")
    mk_notice(client, title="students", audience="STUDENTS")
    mk_notice(client, title="faculty", audience="FACULTY")
    mk_notice(client, title="cse", audience="DEPARTMENT", department_id="cse")
    mk_notice(client, title="ece", audience="DEPARTMENT", department_id="ece")
    mk_notice(client, title="btcs", audience="PROGRAM", program_id="btcs")
    mk_notice(client, title="btec", audience="PROGRAM", program_id="btec")
    mk_notice(client, title="sem-btcs", audience="SEMESTER", semester_id=SEM)
    mk_notice(client, title="sem-btec", audience="SEMESTER", semester_id=ECE_SEM)
    assert feed(client, identity, "stu-1") == {"all", "students", "cse", "btcs", "sem-btcs"}
    assert feed(client, identity, "stu-3") == {"all", "students", "ece", "btec", "sem-btec"}
    # a student with no profile only gets the global student-level notices
    assert feed(client, identity, "stu-2-ghost") == {"all", "students"}


def test_student_cannot_read_unrelated_notice(client, identity, nt):
    other = mk_notice(client, audience="PROGRAM", program_id="btec").json()["id"]
    mine = mk_notice(client, title="mine", audience="PROGRAM", program_id="btcs").json()["id"]
    login(identity, "stu-1", "STUDENT")
    assert client.get(f"/api/v1/notices/{other}", headers=AUTH).status_code == 404
    assert client.get(f"/api/v1/notices/{mine}", headers=AUTH).status_code == 200
    assert client.get("/api/v1/notices?program_id=btec", headers=AUTH).json()["items"] == []
    assert {i["title"] for i in client.get("/api/v1/notices", headers=AUTH).json()["items"]} == {"mine"}
    assert client.get("/api/v1/notices/faculty/me", headers=AUTH).status_code == 403
    assert client.get("/api/v1/notices?is_active=false", headers=AUTH).json()["items"] == []


def test_faculty_feed_audience(client, identity, nt):
    mk_notice(client, title="all")
    mk_notice(client, title="students", audience="STUDENTS")
    mk_notice(client, title="faculty", audience="FACULTY")
    mk_notice(client, title="cse", audience="DEPARTMENT", department_id="cse")
    mk_notice(client, title="ece", audience="DEPARTMENT", department_id="ece")
    mk_notice(client, title="btcs", audience="PROGRAM", program_id="btcs")
    mk_notice(client, title="btec", audience="PROGRAM", program_id="btec")
    mk_notice(client, title="sem-btcs", audience="SEMESTER", semester_id=SEM)
    mk_notice(client, title="sem-btec", audience="SEMESTER", semester_id=ECE_SEM)
    assert feed(client, identity, "fac-1", "FACULTY", "notices/faculty/me") == {
        "all", "faculty", "cse", "btcs", "sem-btcs"}
    assert feed(client, identity, "fac-9", "FACULTY", "notices/faculty/me") == {"all", "faculty"}
    assert client.get("/api/v1/notices/me", headers=AUTH).status_code == 403


def test_priority_filter_in_feed_and_pagination(client, identity, nt):
    for i in range(3):
        mk_notice(client, title=f"n{i}", priority="URGENT" if i else "NORMAL")
    login(identity, "stu-1", "STUDENT")
    assert len(client.get("/api/v1/notices/me?priority=URGENT", headers=AUTH).json()["items"]) == 2
    p1 = client.get("/api/v1/notices/me?limit=2", headers=AUTH).json()
    p2 = client.get(f"/api/v1/notices/me?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None


def test_notice_audit_events(client, nt, monkeypatch):
    events = []
    from app.services import academic_common
    monkeypatch.setattr(academic_common, "record_audit_event", lambda **kw: events.append(kw))
    n = mk_notice(client).json()["id"]
    client.patch(f"/api/v1/notices/{n}", headers=AUTH, json={"is_active": False, "is_published": False})
    actions = [e["action"] for e in events]
    assert actions == ["notice.create", "notice.update", "notice.deactivate", "notice.unpublish"]
    assert all(e["actor_uid"] == "admin-1" for e in events)
