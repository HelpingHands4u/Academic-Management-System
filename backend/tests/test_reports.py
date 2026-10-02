import pytest

from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_attendance import D1, D2, mark as mark_att, pin_today  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_exams import EX, OFF, OFF2, ex, mk_exam, mk_sch  # noqa: F401
from test_marks_results import R1, final_marks, gen, gx, mark, set_scheme  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401


def rep(client, name, expect=200, **p):
    r = client.get(f"/api/v1/reports/{name}", headers=AUTH, params=p)
    assert r.status_code == expect, r.text
    return r.json()


# ---- students / faculty -------------------------------------------------------
def test_student_report_admin_values_filters_pagination(client, identity, enrol):
    b = rep(client, "students")
    assert b["summary"]["total"] == 2 and b["summary"]["active"] == 2
    assert b["summary"]["by_program"] == {"btcs": 2} and b["summary"]["by_semester"] == {SEM: 2}
    assert rep(client, "students", section="b")["summary"]["total"] == 0
    first = rep(client, "students", limit=1)
    assert len(first["items"]) == 1 and first["next_cursor"] == "s-001" and first["summary"]["total"] == 2
    second = rep(client, "students", limit=1, cursor=first["next_cursor"])
    assert second["items"][0]["student_id"] == "S-002" and second["next_cursor"] is None


def test_faculty_report(client, identity, enrol):
    assert mk_fac(client).status_code == 201
    b = rep(client, "faculty")
    assert b["summary"]["total"] == 1 and b["summary"]["by_designation"] == {"Professor": 1}
    assert rep(client, "faculty", is_active=False)["summary"]["total"] == 0


def test_empty_reports_are_zero_not_fabricated(client, identity, store):
    for name in ("students", "faculty", "courses", "attendance", "examinations", "results", "enrollments"):
        b = rep(client, name)
        assert b["items"] == [] and b["next_cursor"] is None
        assert b["summary"].get("total", b["summary"].get("total_records", b["summary"].get("total_schedules"))) == 0


@pytest.mark.parametrize("name", ["students", "faculty"])
def test_students_faculty_reports_admin_only(client, identity, enrol, name):
    for role in ("FACULTY", "STUDENT"):
        as_role(identity, role)
        assert rep(client, name, expect=403)


# ---- courses ----------------------------------------------------------------------
def test_course_report_admin_and_faculty_scope(client, identity, ex):
    b = rep(client, "courses")
    assert b["summary"]["total"] == 2 and b["summary"]["total_credits"] == 8.0
    assert rep(client, "courses", program_id="btcs", course_type="CORE")["summary"]["total"] >= 0
    login(identity, "fac-2", "FACULTY")
    f = rep(client, "courses")
    assert [c["id"] for c in f["items"]] == ["cs102"]
    login(identity, "stu-1", "STUDENT")
    rep(client, "courses", expect=403)


# ---- attendance ---------------------------------------------------------------------
def test_attendance_report_values_and_filters(client, identity, ex):
    mark_att(client, "S-001", D1, "PRESENT")
    mark_att(client, "S-001", D2, "ABSENT")
    mark_att(client, "S-002", D1, "LATE")
    assert mk_fac(client).status_code == 201
    b = rep(client, "attendance")
    s = b["summary"]
    assert (s["total_records"], s["attended_count"], s["attendance_percentage"], s["students"]) == (3, 2, 66.67, 2)
    assert len(b["items"]) == 2
    one = rep(client, "attendance", student_id="S-001")
    assert one["summary"]["attendance_percentage"] == 50.0
    day = rep(client, "attendance", from_date=D2, to_date=D2)
    assert day["summary"]["total_records"] == 1
    assert rep(client, "attendance", faculty_id="f-001")["summary"]["total_records"] == 3
    assert rep(client, "attendance", faculty_id="ghost", expect=404)
    assert rep(client, "attendance", from_date=D2, to_date=D1, expect=422)
    page = rep(client, "attendance", limit=1)
    assert len(page["items"]) == 1 and page["next_cursor"]


