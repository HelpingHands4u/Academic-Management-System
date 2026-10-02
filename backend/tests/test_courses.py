import pytest

from app.core.firebase import FirebaseNotConfiguredError  # noqa: F401
from app.schemas.user import UserProfile, UserRole
from app.services import course_offerings as offering_service
from test_academic import (  # noqa: F401  (fixtures re-exported)
    AUTH,
    as_role,
    client,
    identity,
    mk_dept,
    mk_prog,
    mk_session,
    mk_sem,
    store,
)


def mk_course(client, code="CS101", dept="cse", prog="btcs", **kw):
    body = {"code": code, "name": "Intro", "department_id": dept, "program_id": prog, "credits": 4,
            "course_type": "CORE", "semester_number": 1, "max_marks": 100, "passing_marks": 40, **kw}
    return client.post("/api/v1/courses", headers=AUTH, json=body)


def mk_off(client, course="cs101", sem="btcs__2030-31__1", section="a", **kw):
    return client.post("/api/v1/course-offerings", headers=AUTH,
                       json={"course_id": course, "semester_id": sem, "section": section, **kw})


@pytest.fixture
def base(client):
    mk_dept(client)
    mk_prog(client)
    mk_session(client)
    mk_session(client, "2031-32", "2031-07-01", "2032-06-30")
    mk_sem(client)  # btcs__2030-31__1


@pytest.fixture
def accounts(monkeypatch):
    """Fake Firebase Auth + profiles for faculty assignment."""
    state = {"auth": {}, "profiles": {}}
    monkeypatch.setattr(offering_service, "get_auth_account_status", lambda uid: state["auth"].get(uid))
    monkeypatch.setattr(offering_service, "get_user_profile", lambda uid: state["profiles"].get(uid))

    def add(uid, role, active=True, disabled=False, faculty_id=None):
        state["auth"][uid] = disabled
        state["profiles"][uid] = UserProfile(uid=uid, role=UserRole(role), is_active=active, faculty_id=faculty_id)

    state["add"] = add
    return state


# ---- courses --------------------------------------------------------------
def test_course_create_and_read(client, base):
    r = mk_course(client, code="cs101")
    assert r.status_code == 201
    b = r.json()
    assert b["id"] == "cs101" and b["code"] == "CS101" and b["credits"] == 4 and b["is_active"] is True
    assert client.get("/api/v1/courses/cs101", headers=AUTH).json()["name"] == "Intro"
    assert client.get("/api/v1/courses/none", headers=AUTH).status_code == 404


def test_course_duplicate_409(client, base):
    assert mk_course(client).status_code == 201
    assert mk_course(client, name="Other").status_code == 409


def test_course_invalid_department_and_program_404(client, base):
    assert mk_course(client, dept="ghost").status_code == 404
    assert mk_course(client, prog="ghost").status_code == 404


def test_course_program_department_mismatch(client, base):
    mk_dept(client, "ECE", name="Electronics")
    assert mk_course(client, dept="ece").status_code == 400


@pytest.mark.parametrize("patch", [{"credits": 0}, {"credits": -1}, {"semester_number": 0},
                                   {"max_marks": 0}, {"passing_marks": -1}, {"passing_marks": 101},
                                   {"course_type": "SEMINAR"}, {"code": ""}, {"name": ""}])
def test_course_invalid_values_422(client, base, patch):
    assert mk_course(client, **patch).status_code == 422


def test_course_semester_beyond_program_400(client, base):
    assert mk_course(client, semester_number=9).status_code == 400


