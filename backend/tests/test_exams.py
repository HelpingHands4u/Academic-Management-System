import pytest

from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401

OFF = "cs101__btcs__2030-31__1__a"
OFF2 = "cs102__btcs__2030-31__1__a"
EX = f"{SEM}__end_semester__end-sem"
SCH = f"{EX}__{OFF}"
SCH2 = f"{EX}__{OFF2}"


def mk_exam(client, **kw):
    body = {"name": "End Sem", "examination_type": "END_SEMESTER", "semester_id": SEM,
            "start_date": "2030-12-01", "end_date": "2030-12-10", "status": "SCHEDULED", **kw}
    return client.post("/api/v1/examinations", headers=AUTH, json=body)


def mk_sch(client, offering=OFF, **kw):
    body = {"examination_id": EX, "course_offering_id": offering, "exam_date": "2030-12-02",
            "start_time": "10:00:00", "end_time": "12:00:00", "room": "R1", **kw}
    return client.post("/api/v1/exam-schedules", headers=AUTH, json=body)


@pytest.fixture
def ex(client, enrol, accounts):
    """Exam + schedule-ready: cs101 (fac-1) and cs102 (fac-2); S-001 in both, S-002 only cs101."""
    accounts["add"]("fac-2", "FACULTY", faculty_id="F-2")
    mk_course(client, code="CS102")
    assert mk_off(client, course="cs102", section="a", faculty_uid="fac-2", status="ACTIVE").status_code == 201
    mk_enr(client, "S-001")
    mk_enr(client, "S-002")
    mk_enr(client, "S-001", OFF2)
    assert mk_exam(client).status_code == 201
    return enrol


# ---- examinations ---------------------------------------------------------
def test_admin_creates_examination(client, base, store):
    r = mk_exam(client, description="d")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == b["examination_id"] == EX
    assert (b["academic_session_id"], b["program_id"], b["department_id"], b["semester_id"], b["status"],
            b["created_by_uid"]) == ("2030-31", "btcs", "cse", SEM, "SCHEDULED", "admin-1")
    assert mk_exam(client).status_code == 409
    assert mk_exam(client, academic_session_id="2030-31", program_id="btcs", department_id="cse",
                   name="Other").status_code == 201


def test_examination_default_status_draft(client, base):
    body = {"name": "X", "examination_type": "INTERNAL", "semester_id": SEM,
            "start_date": "2030-12-01", "end_date": "2030-12-01"}
    r = client.post("/api/v1/examinations", headers=AUTH, json=body)
    assert r.status_code == 201 and r.json()["status"] == "DRAFT"


@pytest.mark.parametrize("role", ["FACULTY", "STUDENT"])
def test_non_admin_cannot_mutate(client, identity, base, role):
    assert mk_exam(client).status_code == 201
    as_role(identity, role)
    assert mk_exam(client, name="B").status_code == 403
    assert client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"status": "ONGOING"}).status_code == 403
    assert mk_sch(client).status_code == 403
    assert client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"room": "x"}).status_code == 403


def test_unauthenticated_401(client):
    for c in (client.get("/api/v1/examinations"), client.post("/api/v1/examinations", json={}),
              client.get("/api/v1/examinations/me"), client.get("/api/v1/examinations/faculty/me"),
              client.get("/api/v1/exam-schedules"), client.post("/api/v1/exam-schedules", json={}),
              client.patch("/api/v1/exam-schedules/x", json={})):
        assert c.status_code == 401


def test_examination_validation(client, base):
    assert mk_exam(client, examination_type="QUIZ").status_code == 422
    assert mk_exam(client, status="PENDING").status_code == 422
    assert mk_exam(client, start_date="2030-12-11").status_code == 422
    assert mk_exam(client, role="ADMIN").status_code == 422
    assert client.post("/api/v1/examinations", headers=AUTH, json={}).status_code == 422
    assert mk_exam(client, semester_id="ghost").status_code == 404
    assert mk_exam(client, academic_session_id="ghost").status_code == 404
    assert mk_exam(client, academic_session_id="2031-32").status_code == 400
    assert mk_exam(client, program_id="ghost").status_code == 404


