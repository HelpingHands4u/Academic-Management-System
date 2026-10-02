import pytest
from pydantic import ValidationError

from app.core.errors import UnprocessableAcademicError
from app.schemas.marks import GradingScheme
from app.services import grading
from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_exams import EX, OFF, OFF2, ex, mk_exam, mk_sch  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401

# Test-only scheme: NOT an official university grading scale.
BANDS = [
    {"grade": "F", "min_percentage": 0, "max_percentage": 40, "grade_point": 0, "is_pass": False},
    {"grade": "D", "min_percentage": 40, "max_percentage": 50, "grade_point": 5},
    {"grade": "C", "min_percentage": 50, "max_percentage": 60, "grade_point": 6},
    {"grade": "B", "min_percentage": 60, "max_percentage": 80, "grade_point": 8},
    {"grade": "A", "min_percentage": 80, "max_percentage": 100, "grade_point": 10},
]
SCHEME = GradingScheme(bands=BANDS)
M1 = f"s-001__{OFF}__{EX}"
M2 = f"s-001__{OFF2}__{EX}"
R1 = f"s-001__{SEM}"


def set_scheme(client, bands=BANDS):
    return client.put("/api/v1/grading-scheme", headers=AUTH, json={"name": "test", "bands": bands})


def mark(client, sid="S-001", offering=OFF, **kw):
    body = {"student_id": sid, "course_offering_id": offering, "examination_id": EX,
            "external_marks": 60, "internal_marks": 20, **kw}
    return client.post("/api/v1/marks", headers=AUTH, json=body)


@pytest.fixture
def gx(client, ex):
    assert set_scheme(client).status_code == 200
    return ex


# ---- grading service ------------------------------------------------------
@pytest.mark.parametrize("pct,grade,gp", [(0, "F", 0), (39.99, "F", 0), (40, "D", 5), (49.99, "D", 5), (50, "C", 6),
                                          (59.99, "C", 6), (60, "B", 8), (79.99, "B", 8), (80, "A", 10), (100, "A", 10)])
def test_grade_boundaries(pct, grade, gp):
    g = grading.calculate_grade(pct, SCHEME)
    assert (g.grade, g.grade_point) == (grade, gp)


@pytest.mark.parametrize("bad", [-0.01, 100.01, float("nan"), float("inf"), None, True])
def test_invalid_percentage(bad):
    with pytest.raises(UnprocessableAcademicError):
        grading.calculate_grade(bad, SCHEME)


def test_overlapping_and_gapped_schemes_rejected(client):
    overlap = [dict(BANDS[0], max_percentage=45), *BANDS[1:]]
    gap = [dict(BANDS[0], max_percentage=35), *BANDS[1:]]
    short = BANDS[:-1]
    dup = [dict(BANDS[1], grade="F"), *[b for b in BANDS if b["grade"] != "D"]]
    for bands in (overlap, gap, short, dup, [dict(BANDS[0], grade_point=11), *BANDS[1:]], []):
        with pytest.raises(ValidationError):
            GradingScheme(bands=bands)
        assert set_scheme(client, bands).status_code == 422


def test_scheme_admin_only_and_required(client, identity, base):
    assert client.get("/api/v1/grading-scheme", headers=AUTH).status_code == 404
    as_role(identity, "FACULTY")
    assert set_scheme(client).status_code == 403
    as_role(identity, "ADMIN")
    assert set_scheme(client).status_code == 200
    assert set_scheme(client).status_code == 200  # replaceable
    assert len(client.get("/api/v1/grading-scheme", headers=AUTH).json()["bands"]) == 5


def test_sgpa_cgpa_math():
    assert grading.calculate_sgpa([(4, 10), (2, 6), (3, 8)]) == grading.dec("8.44")
    assert grading.calculate_sgpa([]) is None and grading.calculate_sgpa([(0, 10)]) is None
    # weighted, not the plain average (8.0 and 6.0 -> 7.0 would be the plain average)
    assert grading.calculate_cgpa([(6, 8), (2, 6)]) == grading.dec("7.50")
    assert grading.calculate_cgpa([(0, 8)]) is None