def test_course_filtering_and_search(client, base):
    mk_course(client, "CS101")
    mk_course(client, "CS102", course_type="PRACTICAL", semester_number=2)
    mk_course(client, "MA201", course_type="ELECTIVE", semester_number=2)
    client.patch("/api/v1/courses/ma201", headers=AUTH, json={"is_active": False})
    ids = lambda q: sorted(c["id"] for c in client.get(f"/api/v1/courses{q}", headers=AUTH).json()["items"])
    assert ids("") == ["cs101", "cs102", "ma201"]
    assert ids("?program_id=btcs&department_id=cse") == ["cs101", "cs102", "ma201"]
    assert ids("?semester_number=2") == ["cs102", "ma201"]
    assert ids("?course_type=PRACTICAL") == ["cs102"]
    assert ids("?is_active=false") == ["ma201"]
    assert ids("?search=cs") == ["cs101", "cs102"]
    assert ids("?search=CS102") == ["cs102"]
    assert client.get("/api/v1/courses?search=a%20b", headers=AUTH).status_code == 422


def test_course_update(client, base):
    mk_course(client)
    r = client.patch("/api/v1/courses/cs101", headers=AUTH,
                     json={"name": "Renamed", "credits": 3.5, "max_marks": 50, "passing_marks": 20})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["credits"] == 3.5
    assert client.patch("/api/v1/courses/cs101", headers=AUTH, json={"passing_marks": 90}).status_code == 422
    assert client.patch("/api/v1/courses/cs101", headers=AUTH, json={"program_id": "x"}).status_code == 422
    assert client.patch("/api/v1/courses/cs101", headers=AUTH, json={"code": "NEW"}).status_code == 422
    assert client.patch("/api/v1/courses/zzz", headers=AUTH, json={"name": "x"}).status_code == 404


@pytest.mark.parametrize("role", ["STUDENT", "FACULTY"])
def test_course_mutation_forbidden_for_non_admin(client, identity, base, role):
    mk_course(client)
    as_role(identity, role)
    assert mk_course(client, "CS999").status_code == 403
    assert client.patch("/api/v1/courses/cs101", headers=AUTH, json={"name": "x"}).status_code == 403
    assert client.get("/api/v1/courses/cs101", headers=AUTH).status_code == 200


def test_course_unauthenticated_401(client):
    assert client.get("/api/v1/courses").status_code == 401
    assert client.post("/api/v1/courses", json={}).status_code == 401


def test_non_admin_sees_only_active_courses(client, identity, base):
    mk_course(client, "CS101")
    mk_course(client, "CS102")
    client.patch("/api/v1/courses/cs102", headers=AUTH, json={"is_active": False})
    as_role(identity, "STUDENT")
    items = client.get("/api/v1/courses?is_active=false", headers=AUTH).json()["items"]
    assert [c["id"] for c in items] == ["cs101"]
    assert client.get("/api/v1/courses/cs102", headers=AUTH).status_code == 404


# ---- offerings ------------------------------------------------------------
@pytest.fixture
def ready(client, base, accounts):
    mk_course(client)
    accounts["add"]("fac-1", "FACULTY", faculty_id="F-1")
    return accounts


def test_offering_create_and_read(client, ready):
    r = mk_off(client, academic_session_id="2030-31", program_id="btcs", department_id="cse",
               faculty_uid="fac-1", room="R1", capacity=60)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == "cs101__btcs__2030-31__1__a"
    assert (b["section"], b["status"], b["faculty_uid"], b["faculty_id"]) == ("A", "PLANNED", "fac-1", "F-1")
    assert b["program_id"] == "btcs" and b["department_id"] == "cse" and b["academic_session_id"] == "2030-31"
    assert client.get(f"/api/v1/course-offerings/{b['id']}", headers=AUTH).status_code == 200
    assert client.get("/api/v1/course-offerings/none", headers=AUTH).status_code == 404


def test_offering_without_faculty(client, ready):
    b = mk_off(client).json()
    assert b["faculty_uid"] is None


def test_offering_invalid_references_404(client, ready):
    assert mk_off(client, course="ghost").status_code == 404
    assert mk_off(client, sem="ghost").status_code == 404
    assert mk_off(client, academic_session_id="ghost").status_code == 404
    assert mk_off(client, program_id="ghost").status_code == 404
    assert mk_off(client, department_id="ghost").status_code == 404


