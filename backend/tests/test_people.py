import pytest

from app.schemas.user import UserProfile, UserRole
from app.services import user_links
from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401

SEM = "btcs__2030-31__1"


@pytest.fixture
def people(monkeypatch, store):
    """Fake Firebase Auth accounts + users/{uid} docs for linking profiles."""
    state = {"auth": {}, "profiles": {}}
    monkeypatch.setattr(user_links, "get_auth_account_info", lambda uid: state["auth"].get(uid))
    monkeypatch.setattr(user_links, "get_user_profile", lambda uid: state["profiles"].get(uid))

    def add(uid, role, active=True, disabled=False, claim="same", **extra):
        state["auth"][uid] = {"disabled": disabled, "role": role if claim == "same" else claim}
        state["profiles"][uid] = UserProfile(uid=uid, email=f"{uid}@example.com", display_name=uid.title(),
                                             role=UserRole(role), is_active=active, **extra)
        store.docs[("users", uid)] = {"uid": uid, "role": role}

    state["add"] = add
    return state


def mk_student(client, uid="stu-1", sid="s-001", **kw):
    body = {"uid": uid, "student_id": sid, "department_id": "cse", "program_id": "btcs",
            "current_semester_id": SEM, "admission_year": 2030, "batch": "2030", "section": "a", **kw}
    return client.post("/api/v1/students", headers=AUTH, json=body)


def mk_fac(client, uid="fac-1", fid="f-001", **kw):
    return client.post("/api/v1/faculty", headers=AUTH,
                       json={"uid": uid, "faculty_id": fid, "department_id": "cse", "designation": "Professor", **kw})


def mk_enr(client, sid="S-001", offering="cs101__btcs__2030-31__1__a"):
    return client.post("/api/v1/enrollments", headers=AUTH, json={"student_id": sid, "course_offering_id": offering})


def login(identity, uid, role, **profile):
    identity["claims"] = {"uid": uid, "role": role}
    identity["profile"] = UserProfile(uid=uid, role=UserRole(role), **profile)


# ---- students -------------------------------------------------------------
def test_student_create_links_user_and_has_no_secrets(client, base, people, store):
    people["add"]("stu-1", "STUDENT")
    r = mk_student(client)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == "s-001" and b["student_id"] == "S-001" and b["uid"] == "stu-1"
    assert b["email"] == "stu-1@example.com" and b["display_name"] == "Stu-1"
    assert b["section"] == "A" and b["is_active"] is True and b["created_at"]
    u = store.docs[("users", "stu-1")]
    assert (u["student_id"], u["program_id"], u["semester_id"]) == ("S-001", "btcs", SEM)
    assert "password" not in str(store.docs[("students", "s-001")]).lower()


def test_student_invalid_firebase_user_404(client, base, people):
    assert mk_student(client, uid="ghost").status_code == 404
    people["auth"]["noprofile"] = {"disabled": False, "role": "STUDENT"}
    assert mk_student(client, uid="noprofile").status_code == 404


def test_student_wrong_role_400(client, base, people):
    people["add"]("fac-1", "FACULTY")
    people["add"]("adm-1", "ADMIN")
    people["add"]("odd", "STUDENT", claim="ADMIN")
    assert mk_student(client, uid="fac-1").status_code == 400
    assert mk_student(client, uid="adm-1").status_code == 400
    assert mk_student(client, uid="odd").status_code == 400


def test_student_inactive_user_400(client, base, people):
    people["add"]("a", "STUDENT", active=False)
    people["add"]("b", "STUDENT", disabled=True)
    assert mk_student(client, uid="a").status_code == 400
    assert mk_student(client, uid="b").status_code == 400


def test_student_academic_validation(client, base, people):
    people["add"]("stu-1", "STUDENT")
    mk_dept(client, "ECE", name="Electronics")
    mk_prog(client, dept="ece", code="BTEC")
    mk_sem(client, program="btec")
    assert mk_student(client, department_id="ghost").status_code == 404
    assert mk_student(client, program_id="ghost").status_code == 404
    assert mk_student(client, department_id="ece").status_code == 400  # program/department mismatch
    assert mk_student(client, current_semester_id="ghost").status_code == 404
    assert mk_student(client, current_semester_id="btec__2030-31__1").status_code == 400  # semester/program mismatch