# ---- mark entry -----------------------------------------------------------
def test_admin_creates_mark_and_backend_calculates(client, gx, store):
    r = mark(client, grade="A", grade_point=10, percentage=100, total_marks=100)  # extra fields rejected
    assert r.status_code == 422
    r = mark(client, remarks="ok")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == b["mark_id"] == M1
    assert (b["total_marks"], b["max_marks"], b["percentage"], b["grade"], b["grade_point"], b["status"]) == (
        80, 100, 80, "A", 10, "DRAFT")
    assert (b["student_uid"], b["course_id"], b["semester_id"], b["academic_session_id"], b["entered_by_uid"],
            b["exam_schedule_id"], b["practical_marks"]) == ("stu-1", "cs101", SEM, "2030-31", "admin-1", None, None)
    assert mark(client).status_code == 409
    assert any(a.get("action") == "mark.create" for a in store.audit)


def test_component_maximums(client, gx):
    ok = mark(client, internal_max_marks=30, external_max_marks=70, sid="S-001")
    assert ok.status_code == 201 and ok.json()["total_marks"] == 80
    assert mark(client, offering=OFF2, internal_max_marks=10, external_max_marks=70).status_code == 422  # internal 20 > 10
    assert mark(client, offering=OFF2, internal_max_marks=30, external_max_marks=60).status_code == 422  # sum != 100
    assert mark(client, offering=OFF2, internal_max_marks=30).status_code == 422  # partial maximums
    assert mark(client, offering=OFF2, practical_max_marks=5).status_code == 422  # max without marks


def test_single_component_and_validation(client, gx):
    r = mark(client, internal_marks=None, external_marks=None, practical_marks=45)
    assert r.status_code == 201 and r.json()["total_marks"] == 45 and r.json()["grade"] == "D"
    assert mark(client, offering=OFF2, internal_marks=None, external_marks=None).status_code == 422  # none
    assert mark(client, offering=OFF2, internal_marks=-1).status_code == 422
    assert mark(client, offering=OFF2, internal_marks=50, external_marks=51).status_code == 422  # total 101 > 100
    assert mark(client, offering=OFF2, internal_marks="x").status_code == 422
    assert mark(client, offering=OFF2, status="BAD").status_code == 422
    assert mark(client, offering=OFF2, uid="x").status_code == 422


def test_mark_uses_schedule_max_and_validates_schedule(client, gx):
    mk_sch(client, max_marks=50)
    assert mark(client, internal_marks=10, external_marks=41).status_code == 422  # 51 > 50
    r = mark(client, internal_marks=10, external_marks=30, exam_schedule_id=f"{EX}__{OFF}")
    assert r.status_code == 201 and r.json()["max_marks"] == 50 and r.json()["percentage"] == 80
    assert r.json()["exam_schedule_id"] == f"{EX}__{OFF}"
    assert mark(client, offering=OFF2, exam_schedule_id=f"{EX}__{OFF}").status_code == 400  # wrong offering
    assert mark(client, offering=OFF2, exam_schedule_id=f"{EX}__{OFF2}").status_code == 404  # none scheduled


def test_mark_relationship_validation(client, gx, store):
    assert mark(client, sid="NOPE").status_code == 404
    assert mark(client, offering="ghost").status_code == 404
    assert mark(client, **{"examination_id": "ghost"}).status_code == 404
    assert mark(client, sid="S-002", offering=OFF2).status_code == 400  # not enrolled in cs102
    client.patch("/api/v1/enrollments/s-001__" + OFF2, headers=AUTH, json={"status": "DROPPED"})
    assert mark(client, offering=OFF2).status_code == 400
    client.patch("/api/v1/students/s-002", headers=AUTH, json={"is_active": False})
    assert mark(client, sid="S-002").status_code == 400  # inactive student
    client.patch(f"/api/v1/examinations/{EX}", headers=AUTH, json={"status": "DRAFT"})
    assert mark(client).status_code == 400  # exam not open
    assert not [k for k in store.docs if k[0] == "marks"]