def test_attendance_report_scoping(client, identity, ex):
    mark_att(client, "S-001")
    mark_att(client, "S-002")
    login(identity, "stu-1", "STUDENT")
    b = rep(client, "attendance", student_id="S-002")  # another student's id cannot widen scope
    assert b["summary"]["total_records"] == 0
    assert rep(client, "attendance")["summary"]["total_records"] == 1
    login(identity, "fac-2", "FACULTY")
    assert rep(client, "attendance")["summary"]["total_records"] == 0
    login(identity, "fac-1", "FACULTY")
    assert rep(client, "attendance")["summary"]["total_records"] == 2


# ---- examinations ----------------------------------------------------------------------
def test_examination_report(client, identity, ex):
    assert mk_sch(client).status_code == 201
    b = rep(client, "examinations")
    assert b["summary"]["total_schedules"] == 1 and b["summary"]["by_status"] == {"SCHEDULED": 1}
    assert rep(client, "examinations", from_date="2031-01-01")["summary"]["total_schedules"] == 0
    assert rep(client, "examinations", from_date="2030-12-02", to_date="2030-12-02")["items"][0]["course_offering_id"] == OFF
    login(identity, "fac-2", "FACULTY")
    assert rep(client, "examinations")["items"] == []
    login(identity, "stu-1", "STUDENT")
    assert len(rep(client, "examinations")["items"]) == 1
    login(identity, "stu-2", "STUDENT")
    assert len(rep(client, "examinations")["items"]) == 1  # enrolled in OFF as well


# ---- results ---------------------------------------------------------------------------
def test_result_report_and_privacy(client, identity, gx):
    final_marks(client)
    gen(client)
    b = rep(client, "results")
    assert b["summary"]["total"] == 1 and b["summary"]["average_sgpa"] == 8.67 and b["summary"]["published"] == 0
    assert b["summary"]["grade_distribution"] == {"A": 1, "C": 1}
    login(identity, "stu-1", "STUDENT")
    assert rep(client, "results")["items"] == []  # unpublished is hidden
    login(identity, "admin-1", "ADMIN")
    client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    login(identity, "stu-1", "STUDENT")
    assert len(rep(client, "results")["items"]) == 1
    login(identity, "stu-2", "STUDENT")
    assert rep(client, "results", student_id="S-001")["items"] == []
    login(identity, "fac-1", "FACULTY")
    f = rep(client, "results")
    assert "average_sgpa" not in f["summary"] and f["items"][0]["sgpa"] is None


# ---- enrollments -------------------------------------------------------------------------
def test_enrollment_report(client, identity, ex):
    b = rep(client, "enrollments")
    assert b["summary"]["total"] == 3 and b["summary"]["distinct_students"] == 2
    assert b["summary"]["by_status"] == {"ACTIVE": 3}
    assert rep(client, "enrollments", course_offering_id=OFF2)["summary"]["total"] == 1
    assert rep(client, "enrollments", student_id="S-002")["summary"]["total"] == 1
    assert rep(client, "enrollments", program_id="other")["summary"]["total"] == 0
    assert rep(client, "enrollments", from_date="2000-01-01", to_date="2999-01-01")["summary"]["total"] == 3
    assert rep(client, "enrollments", from_date="2999-01-01")["summary"]["total"] == 0
    p = rep(client, "enrollments", limit=2)
    assert len(p["items"]) == 2 and p["next_cursor"]
    login(identity, "stu-2", "STUDENT")
    assert rep(client, "enrollments", student_id="S-001")["summary"]["total"] == 0  # cannot widen scope
    assert rep(client, "enrollments")["summary"]["total"] == 1
    login(identity, "fac-2", "FACULTY")
    assert rep(client, "enrollments")["summary"]["total"] == 1


def test_reports_unauthenticated_and_swagger(client):
    assert client.get("/api/v1/reports/enrollments").status_code == 401
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/reports/students", "/api/v1/reports/enrollments", "/api/v1/analytics/admin",
              "/api/v1/analytics/faculty/me", "/api/v1/analytics/student/me", "/api/v1/analytics/active-users",
              "/api/v1/audit-logs", "/api/v1/sessions", "/api/v1/sessions/{session_id}/heartbeat",
              "/api/v1/sessions/{session_id}/logout", "/api/v1/users/{uid}"):
        assert p in paths, p