def test_student_duplicates_409(client, base, people):
    people["add"]("stu-1", "STUDENT")
    people["add"]("stu-2", "STUDENT")
    assert mk_student(client).status_code == 201
    assert mk_student(client, uid="stu-2", sid="s-001").status_code == 409  # duplicate student_id
    assert mk_student(client, uid="stu-1", sid="S-002").status_code == 409  # duplicate uid


def test_student_conflicting_user_profile_id_400(client, base, people):
    people["add"]("stu-1", "STUDENT", student_id="OTHER")
    assert mk_student(client).status_code == 400


def test_student_failed_create_leaves_no_partial_state(client, base, people, store):
    people["add"]("stu-1", "STUDENT")
    people["add"]("stu-2", "STUDENT")
    mk_student(client)
    mk_student(client, uid="stu-2", sid="S-001")
    assert "student_id" not in store.docs[("users", "stu-2")]


def test_student_validation_422(client, base, people):
    people["add"]("stu-1", "STUDENT")
    assert mk_student(client, admission_year=1800).status_code == 422
    assert mk_student(client, student_id="").status_code == 422
    assert mk_student(client, email="x@y.com").status_code == 422
    assert mk_student(client, role="ADMIN").status_code == 422
    assert client.post("/api/v1/students", headers=AUTH, json={}).status_code == 422


def test_student_read_update_list(client, base, people, store):
    people["add"]("stu-1", "STUDENT")
    mk_student(client)
    assert client.get("/api/v1/students/S-001", headers=AUTH).json()["uid"] == "stu-1"
    assert client.get("/api/v1/students/s-001", headers=AUTH).status_code == 200
    assert client.get("/api/v1/students/none", headers=AUTH).status_code == 404
    r = client.patch("/api/v1/students/s-001", headers=AUTH, json={"section": "b", "batch": "2031"})
    assert r.status_code == 200 and r.json()["section"] == "B" and r.json()["batch"] == "2031"
    r = client.patch("/api/v1/students/s-001", headers=AUTH, json={"current_semester_id": None})
    assert r.json()["current_semester_id"] is None and store.docs[("users", "stu-1")]["semester_id"] is None
    for bad in ({"uid": "x"}, {"student_id": "X"}, {"email": "a@b.com"}):
        assert client.patch("/api/v1/students/s-001", headers=AUTH, json=bad).status_code == 422
    assert client.patch("/api/v1/students/s-001", headers=AUTH, json={"program_id": "ghost"}).status_code == 404
    assert client.patch("/api/v1/students/none", headers=AUTH, json={"section": "a"}).status_code == 404
    people["add"]("stu-2", "STUDENT")
    mk_student(client, uid="stu-2", sid="S-002", section="b")
    ids = lambda q: sorted(s["id"] for s in client.get(f"/api/v1/students{q}", headers=AUTH).json()["items"])
    assert ids("") == ["s-001", "s-002"]
    assert ids("?section=B") == ["s-001", "s-002"]
    assert ids("?department_id=cse&program_id=btcs&semester_id=" + SEM + "&batch=2030&is_active=true") == ["s-002"]
    assert ids("?is_active=false") == []


def test_student_authorization(client, identity, base, people):
    people["add"]("stu-1", "STUDENT")
    people["add"]("stu-2", "STUDENT")
    mk_student(client)
    mk_student(client, uid="stu-2", sid="S-002")
    assert client.get("/api/v1/students").status_code == 401
    login(identity, "stu-1", "STUDENT")
    assert client.get("/api/v1/students/me", headers=AUTH).json()["student_id"] == "S-001"
    assert client.get("/api/v1/students/S-001", headers=AUTH).status_code == 200
    assert client.get("/api/v1/students/S-002", headers=AUTH).status_code == 404  # other student hidden
    assert client.get("/api/v1/students", headers=AUTH).status_code == 403
    assert mk_student(client, uid="stu-3", sid="S-9").status_code == 403
    assert client.patch("/api/v1/students/s-001", headers=AUTH, json={"program_id": "btcs"}).status_code == 403
    login(identity, "fac-1", "FACULTY")
    assert client.get("/api/v1/students/me", headers=AUTH).status_code == 403
    assert client.get("/api/v1/students/S-001", headers=AUTH).status_code == 403
    login(identity, "stu-9", "STUDENT")
    assert client.get("/api/v1/students/me", headers=AUTH).status_code == 404  # no profile yet
    login(identity, "stu-1", "STUDENT", is_active=False)
    assert client.get("/api/v1/students/me", headers=AUTH).status_code == 403