def test_examination_from_other_semester(client, gx):
    mk_sem(client, number=2, session="2031-32")
    other = "btcs__2031-32__2"
    r = client.post("/api/v1/examinations", headers=AUTH, json={
        "name": "Other", "examination_type": "INTERNAL", "semester_id": other, "start_date": "2031-09-01",
        "end_date": "2031-09-05", "status": "SCHEDULED"})
    assert r.status_code == 201, r.text
    assert mark(client, **{"examination_id": r.json()["id"]}).status_code == 400


def test_marks_without_scheme_have_no_grade(client, ex):
    r = mark(client)
    assert r.status_code == 201 and r.json()["grade"] is None and r.json()["percentage"] == 80
    set_scheme(client)
    assert client.post("/api/v1/grading-scheme/regrade", headers=AUTH, json={"semester_id": SEM}).json()["marks_updated"] == 1
    assert client.get(f"/api/v1/marks/{M1}", headers=AUTH).json()["grade"] == "A"
    assert client.post("/api/v1/grading-scheme/regrade", headers=AUTH, json={"semester_id": SEM}).json()["marks_updated"] == 0


# ---- authorization --------------------------------------------------------
def test_faculty_marks_access(client, identity, gx):
    login(identity, "fac-1", "FACULTY")
    assert mark(client).status_code == 201
    assert mark(client, offering=OFF2).status_code == 403  # unrelated offering
    assert mark(client, offering=OFF2, sid="S-001").status_code == 403
    assert mark(client, sid="S-002", status="FINAL").status_code == 403  # only admin verifies
    assert client.get(f"/api/v1/marks/{M1}", headers=AUTH).status_code == 200
    login(identity, "fac-2", "FACULTY")
    assert client.get(f"/api/v1/marks/{M1}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/marks", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/marks?course_offering_id={OFF}", headers=AUTH).json()["items"] == []
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"remarks": "x"}).status_code == 404


def test_student_cannot_write(client, identity, gx):
    mark(client)
    login(identity, "stu-1", "STUDENT")
    assert mark(client, offering=OFF2).status_code == 403
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"remarks": "x"}).status_code == 403
    assert client.post("/api/v1/results/generate", headers=AUTH, json={}).status_code == 403
    assert client.put("/api/v1/grading-scheme", headers=AUTH, json={"bands": BANDS}).status_code == 403


def test_unauthenticated_401(client):
    for c in (client.get("/api/v1/marks"), client.get("/api/v1/marks/me"), client.post("/api/v1/marks", json={}),
              client.patch("/api/v1/marks/x", json={}), client.get("/api/v1/results"),
              client.get("/api/v1/results/me"), client.get("/api/v1/results/me/sgpa"),
              client.get("/api/v1/results/me/cgpa"), client.post("/api/v1/results/generate", json={}),
              client.post("/api/v1/results/x/publish"), client.get("/api/v1/grading-scheme")):
        assert c.status_code == 401


# ---- update ---------------------------------------------------------------
def test_mark_update(client, identity, gx, store):
    mark(client)
    r = client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"external_marks": 30, "remarks": "rev"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["total_marks"], b["percentage"], b["grade"], b["grade_point"], b["remarks"]) == (50, 50, "C", 6, "rev")
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"internal_marks": None, "external_marks": None}).status_code == 422
    r = client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"internal_marks": None})
    assert r.status_code == 200 and r.json()["total_marks"] == 30 and r.json()["grade"] == "F"
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"external_marks": 101}).status_code == 422
    for field, value in (("student_id", "S-002"), ("course_offering_id", OFF2), ("examination_id", "x"),
                         ("semester_id", "x"), ("academic_session_id", "x"), ("grade", "A"), ("grade_point", 10),
                         ("percentage", 100), ("total_marks", 100)):
        assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={field: value}).status_code == 422, field
    assert client.patch("/api/v1/marks/none", headers=AUTH, json={"remarks": "x"}).status_code == 404
    assert any(a.get("action") == "mark.update" for a in store.audit)
    login(identity, "fac-1", "FACULTY")
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"external_marks": 70}).status_code == 200
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"status": "FINAL"}).status_code == 403


