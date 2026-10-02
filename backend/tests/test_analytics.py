import pytest

from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_attendance import D1, D2, mark as mark_att, pin_today  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_exams import EX, OFF, OFF2, ex, mk_exam, mk_sch  # noqa: F401
from test_marks_results import R1, final_marks, gen, gx, mark, set_scheme  # noqa: F401
from test_notices import mk_notice
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401
from test_timetable import mk_tt

ADMIN_KEYS = {"active_students", "active_faculty", "departments", "programs", "courses", "course_offerings",
              "active_enrollments", "examinations", "attendance_records", "published_results", "active_notices"}


def get(client, path, **p):
    return client.get(f"/api/v1/analytics/{path}", headers=AUTH, params=p)


# ---- admin ------------------------------------------------------------------
def test_admin_analytics_empty_database(client, identity, store):
    r = get(client, "admin")
    assert r.status_code == 200
    assert r.json() == {k: 0 for k in ADMIN_KEYS}


def test_admin_analytics_counts_real_data(client, identity, ex, store):
    mk_fac(client)
    mk_notice(client)
    mk_notice(client, title="Off", is_published=False)
    b = get(client, "admin").json()
    assert (b["active_students"], b["active_faculty"], b["departments"], b["programs"]) == (2, 1, 1, 1)
    assert (b["courses"], b["course_offerings"], b["examinations"]) == (2, 2, 1)
    assert (b["active_enrollments"], b["published_results"], b["active_notices"], b["attendance_records"]) == (3, 0, 1, 0)
    mark_att(client)
    client.patch("/api/v1/students/s-002", headers=AUTH, json={"is_active": False})
    client.patch(f"/api/v1/enrollments/s-002__{OFF}", headers=AUTH, json={"status": "DROPPED"})
    b = get(client, "admin").json()
    assert (b["attendance_records"], b["active_students"]) == (1, 1)


def test_admin_analytics_roles(client, identity):
    assert client.get("/api/v1/analytics/admin").status_code == 401
    for role in ("STUDENT", "FACULTY"):
        as_role(identity, role)
        assert get(client, "admin").status_code == 403


# ---- faculty ----------------------------------------------------------------
def test_faculty_analytics(client, identity, ex):
    assert mk_sch(client).status_code == 201
    assert mark_att(client).status_code == 201
    assert mark_att(client, "S-002", D1).status_code == 201
    login(identity, "fac-1", "FACULTY")
    b = get(client, "faculty/me").json()
    assert b["assigned_course_offerings"] == 1 and b["enrolled_students"] == 2
    assert b["attendance_records"] == 2 and b["upcoming_exam_schedules"] == 1
    assert b["pending_marks"] == 2  # two enrolled students, one schedule, no marks
    assert b["attendance_completion_percentage"] is None
    login(identity, "admin-1", "ADMIN")
    set_scheme(client)
    assert mark(client, "S-001").status_code == 201
    login(identity, "fac-1", "FACULTY")
    assert get(client, "faculty/me").json()["pending_marks"] == 1


def test_faculty_analytics_other_faculty_sees_only_own(client, identity, ex):
    mk_sch(client)
    login(identity, "fac-2", "FACULTY")
    b = get(client, "faculty/me").json()
    assert (b["assigned_course_offerings"], b["enrolled_students"], b["attendance_records"],
            b["upcoming_exam_schedules"], b["pending_marks"]) == (1, 1, 0, 0, 0)


def test_faculty_analytics_no_assignments_and_roles(client, identity, ex):
    login(identity, "nobody", "FACULTY")
    b = get(client, "faculty/me").json()
    assert (b["assigned_course_offerings"], b["enrolled_students"], b["pending_marks"]) == (0, 0, 0)
    as_role(identity, "STUDENT")
    assert get(client, "faculty/me").status_code == 403
    as_role(identity, "ADMIN")
    assert get(client, "faculty/me").status_code == 403


# ---- student ----------------------------------------------------------------
def test_student_analytics_full(client, identity, gx):
    mk_sch(client)
    mk_notice(client, title="All")
    mk_notice(client, title="Staff", audience="FACULTY")
    mk_tt(client)
    mark_att(client, status="PRESENT")
    mark_att(client, on=D2, status="ABSENT")
    mark_att(client, "S-002", D1)
    final_marks(client)
    assert gen(client).status_code == 201
    login(identity, "stu-1", "STUDENT")
    assert get(client, "student/me").json()["published_results"] == 0
    assert get(client, "student/me").json()["cgpa"]["cgpa"] is None
    login(identity, "admin-1", "ADMIN")
    assert client.post(f"/api/v1/results/{R1}/publish", headers=AUTH).status_code == 200
    login(identity, "stu-1", "STUDENT")
    b = get(client, "student/me").json()
    assert b["profile_found"] and b["enrolled_courses"] == 2
    assert {e["student_id"] for e in b["enrollments"]} == {"S-001"}
    att = {a["course_offering_id"]: a for a in b["attendance"]}
    assert len(att) == 1 and att[OFF]["total_classes"] == 2 and att[OFF]["attendance_percentage"] == 50.0
    assert {a["student_id"] for a in b["attendance"]} == {"S-001"}
    assert [e["course_offering_id"] for e in b["upcoming_exams"]] == [OFF]
    assert b["published_results"] == 1 and b["sgpa"][0]["sgpa"] == 8.67
    assert b["cgpa"]["cgpa"] == 8.67 and b["cgpa"]["status"] == "COMPLETE"
    assert len(b["timetable"]) == 1
    assert [n["title"] for n in b["notices"]] == ["All"]


def test_student_sees_only_own_data(client, identity, gx):
    mark_att(client, "S-001")
    mark_att(client, "S-002")
    login(identity, "stu-2", "STUDENT")
    b = get(client, "student/me").json()
    assert {a["student_id"] for a in b["attendance"]} == {"S-002"}
    assert {e["student_id"] for e in b["enrollments"]} == {"S-002"}
    assert b["enrolled_courses"] == 1


def test_student_without_profile_gets_safe_empty_response(client, identity, store):
    login(identity, "ghost", "STUDENT")
    b = get(client, "student/me").json()
    assert b["profile_found"] is False and b["cgpa"] is None
    assert (b["enrolled_courses"], b["attendance"], b["timetable"], b["notices"]) == (0, [], [], [])


def test_student_analytics_has_no_user_parameter_and_roles(client, identity, gx):
    login(identity, "stu-1", "STUDENT")
    # a foreign uid / student id in the query is ignored: data is always the caller's
    assert get(client, "student/me", uid="stu-2", student_id="S-002").json()["enrollments"][0]["student_id"] == "S-001"
    for role in ("FACULTY", "ADMIN"):
        as_role(identity, role)
        assert get(client, "student/me").status_code == 403
    assert client.get("/api/v1/analytics/student/me").status_code == 401