def test_examination_list_filters_pagination_get(client, base):
    mk_exam(client)
    mk_exam(client, name="Mid", examination_type="MIDTERM", status="DRAFT")
    mk_exam(client, name="Prac", examination_type="PRACTICAL")
    r = client.get("/api/v1/examinations", headers=AUTH)
    assert len(r.json()["items"]) == 3
    p1 = client.get("/api/v1/examinations?limit=2", headers=AUTH).json()
    assert len(p1["items"]) == 2 and p1["next_cursor"]
    p2 = client.get(f"/api/v1/examinations?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert len(p2["items"]) == 1 and p2["next_cursor"] is None
    for q, n in (("examination_type=MIDTERM", 1), ("status=SCHEDULED", 2), ("semester_id=" + SEM, 3),
                 ("program_id=btcs", 3), ("department_id=cse", 3), ("academic_session_id=2030-31", 3),
                 ("academic_session_id=2031-32", 0)):
        assert len(client.get(f"/api/v1/examinations?{q}", headers=AUTH).json()["items"]) == n, q
    assert client.get(f"/api/v1/examinations/{EX}", headers=AUTH).status_code == 200
    assert client.get("/api/v1/examinations/none", headers=AUTH).status_code == 404


def test_examination_update(client, base):
    mk_exam(client)
    r = client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"status": "ONGOING", "description": "x"})
    assert r.status_code == 200 and r.json()["status"] == "ONGOING"
    assert client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"start_date": "2030-12-20"}).status_code == 422
    assert client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"examination_type": "MIDTERM"}).status_code == 422
    assert client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"name": "New"}).status_code == 400
    assert client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"status": None}).status_code == 400
    assert client.patch("/api/v1/examinations/none", headers=AUTH, json={"status": "DRAFT"}).status_code == 404


# ---- schedules ------------------------------------------------------------
def test_admin_creates_schedule(client, ex, store):
    r = mk_sch(client, course_id="cs101", semester_id=SEM, faculty_uid="fac-1")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == b["exam_schedule_id"] == SCH
    assert (b["course_id"], b["semester_id"], b["academic_session_id"], b["program_id"], b["department_id"],
            b["faculty_uid"], b["max_marks"], b["status"], b["start_time"], b["room"]) == (
        "cs101", SEM, "2030-31", "btcs", "cse", "fac-1", 100, "SCHEDULED", "10:00:00", "R1")
    assert mk_sch(client, room="R9", exam_date="2030-12-05").status_code == 409  # same offering+exam
    assert any(a.get("action") == "exam_schedule.create" for a in store.audit)


def test_schedule_validation(client, ex):
    assert mk_sch(client, examination_id="ghost").status_code == 404
    assert mk_sch(client, offering="ghost").status_code == 404
    assert mk_sch(client, course_id="cs102").status_code == 400
    assert mk_sch(client, semester_id="other").status_code == 400
    assert mk_sch(client, academic_session_id="2031-32").status_code == 400
    assert mk_sch(client, faculty_uid="fac-2").status_code == 400
    assert mk_sch(client, max_marks=0).status_code == 422
    assert mk_sch(client, start_time="12:00:00", end_time="10:00:00").status_code == 422
    assert mk_sch(client, start_time="10:00:00", end_time="10:00:00").status_code == 422
    assert mk_sch(client, exam_date="2030-12-11").status_code == 422
    assert mk_sch(client, exam_date="2030-11-30").status_code == 422
    assert mk_sch(client, exam_date="nope").status_code == 422
    assert mk_sch(client, max_marks=50).json()["max_marks"] == 50


def test_schedule_semester_mismatch(client, ex):
    mk_sem(client, number=2, session="2031-32")
    mk_course(client, code="CS201", **{"semester_number": 2})
    assert mk_off(client, course="cs201", sem="btcs__2031-32__2", section="a").status_code == 201
    assert mk_sch(client, offering="cs201__btcs__2031-32__2__a").status_code == 400


def test_schedule_closed_examination(client, ex):
    client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"status": "COMPLETED"})
    assert mk_sch(client).status_code == 400