def test_offering_semester_program_mismatch(client, ready):
    mk_prog(client, code="BTEE", name="Other")
    assert mk_off(client, program_id="btee").status_code == 400


def test_offering_semester_session_mismatch(client, ready):
    assert mk_off(client, academic_session_id="2031-32").status_code == 400


def test_offering_course_program_mismatch(client, ready):
    mk_dept(client, "ECE", name="Electronics")
    mk_prog(client, dept="ece", code="BTEC")
    mk_sem(client, program="btec")
    mk_course(client, "EC101", dept="ece", prog="btec")
    assert mk_off(client, course="ec101").status_code == 400  # course's program != semester's program
    assert mk_off(client, department_id="ece").status_code == 400


def test_offering_course_semester_number_mismatch(client, ready):
    mk_sem(client, number=2)
    assert mk_off(client, sem="btcs__2030-31__2").status_code == 400


def test_offering_rejects_non_faculty_roles(client, ready):
    ready["add"]("stu-1", "STUDENT")
    ready["add"]("adm-2", "ADMIN")
    assert mk_off(client, faculty_uid="stu-1").status_code == 400
    assert mk_off(client, faculty_uid="adm-2").status_code == 400
    assert mk_off(client, faculty_uid="nobody").status_code == 404


def test_offering_rejects_inactive_faculty(client, ready):
    ready["add"]("fac-off", "FACULTY", active=False)
    ready["add"]("fac-dis", "FACULTY", disabled=True)
    assert mk_off(client, faculty_uid="fac-off").status_code == 400
    assert mk_off(client, faculty_uid="fac-dis").status_code == 400


def test_offering_duplicate_409(client, ready):
    assert mk_off(client, section="a").status_code == 201
    assert mk_off(client, section="A").status_code == 409
    assert mk_off(client, section="b").status_code == 201


def test_offering_unknown_fields_and_bad_values_422(client, ready):
    assert mk_off(client, section="").status_code == 422
    assert mk_off(client, capacity=0).status_code == 422
    assert mk_off(client, status="DONE").status_code == 422
    assert mk_off(client, id="evil").status_code == 422


def test_offering_filtering(client, ready):
    mk_sem(client, number=2)
    mk_course(client, "CS102", semester_number=2)
    ready["add"]("fac-2", "FACULTY")
    mk_off(client, section="a", faculty_uid="fac-1")
    mk_off(client, section="b", faculty_uid="fac-2")
    mk_off(client, course="cs102", sem="btcs__2030-31__2", section="a", status="ACTIVE")
    ids = lambda q: sorted(o["id"] for o in client.get(f"/api/v1/course-offerings{q}", headers=AUTH).json()["items"])
    assert len(ids("")) == 3
    assert len(ids("?course_id=cs101")) == 2
    assert len(ids("?semester_id=btcs__2030-31__2")) == 1
    assert len(ids("?faculty_uid=fac-2")) == 1
    assert len(ids("?status=ACTIVE")) == 1
    assert len(ids("?section=A")) == 2
    assert len(ids("?program_id=btcs&academic_session_id=2030-31&department_id=cse")) == 3


def test_offering_update_assign_and_unassign(client, ready):
    oid = mk_off(client).json()["id"]
    r = client.patch(f"/api/v1/course-offerings/{oid}", headers=AUTH,
                     json={"faculty_uid": "fac-1", "room": "R9", "capacity": 40, "status": "ACTIVE"})
    assert r.status_code == 200
    assert (r.json()["faculty_uid"], r.json()["faculty_id"], r.json()["status"]) == ("fac-1", "F-1", "ACTIVE")
    r = client.patch(f"/api/v1/course-offerings/{oid}", headers=AUTH, json={"faculty_uid": None})
    assert r.json()["faculty_uid"] is None and r.json()["faculty_id"] is None
    ready["add"]("stu-1", "STUDENT")
    assert client.patch(f"/api/v1/course-offerings/{oid}", headers=AUTH, json={"faculty_uid": "stu-1"}).status_code == 400
    assert client.patch(f"/api/v1/course-offerings/{oid}", headers=AUTH, json={"course_id": "x"}).status_code == 422
    assert client.patch("/api/v1/course-offerings/none", headers=AUTH, json={"room": "x"}).status_code == 404