# ---- faculty --------------------------------------------------------------
def test_faculty_create(client, base, people, store):
    people["add"]("fac-1", "FACULTY")
    r = mk_fac(client)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == "f-001" and b["faculty_id"] == "F-001" and b["uid"] == "fac-1"
    assert b["email"] == "fac-1@example.com" and b["designation"] == "Professor"
    assert store.docs[("users", "fac-1")]["faculty_id"] == "F-001"


def test_faculty_validation_and_conflicts(client, base, people):
    people["add"]("fac-1", "FACULTY")
    people["add"]("fac-2", "FACULTY")
    people["add"]("stu-1", "STUDENT")
    people["add"]("fac-off", "FACULTY", active=False)
    assert mk_fac(client, uid="ghost").status_code == 404
    assert mk_fac(client, uid="stu-1").status_code == 400
    assert mk_fac(client, uid="fac-off").status_code == 400
    assert mk_fac(client, department_id="ghost").status_code == 404
    assert mk_fac(client, faculty_id="").status_code == 422
    assert mk_fac(client).status_code == 201
    assert mk_fac(client, uid="fac-2", fid="F-001").status_code == 409
    assert mk_fac(client, uid="fac-1", fid="F-002").status_code == 409


def test_faculty_read_update_list(client, base, people):
    people["add"]("fac-1", "FACULTY")
    mk_fac(client)
    assert client.get("/api/v1/faculty/F-001", headers=AUTH).json()["department_id"] == "cse"
    assert client.get("/api/v1/faculty/none", headers=AUTH).status_code == 404
    r = client.patch("/api/v1/faculty/f-001", headers=AUTH, json={"designation": "Lecturer"})
    assert r.status_code == 200 and r.json()["designation"] == "Lecturer"
    assert client.patch("/api/v1/faculty/f-001", headers=AUTH, json={"uid": "x"}).status_code == 422
    assert client.patch("/api/v1/faculty/f-001", headers=AUTH, json={"department_id": "ghost"}).status_code == 404
    ids = lambda q: [f["id"] for f in client.get(f"/api/v1/faculty{q}", headers=AUTH).json()["items"]]
    assert ids("?department_id=cse&designation=Lecturer&is_active=true") == ["f-001"]
    assert ids("?designation=Professor") == []


def test_faculty_authorization(client, identity, base, people):
    people["add"]("fac-1", "FACULTY")
    people["add"]("fac-2", "FACULTY")
    mk_fac(client)
    mk_fac(client, uid="fac-2", fid="F-002")
    login(identity, "fac-1", "FACULTY")
    assert client.get("/api/v1/faculty/me", headers=AUTH).json()["faculty_id"] == "F-001"
    assert client.get("/api/v1/faculty/F-001", headers=AUTH).status_code == 200
    assert client.get("/api/v1/faculty/F-002", headers=AUTH).status_code == 404
    assert client.get("/api/v1/faculty", headers=AUTH).status_code == 403
    assert mk_fac(client, uid="x", fid="X").status_code == 403
    assert client.patch("/api/v1/faculty/f-001", headers=AUTH, json={"designation": "Dean"}).status_code == 403
    login(identity, "stu-1", "STUDENT")
    assert client.get("/api/v1/faculty/me", headers=AUTH).status_code == 403
    assert client.get("/api/v1/faculty/F-001", headers=AUTH).status_code == 403


# ---- enrollments ----------------------------------------------------------
@pytest.fixture
def enrol(client, ready, people):
    """Course cs101 offered to section A of semester 1, faculty fac-1, students stu-1/stu-2."""
    for uid in ("stu-1", "stu-2", "stu-3"):
        people["add"](uid, "STUDENT")
    people["add"]("fac-1", "FACULTY")
    mk_off(client, section="a", faculty_uid="fac-1", status="ACTIVE")
    mk_student(client, "stu-1", "S-001")
    mk_student(client, "stu-2", "S-002")
    return people