def test_schedule_get_list_filters_pagination(client, ex):
    mk_sch(client)
    r2 = mk_sch(client, offering=OFF2, room="R2", exam_date="2030-12-03")
    assert r2.status_code == 201, r2.text
    assert client.get(f"/api/v1/exam-schedules/{SCH}", headers=AUTH).json()["course_code"] == "CS101"
    assert client.get("/api/v1/exam-schedules/none", headers=AUTH).status_code == 404
    assert len(client.get("/api/v1/exam-schedules", headers=AUTH).json()["items"]) == 2
    p1 = client.get("/api/v1/exam-schedules?limit=1", headers=AUTH).json()
    p2 = client.get(f"/api/v1/exam-schedules?limit=1&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert p1["items"][0]["id"] != p2["items"][0]["id"] and p2["next_cursor"] is None
    for q, n in (("course_offering_id=" + OFF, 1), ("course_id=cs102", 1), ("exam_date=2030-12-03", 1),
                 ("faculty_uid=fac-2", 1), ("examination_id=" + EX, 2), ("semester_id=" + SEM, 2),
                 ("status=CANCELLED", 0), ("program_id=btcs", 2), ("department_id=cse", 2)):
        assert len(client.get(f"/api/v1/exam-schedules?{q}", headers=AUTH).json()["items"]) == n, q


def test_schedule_update(client, ex):
    mk_sch(client)
    r = client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"room": "R5", "max_marks": 60})
    assert r.status_code == 200 and r.json()["room"] == "R5" and r.json()["max_marks"] == 60
    assert client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"course_offering_id": OFF2}).status_code == 422
    assert client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"start_time": "13:00:00"}).status_code == 422
    assert client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"exam_date": "2031-01-01"}).status_code == 422
    r = client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"status": "CANCELLED"})
    assert r.json()["status"] == "CANCELLED"
    assert client.patch("/api/v1/exam-schedules/none", headers=AUTH, json={"room": "x"}).status_code == 404


def test_examination_range_cannot_exclude_schedules(client, ex):
    mk_sch(client)
    assert client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"start_date": "2030-12-05"}).status_code == 409


# ---- conflicts ------------------------------------------------------------
def test_room_conflict(client, ex):
    mk_sch(client, room="R1")
    assert mk_sch(client, offering=OFF2, room="r1", start_time="11:00:00", end_time="13:00:00").status_code == 409
    # back-to-back and different room are fine
    assert mk_sch(client, offering=OFF2, room="R1", start_time="12:00:00", end_time="13:00:00").status_code == 201


def test_faculty_conflict(client, ex, accounts):
    client.patch(f"/api/v1/course-offerings/{OFF2}", headers=AUTH, json={"faculty_uid": "fac-1"})
    mk_sch(client, room="R1")
    r = mk_sch(client, offering=OFF2, room="R2", start_time="11:00:00", end_time="13:00:00")
    assert r.status_code == 409 and "faculty" in r.json()["detail"]


def test_student_conflict(client, ex):
    mk_sch(client, room="R1")
    r = mk_sch(client, offering=OFF2, room="R2", start_time="11:00:00", end_time="13:00:00")
    assert r.status_code == 409 and "students" in r.json()["detail"]
    assert mk_sch(client, offering=OFF2, room="R2", exam_date="2030-12-03").status_code == 201


def test_no_student_conflict_without_shared_students(client, ex):
    client.patch("/api/v1/enrollments/s-001__" + OFF2, headers=AUTH, json={"status": "DROPPED"})
    mk_sch(client, room="R1")
    assert mk_sch(client, offering=OFF2, room="R2", start_time="11:00:00", end_time="13:00:00").status_code == 201


def test_cancelled_schedule_frees_slot_and_update_conflict(client, ex):
    mk_sch(client, room="R1")
    mk_sch(client, offering=OFF2, room="R2", exam_date="2030-12-03")
    r = client.patch(f"/api/v1/exam-schedules/{SCH2}", headers=AUTH, json={"exam_date": "2030-12-02"})
    assert r.status_code == 409
    client.patch(f"/api/v1/exam-schedules/{SCH}", headers=AUTH, json={"status": "CANCELLED"})
    assert client.patch(f"/api/v1/exam-schedules/{SCH2}", headers=AUTH, json={"exam_date": "2030-12-02"}).status_code == 200