def test_faculty_cannot_edit_final(client, identity, gx):
    mark(client, status="FINAL")
    login(identity, "fac-1", "FACULTY")
    assert client.patch(f"/api/v1/marks/{M1}", headers=AUTH, json={"external_marks": 10}).status_code == 403


# ---- reads ----------------------------------------------------------------
def test_listing_filters_pagination(client, gx):
    mark(client)
    mark(client, offering=OFF2, internal_marks=5, external_marks=10, status="FINAL")
    mark(client, sid="S-002", internal_marks=30, external_marks=60, status="FINAL")
    assert len(client.get("/api/v1/marks", headers=AUTH).json()["items"]) == 3
    p1 = client.get("/api/v1/marks?limit=2", headers=AUTH).json()
    p2 = client.get(f"/api/v1/marks?limit=2&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None
    for q, n in (("student_id=S-001", 2), ("student_uid=stu-2", 1), ("course_id=cs102", 1),
                 (f"course_offering_id={OFF}", 2), (f"examination_id={EX}", 3), (f"semester_id={SEM}", 3),
                 ("academic_session_id=2030-31", 3), ("grade=A", 2), ("grade=F", 1), ("status=FINAL", 2),
                 ("status=DRAFT", 1)):
        assert len(client.get(f"/api/v1/marks?{q}", headers=AUTH).json()["items"]) == n, q
    item = client.get(f"/api/v1/marks/{M1}", headers=AUTH).json()
    assert item["course_code"] == "CS101" and item["examination_name"] == "End Sem"


def test_student_sees_only_own_final_marks(client, identity, gx):
    mark(client, status="FINAL")
    mark(client, offering=OFF2, status="DRAFT")
    mark(client, sid="S-002", status="FINAL")
    login(identity, "stu-1", "STUDENT")
    mine = client.get("/api/v1/marks/me", headers=AUTH).json()["items"]
    assert [m["id"] for m in mine] == [M1] and mine[0]["course_name"] == "Intro"
    assert [m["id"] for m in client.get("/api/v1/marks", headers=AUTH).json()["items"]] == [M1]
    assert client.get("/api/v1/marks?student_uid=stu-2", headers=AUTH).json()["items"] == []
    assert client.get("/api/v1/marks?status=DRAFT", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/marks/{M2}", headers=AUTH).status_code == 404  # own but draft
    assert client.get(f"/api/v1/marks/s-002__{OFF}__{EX}", headers=AUTH).status_code == 404  # someone else's
    login(identity, "fac-1", "FACULTY")
    assert client.get("/api/v1/marks/me", headers=AUTH).status_code == 403


# ---- results / SGPA / CGPA ------------------------------------------------
def gen(client, sid="S-001", sem=SEM, **kw):
    return client.post("/api/v1/results/generate", headers=AUTH, json={"student_id": sid, "semester_id": sem, **kw})


def final_marks(client):
    # cs101: 4 credits, 80% -> A(10); cs102 set to 2 credits: 55% -> C(6)
    client.patch("/api/v1/courses/cs102", headers=AUTH, json={"credits": 2})
    assert mark(client, status="FINAL").status_code == 201
    assert mark(client, offering=OFF2, internal_marks=15, external_marks=40, status="FINAL").status_code == 201


def test_result_requires_scheme(client, ex):
    assert gen(client).status_code == 409


def test_semester_result_and_weighted_sgpa(client, gx, store):
    final_marks(client)
    r = gen(client)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == b["result_id"] == R1
    assert (b["status"], b["published"], b["total_credits"], b["earned_credits"], b["sgpa"]) == (
        "COMPLETE", False, 6, 6, 8.67)  # (4*10 + 2*6) / 6
    assert (b["total_marks"], b["max_marks"], b["percentage"]) == (135, 200, 67.5)
    assert (b["program_id"], b["academic_session_id"], b["student_uid"]) == ("btcs", "2030-31", "stu-1")
    by = {c["course_id"]: c for c in b["courses"]}
    assert (by["cs101"]["credits"], by["cs101"]["grade"], by["cs101"]["grade_point"]) == (4, "A", 10)
    assert (by["cs102"]["credits"], by["cs102"]["grade"], by["cs102"]["status"]) == (2, "C", "GRADED")
    assert any(a.get("action") == "result.generate" for a in store.audit)
    assert gen(client).status_code == 201  # idempotent regeneration
    assert len([k for k in store.docs if k[0] == "results"]) == 1
    assert gen(client, sid="NOPE").status_code == 404
    assert gen(client, sem="ghost").status_code == 404
    assert gen(client, examination_type="QUIZ").status_code == 422


def test_incomplete_missing_and_draft_marks(client, gx):
    mark(client, status="FINAL")
    mark(client, offering=OFF2, status="DRAFT")  # draft does not count
    b = gen(client).json()
    assert b["status"] == "INCOMPLETE" and b["sgpa"] is None and b["total_credits"] == 8
    assert {c["course_id"]: c["status"] for c in b["courses"]} == {"cs101": "GRADED", "cs102": "MISSING"}
    assert b["earned_credits"] == 4
    client.patch("/api/v1/courses/cs102", headers=AUTH, json={"credits": 2})
    publish = client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    assert publish.status_code == 409  # cannot publish an incomplete result
    # nothing graded at all
    b = gen(client, sid="S-002").json()
    assert b["status"] == "INCOMPLETE" and b["sgpa"] is None and b["total_marks"] is None and b["percentage"] is None


def test_earned_credits_exclude_failed_courses(client, gx):
    client.patch("/api/v1/courses/cs102", headers=AUTH, json={"credits": 2})
    mark(client, status="FINAL")
    mark(client, offering=OFF2, internal_marks=5, external_marks=30, status="FINAL")  # 35% -> F
    b = gen(client).json()
    assert (b["status"], b["total_credits"], b["earned_credits"], b["sgpa"]) == ("COMPLETE", 6, 4, 6.67)  # 40/6


def test_only_enrolled_active_courses_count(client, gx):
    client.patch("/api/v1/enrollments/s-001__" + OFF2, headers=AUTH, json={"status": "DROPPED"})
    mark(client, status="FINAL")
    b = gen(client).json()
    assert [c["course_id"] for c in b["courses"]] == ["cs101"] and b["status"] == "COMPLETE" and b["sgpa"] == 10


def test_result_regenerated_on_mark_change_and_unpublishes(client, identity, gx):
    final_marks(client)
    gen(client)
    assert client.post(f"/api/v1/results/{R1}/publish", headers=AUTH).status_code == 200
    assert client.patch(f"/api/v1/marks/{M2}", headers=AUTH, json={"external_marks": 50}).status_code == 200
    row = client.get(f"/api/v1/results/{R1}", headers=AUTH).json()
    assert row["sgpa"] == 9.33 and row["published"] is False and row["published_at"] is None  # (40+2*8)/6 -> 9.33
    assert client.patch(f"/api/v1/marks/{M2}", headers=AUTH, json={"remarks": "n"}).status_code == 200
    assert client.get(f"/api/v1/results/{R1}", headers=AUTH).json()["sgpa"] == 9.33


def test_publication_workflow_and_student_visibility(client, identity, gx, store):
    final_marks(client)
    gen(client)
    login(identity, "stu-1", "STUDENT")
    assert client.get("/api/v1/results/me", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/results/{R1}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/results/me/sgpa", headers=AUTH).json()["items"] == []
    assert client.get("/api/v1/results?published=false", headers=AUTH).json()["items"] == []
    assert client.post(f"/api/v1/results/{R1}/publish", headers=AUTH).status_code == 403
    as_role(identity, "FACULTY")
    assert client.post(f"/api/v1/results/{R1}/publish", headers=AUTH).status_code == 403
    as_role(identity, "ADMIN")
    p = client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    assert p.status_code == 200 and p.json()["published"] is True and p.json()["published_by_uid"] == "u-ADMIN"
    assert p.json()["published_at"]
    assert any(a.get("action") == "result.publish" for a in store.audit)
    login(identity, "stu-1", "STUDENT")
    assert len(client.get("/api/v1/results/me", headers=AUTH).json()["items"]) == 1
    assert client.get(f"/api/v1/results/{R1}", headers=AUTH).json()["sgpa"] == 8.67
    as_role(identity, "ADMIN")
    u = client.post(f"/api/v1/results/{R1}/unpublish", headers=AUTH)
    assert u.json()["published"] is False and u.json()["published_at"] is None
    assert any(a.get("action") == "result.unpublish" for a in store.audit)
    assert client.post("/api/v1/results/none/publish", headers=AUTH).status_code == 404


def test_student_cannot_see_other_students_results(client, identity, gx):
    final_marks(client)
    mark(client, sid="S-002", status="FINAL")
    gen(client)
    gen(client, sid="S-002")
    client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    client.post(f"/api/v1/results/s-002__{SEM}/publish", headers=AUTH)  # s-002 only has cs101 -> complete
    login(identity, "stu-2", "STUDENT")
    assert [r["student_id"] for r in client.get("/api/v1/results/me", headers=AUTH).json()["items"]] == ["S-002"]
    assert [r["student_id"] for r in client.get("/api/v1/results", headers=AUTH).json()["items"]] == ["S-002"]
    assert client.get(f"/api/v1/results/{R1}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/results/sgpa?student_id=S-001", headers=AUTH).status_code == 403
    assert client.get("/api/v1/results/cgpa?student_id=S-001", headers=AUTH).status_code == 403


def test_admin_result_listing_and_filters(client, gx):
    final_marks(client)
    mark(client, sid="S-002", status="FINAL")
    gen(client)
    gen(client, sid="S-002")
    client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    for q, n in (("", 2), ("student_id=S-001", 1), (f"semester_id={SEM}", 2), ("academic_session_id=2030-31", 2),
                 ("program_id=btcs", 2), ("program_id=zz", 0), ("status=COMPLETE", 2), ("status=INCOMPLETE", 0),
                 ("published=true", 1), ("published=false", 1)):
        assert len(client.get(f"/api/v1/results?{q}", headers=AUTH).json()["items"]) == n, q
    p1 = client.get("/api/v1/results?limit=1", headers=AUTH).json()
    p2 = client.get(f"/api/v1/results?limit=1&cursor={p1['next_cursor']}", headers=AUTH).json()
    assert p1["items"][0]["id"] != p2["items"][0]["id"] and p2["next_cursor"] is None


def test_faculty_result_scope(client, identity, gx):
    final_marks(client)
    gen(client)
    login(identity, "fac-1", "FACULTY")
    items = client.get("/api/v1/results", headers=AUTH).json()["items"]
    assert len(items) == 1 and [c["course_id"] for c in items[0]["courses"]] == ["cs101"]
    assert items[0]["sgpa"] is None and items[0]["total_credits"] is None  # no aggregates for faculty
    assert client.get(f"/api/v1/results/{R1}", headers=AUTH).json()["sgpa"] is None
    assert client.get("/api/v1/results/me", headers=AUTH).status_code == 403
    login(identity, "fac-9", "FACULTY")
    assert client.get("/api/v1/results", headers=AUTH).json()["items"] == []
    assert client.get(f"/api/v1/results/{R1}", headers=AUTH).status_code == 404
    assert client.get("/api/v1/results/sgpa?student_id=S-001", headers=AUTH).status_code == 403


def test_sgpa_endpoints(client, identity, gx):
    final_marks(client)
    gen(client)
    a = client.get("/api/v1/results/sgpa?student_id=S-001", headers=AUTH).json()["items"]
    assert len(a) == 1 and (a[0]["sgpa"], a[0]["total_credits"], a[0]["earned_credits"], a[0]["status"],
                           a[0]["semester_id"], a[0]["student_id"], a[0]["academic_session_id"]) == (
        8.67, 6, 6, "COMPLETE", SEM, "S-001", "2030-31")
    assert client.get("/api/v1/results/sgpa?student_id=NOPE", headers=AUTH).status_code == 404
    client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    login(identity, "stu-1", "STUDENT")
    assert client.get("/api/v1/results/me/sgpa", headers=AUTH).json()["items"][0]["sgpa"] == 8.67
    assert client.get("/api/v1/results/me/sgpa?semester_id=other", headers=AUTH).json()["items"] == []


def test_zero_credits_and_no_data(client, identity, gx, store):
    # student with no enrollments counted -> zero credits, no SGPA, no division by zero
    client.patch("/api/v1/enrollments/s-002__" + OFF, headers=AUTH, json={"status": "DROPPED"})
    b = gen(client, sid="S-002").json()
    assert (b["total_credits"], b["sgpa"], b["status"], b["courses"]) == (0, None, "INCOMPLETE", [])
    c = client.get("/api/v1/results/cgpa?student_id=S-002", headers=AUTH).json()
    assert (c["cgpa"], c["status"], c["total_credits"], c["semesters_considered"]) == (None, "NO_DATA", 0, [])
    login(identity, "stu-2", "STUDENT")
    c = client.get("/api/v1/results/me/cgpa", headers=AUTH).json()
    assert c["cgpa"] is None and c["status"] == "NO_DATA" and c["student_id"] == "S-002"


def _second_semester_result(client, store, credits, sgpa_pct_marks):
    """Hand-built semester-2 result document for S-001 (derived values are verified elsewhere)."""
    store.docs[("results", "s-001__btcs__2031-32__2")] = {
        "result_id": "s-001__btcs__2031-32__2", "student_uid": "stu-1", "student_id": "S-001",
        "academic_session_id": "2031-32", "semester_id": "btcs__2031-32__2", "program_id": "btcs",
        "courses": [], "total_credits": credits, "earned_credits": credits, "sgpa": sgpa_pct_marks,
        "status": "COMPLETE", "published": True,
    }


def test_cgpa_weighted_across_semesters(client, identity, gx, store):
    final_marks(client)
    gen(client)
    client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    _second_semester_result(client, store, 2, 6.0)  # 6 credits @ 8.67 and 2 credits @ 6.0
    login(identity, "stu-1", "STUDENT")
    c = client.get("/api/v1/results/me/cgpa", headers=AUTH).json()
    assert c["cgpa"] == 8.0  # (6*8.67 + 2*6.0) / 8 = 8.0025 -> weighted, plain mean would be 7.34
    assert c["status"] == "COMPLETE" and c["total_credits"] == 8 and len(c["semesters_considered"]) == 2
    assert c["student_id"] == "S-001" and c["semesters_excluded"] == 0


def test_cgpa_excludes_incomplete_and_unpublished(client, identity, gx, store):
    final_marks(client)
    gen(client)  # complete but NOT published
    _second_semester_result(client, store, 2, 6.0)
    login(identity, "stu-1", "STUDENT")
    c = client.get("/api/v1/results/me/cgpa", headers=AUTH).json()
    assert c["cgpa"] == 6.0 and c["status"] == "PARTIAL" and c["semesters_excluded"] == 1
    as_role(identity, "ADMIN")
    c = client.get("/api/v1/results/cgpa?student_id=S-001", headers=AUTH).json()  # admin sees unpublished
    assert c["status"] == "COMPLETE" and c["cgpa"] == 8.0
    store.docs[("results", "s-001__btcs__2031-32__2")]["status"] = "INCOMPLETE"
    store.docs[("results", "s-001__btcs__2031-32__2")]["sgpa"] = None
    c = client.get("/api/v1/results/cgpa?student_id=S-001", headers=AUTH).json()
    assert c["status"] == "PARTIAL" and c["cgpa"] == 8.67 and len(c["semesters_considered"]) == 1


def test_regrade_with_replaced_scheme_updates_results(client, gx):
    final_marks(client)
    gen(client)
    client.post(f"/api/v1/results/{R1}/publish", headers=AUTH)
    harsher = [dict(b) for b in BANDS]
    harsher[3]["grade_point"] = 7
    harsher[4]["grade_point"] = 9
    assert set_scheme(client, harsher).status_code == 200
    r = client.post("/api/v1/grading-scheme/regrade", headers=AUTH, json={"semester_id": SEM}).json()
    assert r == {"marks_updated": 1, "results_regenerated": 1, "results_unpublished": 1}
    row = client.get(f"/api/v1/results/{R1}", headers=AUTH).json()
    assert row["sgpa"] == 8.0 and row["published"] is False  # (4*9 + 2*6) / 6