def test_enrollment_create_and_read(client, enrol):
    r = mk_enr(client)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == "s-001__cs101__btcs__2030-31__1__a"
    assert (b["student_uid"], b["student_id"], b["course_id"], b["semester_id"], b["program_id"], b["section"],
            b["status"]) == ("stu-1", "S-001", "cs101", SEM, "btcs", "A", "ACTIVE")
    assert b["academic_session_id"] == "2030-31" and b["enrolled_at"] and b["dropped_at"] is None
    assert client.get(f"/api/v1/enrollments/{b['id']}", headers=AUTH).status_code == 200
    assert client.get("/api/v1/enrollments/none", headers=AUTH).status_code == 404


def test_enrollment_invalid_student_and_offering(client, enrol):
    assert mk_enr(client, sid="NOPE").status_code == 404
    assert mk_enr(client, offering="ghost").status_code == 404
    assert client.post("/api/v1/enrollments", headers=AUTH, json={"student_id": "S-001"}).status_code == 422
    assert client.post("/api/v1/enrollments", headers=AUTH,
                       json={"student_id": "S-001", "course_offering_id": "cs101__btcs__2030-31__1__a",
                             "status": "COMPLETED"}).status_code == 422


def test_enrollment_inactive_student_and_closed_offering(client, enrol):
    client.patch("/api/v1/students/s-002", headers=AUTH, json={"is_active": False})
    assert mk_enr(client, sid="S-002").status_code == 400
    client.patch("/api/v1/course-offerings/cs101__btcs__2030-31__1__a", headers=AUTH, json={"status": "CANCELLED"})
    assert mk_enr(client).status_code == 400


def test_enrollment_program_mismatch(client, enrol, people):
    mk_dept(client, "ECE", name="Electronics")
    mk_prog(client, dept="ece", code="BTEC")
    mk_sem(client, program="btec")
    people["add"]("stu-4", "STUDENT")
    assert client.post("/api/v1/students", headers=AUTH, json={
        "uid": "stu-4", "student_id": "S-004", "department_id": "ece", "program_id": "btec",
        "current_semester_id": "btec__2030-31__1", "admission_year": 2030}).status_code == 201
    assert mk_enr(client, sid="S-004").status_code == 400


def test_enrollment_semester_and_section_mismatch(client, enrol, people):
    mk_sem(client, number=2)
    people["add"]("stu-5", "STUDENT")
    mk_student(client, "stu-5", "S-005", current_semester_id="btcs__2030-31__2", section=None)
    assert mk_enr(client, sid="S-005").status_code == 400  # semester mismatch
    mk_student(client, "stu-3", "S-003", section="b")
    assert mk_enr(client, sid="S-003").status_code == 400  # section mismatch
    # no semester / section on the student: not constrained by them
    people["add"]("stu-6", "STUDENT")
    mk_student(client, "stu-6", "S-006", current_semester_id=None, section=None)
    assert mk_enr(client, sid="S-006").status_code == 201


def test_enrollment_duplicate_active_409(client, enrol):
    assert mk_enr(client).status_code == 201
    assert mk_enr(client).status_code == 409


def test_enrollment_status_lifecycle(client, enrol):
    eid = mk_enr(client).json()["id"]
    url = f"/api/v1/enrollments/{eid}"
    r = client.patch(url, headers=AUTH, json={"status": "DROPPED"})
    assert r.status_code == 200 and r.json()["status"] == "DROPPED" and r.json()["dropped_at"]
    assert client.patch(url, headers=AUTH, json={"status": "COMPLETED"}).status_code == 400
    r = client.patch(url, headers=AUTH, json={"status": "ACTIVE"})
    assert r.json()["status"] == "ACTIVE" and r.json()["dropped_at"] is None
    assert client.patch(url, headers=AUTH, json={"status": "COMPLETED"}).json()["status"] == "COMPLETED"
    assert client.patch(url, headers=AUTH, json={"status": "DROPPED"}).status_code == 400
    assert client.patch(url, headers=AUTH, json={"status": "PENDING"}).status_code == 422
    assert client.patch("/api/v1/enrollments/none", headers=AUTH, json={"status": "DROPPED"}).status_code == 404


def test_reenroll_after_drop_reuses_record(client, enrol):
    eid = mk_enr(client).json()["id"]
    client.patch(f"/api/v1/enrollments/{eid}", headers=AUTH, json={"status": "DROPPED"})
    r = mk_enr(client)
    assert r.status_code == 201 and r.json()["id"] == eid and r.json()["status"] == "ACTIVE"
    assert mk_enr(client).status_code == 409