@pytest.mark.parametrize("role", ["STUDENT", "FACULTY"])
def test_offering_mutation_forbidden_for_non_admin(client, identity, ready, role):
    oid = mk_off(client).json()["id"]
    as_role(identity, role)
    assert mk_off(client, section="z").status_code == 403
    assert client.patch(f"/api/v1/course-offerings/{oid}", headers=AUTH, json={"faculty_uid": "fac-1"}).status_code == 403


def test_offering_unauthenticated_401(client):
    assert client.get("/api/v1/course-offerings").status_code == 401
    assert client.post("/api/v1/course-offerings", json={}).status_code == 401


def test_faculty_sees_only_own_offerings(client, identity, ready):
    ready["add"]("fac-2", "FACULTY")
    mine = mk_off(client, section="a", faculty_uid="fac-1").json()["id"]
    other = mk_off(client, section="b", faculty_uid="fac-2").json()["id"]
    mk_off(client, section="c")
    identity["claims"] = {"uid": "fac-1", "role": "FACULTY"}
    identity["profile"] = UserProfile(uid="fac-1", role=UserRole.FACULTY)
    items = client.get("/api/v1/course-offerings", headers=AUTH).json()["items"]
    assert [o["id"] for o in items] == [mine]
    # trying to widen the filter does not leak other faculty's offerings
    items = client.get("/api/v1/course-offerings?faculty_uid=fac-2", headers=AUTH).json()["items"]
    assert [o["id"] for o in items] == [mine]
    assert client.get(f"/api/v1/course-offerings/{mine}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/course-offerings/{other}", headers=AUTH).status_code == 404


def test_student_sees_offerings_for_own_program(client, identity, ready):
    mk_prog(client, code="BTEE", name="Other")
    a = mk_off(client, section="a", status="ACTIVE").json()["id"]
    planned = mk_off(client, section="b").json()["id"]
    cancelled = mk_off(client, section="c", status="CANCELLED").json()["id"]
    identity["claims"] = {"uid": "stu-9", "role": "STUDENT"}
    identity["profile"] = UserProfile(uid="stu-9", role=UserRole.STUDENT, program_id="btcs", semester_id="btcs__2030-31__1")
    got = sorted(o["id"] for o in client.get("/api/v1/course-offerings", headers=AUTH).json()["items"])
    assert got == sorted([a, planned])
    assert client.get(f"/api/v1/course-offerings/{cancelled}", headers=AUTH).status_code == 404
    # student with a different program sees nothing; with no program sees nothing
    identity["profile"] = UserProfile(uid="stu-9", role=UserRole.STUDENT, program_id="btee")
    assert client.get("/api/v1/course-offerings", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/course-offerings/{a}", headers=AUTH).status_code == 404
    identity["profile"] = UserProfile(uid="stu-9", role=UserRole.STUDENT)
    assert client.get("/api/v1/course-offerings", headers=AUTH).json()["items"] == []


def test_course_with_open_offering_cannot_be_deactivated(client, ready):
    oid = mk_off(client).json()["id"]
    assert client.patch("/api/v1/courses/cs101", headers=AUTH, json={"is_active": False}).status_code == 409
    client.patch(f"/api/v1/course-offerings/{oid}", headers=AUTH, json={"status": "CANCELLED"})
    assert client.patch("/api/v1/courses/cs101", headers=AUTH, json={"is_active": False}).status_code == 200


def test_swagger_lists_new_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/courses", "/api/v1/courses/{course_id}", "/api/v1/course-offerings",
              "/api/v1/course-offerings/{offering_id}"):
        assert p in paths