# ---- role access ----------------------------------------------------------
def test_faculty_access(client, identity, ex):
    mk_sch(client)
    mk_sch(client, offering=OFF2, room="R2", exam_date="2030-12-03")
    login(identity, "fac-1", "FACULTY")
    mine = client.get("/api/v1/examinations/faculty/me", headers=AUTH).json()["items"]
    assert [i["id"] for i in mine] == [SCH] and mine[0]["course_name"] == "Intro" and mine[0]["examination_name"] == "End Sem"
    assert [i["id"] for i in client.get("/api/v1/exam-schedules", headers=AUTH).json()["items"]] == [SCH]
    assert client.get(f"/api/v1/exam-schedules/{SCH}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/exam-schedules/{SCH2}", headers=AUTH).status_code == 404
    assert client.get(f"/api/v1/exam-schedules?course_offering_id={OFF2}", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/examinations/{EX}", headers=AUTH).status_code == 200
    assert client.get("/api/v1/examinations/me", headers=AUTH).status_code == 403
    login(identity, "fac-9", "FACULTY")
    assert client.get("/api/v1/examinations/faculty/me", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/examinations/{EX}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/examinations", headers=AUTH).json()["items"] == []


def test_student_access(client, identity, ex):
    mk_sch(client)
    mk_sch(client, offering=OFF2, room="R2", exam_date="2030-12-03")
    ctx = dict(program_id="btcs", semester_id=SEM)
    login(identity, "stu-2", "STUDENT", **ctx)  # enrolled only in cs101
    mine = client.get("/api/v1/examinations/me", headers=AUTH).json()["items"]
    assert [i["id"] for i in mine] == [SCH]
    assert (mine[0]["course_code"], mine[0]["room"], mine[0]["start_time"], mine[0]["exam_date"],
            mine[0]["course_offering_id"], mine[0]["status"]) == ("CS101", "R1", "10:00:00", "2030-12-02", OFF, "SCHEDULED")
    assert client.get(f"/api/v1/exam-schedules/{SCH}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/exam-schedules/{SCH2}", headers=AUTH).status_code == 404
    assert [i["id"] for i in client.get("/api/v1/exam-schedules", headers=AUTH).json()["items"]] == [SCH]
    assert client.get("/api/v1/examinations/faculty/me", headers=AUTH).status_code == 403
    assert client.get(f"/api/v1/examinations/{EX}", headers=AUTH).status_code == 200
    assert len(client.get("/api/v1/examinations", headers=AUTH).json()["items"]) == 1
    login(identity, "stu-1", "STUDENT", **ctx)
    assert len(client.get("/api/v1/examinations/me", headers=AUTH).json()["items"]) == 2
    login(identity, "stu-3", "STUDENT", **ctx)  # no enrollments
    assert client.get("/api/v1/examinations/me", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/exam-schedules/{SCH}", headers=AUTH).status_code == 404
    login(identity, "stu-3", "STUDENT", program_id="btcs", semester_id="other")
    assert client.get(f"/api/v1/examinations/{EX}", headers=AUTH).status_code == 404


def test_draft_hidden_from_non_admin(client, identity, ex):
    client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"status": "DRAFT"})
    mk_sch(client)
    login(identity, "stu-1", "STUDENT", program_id="btcs", semester_id=SEM)
    assert client.get("/api/v1/examinations", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/examinations/{EX}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/examinations/me", headers=AUTH).json()["items"] == []
    login(identity, "fac-1", "FACULTY")
    assert client.get("/api/v1/examinations/faculty/me", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/exam-schedules/{SCH}", headers=AUTH).status_code == 404


def test_regression_endpoints(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/auth/me", headers=AUTH).status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/examinations", "/api/v1/examinations/me", "/api/v1/examinations/faculty/me",
              "/api/v1/examinations/{examination_id}", "/api/v1/exam-schedules",
              "/api/v1/exam-schedules/{exam_schedule_id}"):
        assert p in paths