def test_enrollment_visibility_student_own_only(client, identity, enrol):
    mine = mk_enr(client, "S-001").json()["id"]
    other = mk_enr(client, "S-002").json()["id"]
    login(identity, "stu-1", "STUDENT")
    items = client.get("/api/v1/enrollments", headers=AUTH).json()["items"]
    assert [e["id"] for e in items] == [mine]
    items = client.get("/api/v1/enrollments?student_uid=stu-2&student_id=S-002", headers=AUTH).json()["items"]
    assert items == []
    assert client.get(f"/api/v1/enrollments/{mine}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/enrollments/{other}", headers=AUTH).status_code == 404
    assert mk_enr(client, "S-001").status_code == 403
    assert client.patch(f"/api/v1/enrollments/{mine}", headers=AUTH, json={"status": "DROPPED"}).status_code == 403
    assert client.patch(f"/api/v1/enrollments/{other}", headers=AUTH, json={"status": "DROPPED"}).status_code == 403


def test_enrollment_visibility_faculty_assigned_only(client, identity, enrol, people, accounts):
    accounts["add"]("fac-2", "FACULTY")
    mk_course(client, "CS102")
    mk_off(client, course="cs102", section="a", faculty_uid="fac-2", status="ACTIVE")
    mine = mk_enr(client, "S-001").json()["id"]
    other = mk_enr(client, "S-001", "cs102__btcs__2030-31__1__a").json()["id"]
    login(identity, "fac-1", "FACULTY")
    assert [e["id"] for e in client.get("/api/v1/enrollments", headers=AUTH).json()["items"]] == [mine]
    assert [e["id"] for e in client.get("/api/v1/enrollments?course_offering_id=cs101__btcs__2030-31__1__a",
                                        headers=AUTH).json()["items"]] == [mine]
    assert client.get("/api/v1/enrollments?course_offering_id=cs102__btcs__2030-31__1__a",
                      headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/enrollments/{mine}", headers=AUTH).status_code == 200
    assert client.get(f"/api/v1/enrollments/{other}", headers=AUTH).status_code == 404
    assert mk_enr(client, "S-002").status_code == 403
    assert client.patch(f"/api/v1/enrollments/{mine}", headers=AUTH, json={"status": "DROPPED"}).status_code == 403
    login(identity, "fac-9", "FACULTY")
    assert client.get("/api/v1/enrollments", headers=AUTH).json()["items"] == []


def test_enrollment_admin_access_and_filters(client, enrol):
    mk_course(client, "CS102")
    mk_off(client, course="cs102", section="a", status="ACTIVE")
    a = mk_enr(client, "S-001").json()["id"]
    b = mk_enr(client, "S-002").json()["id"]
    c = mk_enr(client, "S-001", "cs102__btcs__2030-31__1__a").json()["id"]
    client.patch(f"/api/v1/enrollments/{c}", headers=AUTH, json={"status": "DROPPED"})
    ids = lambda q: sorted(e["id"] for e in client.get(f"/api/v1/enrollments{q}", headers=AUTH).json()["items"])
    assert ids("") == sorted([a, b, c])
    assert ids("?student_id=S-001") == sorted([a, c])
    assert ids("?student_uid=stu-2") == [b]
    assert ids("?course_offering_id=cs101__btcs__2030-31__1__a") == sorted([a, b])
    assert ids("?course_id=cs102") == [c]
    assert ids(f"?semester_id={SEM}&status=DROPPED") == [c]
    assert ids("?status=ACTIVE") == sorted([a, b])
    assert client.get("/api/v1/enrollments?limit=2", headers=AUTH).json()["next_cursor"]


def test_enrollment_unauthenticated_and_no_role(client, identity, enrol):
    assert client.get("/api/v1/enrollments").status_code == 401
    assert client.post("/api/v1/enrollments", json={}).status_code == 401
    identity["claims"], identity["profile"] = {"uid": "nobody"}, None
    assert client.get("/api/v1/enrollments", headers=AUTH).status_code == 403


def test_swagger_lists_phase6_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/students", "/api/v1/students/me", "/api/v1/students/{student_id}", "/api/v1/faculty",
              "/api/v1/faculty/me", "/api/v1/faculty/{faculty_id}", "/api/v1/enrollments",
              "/api/v1/enrollments/{enrollment_id}"):
        assert p in paths

