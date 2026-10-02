import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists

from app.core import security
from app.main import app
from app.schemas.user import UserProfile, UserRole
from app.services import academic_common, audit

AUTH = {"Authorization": "Bearer good-token"}


def _match(actual, op, value):
    if op == "==":
        return actual == value
    if op == "in":
        return actual in value
    if actual is None:
        return False
    return actual >= value if op == ">=" else actual <= value


class Snap:
    def __init__(self, store, path, data):
        self.id, self.reference, self._d = path[1], Ref(store, path), data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._d) if self._d is not None else None


class Ref:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def get(self):
        return Snap(self.store, self.path, self.store.docs.get(self.path))


class Query:
    def __init__(self, store, coll, filters=(), after=None, lim=None):
        self.store, self.coll, self.filters, self.after, self.lim = store, coll, tuple(filters), after, lim

    def where(self, filter):
        return Query(self.store, self.coll, self.filters + ((filter.field_path, filter.value, filter.op_string),), self.after, self.lim)

    def order_by(self, _):
        return self

    def start_after(self, snap):
        return Query(self.store, self.coll, self.filters, snap.id, self.lim)

    def limit(self, n):
        return Query(self.store, self.coll, self.filters, self.after, n)

    def count(self):
        n = len(list(self.stream()))
        return type("Agg", (), {"get": lambda _s: [[type("R", (), {"value": n})()]]})()

    def stream(self):
        out = []
        for (c, i), d in sorted(self.store.docs.items()):
            if c != self.coll or (self.after and i <= self.after):
                continue
            if all(_match(d.get(f), op, v) for f, v, op in self.filters):
                out.append(Snap(self.store, (c, i), d))
        return iter(out[: self.lim] if self.lim else out)


class Collection(Query):
    def __init__(self, store, coll):
        super().__init__(store, coll)

    def document(self, i):
        return Ref(self.store, (self.coll, i))

    def add(self, data):
        self.store.audit.append(data)
        self.store.docs[("audit_logs", f"a{len(self.store.audit):05d}")] = dict(data)


class Batch:
    def __init__(self, store):
        self.store, self.ops = store, []

    def create(self, ref, data):
        self.ops.append(("create", ref.path, data))

    def update(self, ref, data):
        self.ops.append(("update", ref.path, data))

    def commit(self):
        for op, path, _ in self.ops:
            if op == "create" and path in self.store.docs:
                raise AlreadyExists("exists")
        for op, path, data in self.ops:
            if op == "create":
                self.store.docs[path] = dict(data)
            else:
                self.store.docs[path].update(data)


class FakeStore:
    def __init__(self):
        self.docs, self.audit = {}, []

    def collection(self, name):
        return Collection(self, name)

    def batch(self):
        return Batch(self)


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    for mod in (academic_common, audit):  # all Firestore access goes through these two
        monkeypatch.setattr(mod, "get_firestore_client", lambda: s)
    return s


@pytest.fixture
def identity(monkeypatch):
    state = {"claims": {"uid": "admin-1", "role": "ADMIN"}, "profile": UserProfile(uid="admin-1", role=UserRole.ADMIN)}

    def fake_verify(token):
        if token != "good-token":
            raise ValueError("bad")
        return state["claims"]

    monkeypatch.setattr(security, "verify_id_token", fake_verify)
    monkeypatch.setattr(security, "get_user_profile", lambda uid: state["profile"])
    return state


def as_role(identity, role):
    identity["claims"] = {"uid": "u-" + role, "role": role}
    identity["profile"] = UserProfile(uid="u-" + role, role=UserRole(role))


@pytest.fixture
def client(store, identity):
    return TestClient(app)


def mk_dept(client, code="CSE", name="Computer Science"):
    return client.post("/api/v1/departments", headers=AUTH, json={"name": name, "code": code})


def mk_prog(client, dept="cse", code="BTCS", **kw):
    body = {"name": "BTech CS", "code": code, "department_id": dept, "degree_type": "btech",
            "duration_years": 4, "total_semesters": 8, **kw}
    return client.post("/api/v1/programs", headers=AUTH, json=body)


def mk_session(client, name="2030-31", start="2030-07-01", end="2031-06-30", **kw):
    return client.post("/api/v1/academic-sessions", headers=AUTH,
                       json={"name": name, "start_date": start, "end_date": end, **kw})


def mk_sem(client, program="btcs", session="2030-31", number=1, **kw):
    body = {"program_id": program, "academic_session_id": session, "semester_number": number,
            "start_date": "2030-07-01", "end_date": "2030-12-31", **kw}
    return client.post("/api/v1/semesters", headers=AUTH, json=body)


# ---- auth / roles ---------------------------------------------------------
@pytest.mark.parametrize("path", ["departments", "programs", "academic-sessions", "semesters"])
def test_unauthenticated_401(client, path):
    assert client.get(f"/api/v1/{path}").status_code == 401
    assert client.post(f"/api/v1/{path}", json={}).status_code == 401


@pytest.mark.parametrize("role", ["STUDENT", "FACULTY"])
def test_non_admin_mutation_403(client, identity, store, role):
    mk_dept(client)
    as_role(identity, role)
    assert mk_dept(client, code="ECE").status_code == 403
    assert mk_prog(client).status_code == 403
    assert mk_session(client).status_code == 403
    assert mk_sem(client).status_code == 403
    assert client.patch("/api/v1/departments/cse", headers=AUTH, json={"name": "X"}).status_code == 403
    assert client.patch("/api/v1/semesters/x", headers=AUTH, json={"name": "X"}).status_code == 403
    assert ("departments", "ece") not in store.docs


def test_user_without_role_cannot_read(client, identity):
    identity["claims"], identity["profile"] = {"uid": "n"}, None
    assert client.get("/api/v1/departments", headers=AUTH).status_code == 403


def test_inactive_user_blocked(client, identity):
    identity["profile"] = UserProfile(uid="admin-1", role=UserRole.ADMIN, is_active=False)
    assert client.get("/api/v1/departments", headers=AUTH).status_code == 403


def test_students_see_only_active(client, identity):
    mk_dept(client, "CSE")
    mk_dept(client, "ECE")
    client.patch("/api/v1/departments/ece", headers=AUTH, json={"is_active": False})
    assert len(client.get("/api/v1/departments", headers=AUTH).json()["items"]) == 2
    as_role(identity, "STUDENT")
    r = client.get("/api/v1/departments?is_active=false", headers=AUTH)
    assert [d["code"] for d in r.json()["items"]] == ["CSE"]
    assert client.get("/api/v1/departments/ece", headers=AUTH).status_code == 404
    assert client.get("/api/v1/departments/cse", headers=AUTH).status_code == 200


# ---- departments ----------------------------------------------------------
def test_department_create_read_update(client, store):
    r = mk_dept(client, code="cse")
    assert r.status_code == 201
    d = r.json()
    assert d["id"] == "cse" and d["code"] == "CSE" and d["is_active"] is True and d["created_at"]
    assert client.get("/api/v1/departments/cse", headers=AUTH).json()["name"] == "Computer Science"
    u = client.patch("/api/v1/departments/cse", headers=AUTH, json={"name": "CS&E", "description": "d"})
    assert u.status_code == 200 and u.json()["name"] == "CS&E"
    assert store.docs[("departments", "cse")]["name"] == "CS&E"
    assert store.audit and "password" not in str(store.audit)


def test_department_duplicate_code_409(client):
    assert mk_dept(client, "CSE").status_code == 201
    assert mk_dept(client, "cse", name="Other").status_code == 409


def test_department_missing_404_and_bad_input_422(client):
    assert client.get("/api/v1/departments/nope", headers=AUTH).status_code == 404
    assert client.patch("/api/v1/departments/nope", headers=AUTH, json={"name": "x"}).status_code == 404
    assert client.post("/api/v1/departments", headers=AUTH, json={"name": "x"}).status_code == 422
    assert client.patch("/api/v1/departments/cse", headers=AUTH, json={"code": "NEW"}).status_code == 422


def test_cannot_deactivate_department_with_active_programs(client):
    mk_dept(client)
    mk_prog(client)
    assert client.patch("/api/v1/departments/cse", headers=AUTH, json={"is_active": False}).status_code == 409
    client.patch("/api/v1/programs/btcs", headers=AUTH, json={"is_active": False})
    assert client.patch("/api/v1/departments/cse", headers=AUTH, json={"is_active": False}).status_code == 200


# ---- programs -------------------------------------------------------------
def test_program_create(client):
    mk_dept(client)
    r = mk_prog(client)
    assert r.status_code == 201
    assert r.json()["degree_type"] == "BTECH" and r.json()["department_id"] == "cse"


def test_program_invalid_department_404(client):
    assert mk_prog(client, dept="ghost").status_code == 404


def test_program_inactive_department_400(client):
    mk_dept(client)
    client.patch("/api/v1/departments/cse", headers=AUTH, json={"is_active": False})
    assert mk_prog(client).status_code == 400


def test_program_duplicate_code_409(client):
    mk_dept(client)
    assert mk_prog(client).status_code == 201
    assert mk_prog(client).status_code == 409


@pytest.mark.parametrize("patch", [{"duration_years": 0}, {"total_semesters": -1}, {"duration_years": "x"}])
def test_program_invalid_numbers_422(client, patch):
    mk_dept(client)
    assert mk_prog(client, **patch).status_code == 422


def test_program_filtering(client):
    mk_dept(client, "CSE")
    mk_dept(client, "ECE", name="Electronics")
    mk_prog(client, "cse", "P1")
    mk_prog(client, "cse", "P2")
    mk_prog(client, "ece", "P3")
    client.patch("/api/v1/programs/p2", headers=AUTH, json={"is_active": False})
    ids = lambda q: sorted(p["id"] for p in client.get(f"/api/v1/programs{q}", headers=AUTH).json()["items"])
    assert ids("") == ["p1", "p2", "p3"]
    assert ids("?department_id=cse") == ["p1", "p2"]
    assert ids("?department_id=cse&is_active=true") == ["p1"]
    assert ids("?is_active=false") == ["p2"]


def test_program_pagination(client):
    mk_dept(client)
    for c in ("P1", "P2", "P3"):
        mk_prog(client, code=c)
    r1 = client.get("/api/v1/programs?limit=2", headers=AUTH).json()
    assert len(r1["items"]) == 2 and r1["next_cursor"]
    r2 = client.get(f"/api/v1/programs?limit=2&cursor={r1['next_cursor']}", headers=AUTH).json()
    assert [p["id"] for p in r2["items"]] == ["p3"] and r2["next_cursor"] is None


# ---- sessions -------------------------------------------------------------
def test_session_create_and_get(client):
    r = mk_session(client)
    assert r.status_code == 201 and r.json()["id"] == "2030-31"
    assert client.get("/api/v1/academic-sessions/2030-31", headers=AUTH).json()["start_date"] == "2030-07-01"
    assert mk_session(client).status_code == 409


@pytest.mark.parametrize("start,end", [("2031-01-01", "2030-01-01"), ("2030-01-01", "2030-01-01")])
def test_session_invalid_dates_422(client, start, end):
    assert mk_session(client, start=start, end=end).status_code == 422


def test_session_update_invalid_range_422(client):
    mk_session(client)
    r = client.patch("/api/v1/academic-sessions/2030-31", headers=AUTH, json={"end_date": "2030-01-01"})
    assert r.status_code == 422


def test_only_one_current_session(client):
    mk_session(client, "2030-31", is_current=True)
    mk_session(client, "2031-32", "2031-07-01", "2032-06-30", is_current=True)
    cur = client.get("/api/v1/academic-sessions?is_current=true", headers=AUTH).json()["items"]
    assert [s["id"] for s in cur] == ["2031-32"]
    r = client.patch("/api/v1/academic-sessions/2030-31", headers=AUTH, json={"is_current": True})
    assert r.status_code == 200
    cur = client.get("/api/v1/academic-sessions?is_current=true", headers=AUTH).json()["items"]
    assert [s["id"] for s in cur] == ["2030-31"]


def test_deactivate_session_clears_current_and_blocks_current(client):
    mk_session(client, is_current=True)
    r = client.patch("/api/v1/academic-sessions/2030-31", headers=AUTH, json={"is_active": False})
    assert r.json()["is_current"] is False and r.json()["is_active"] is False
    r = client.patch("/api/v1/academic-sessions/2030-31", headers=AUTH, json={"is_current": True})
    assert r.status_code == 400


# ---- semesters ------------------------------------------------------------
@pytest.fixture
def hierarchy(client):
    mk_dept(client)
    mk_prog(client)
    mk_session(client)
    mk_session(client, "2031-32", "2031-07-01", "2032-06-30")


def test_semester_create(client, hierarchy):
    r = mk_sem(client)
    assert r.status_code == 201
    b = r.json()
    assert b["id"] == "btcs__2030-31__1" and b["name"] == "Semester 1" and b["is_current"] is False


def test_semester_invalid_program_404(client, hierarchy):
    assert mk_sem(client, program="ghost").status_code == 404


def test_semester_invalid_session_404(client, hierarchy):
    assert mk_sem(client, session="ghost").status_code == 404


def test_semester_duplicate_409(client, hierarchy):
    assert mk_sem(client).status_code == 201
    assert mk_sem(client).status_code == 409
    assert mk_sem(client, number=2).status_code == 201
    assert mk_sem(client, session="2031-32").status_code == 201


def test_semester_validation(client, hierarchy):
    assert mk_sem(client, number=0).status_code == 422
    assert mk_sem(client, start_date="2031-01-01", end_date="2030-01-01").status_code == 422
    assert mk_sem(client, number=9).status_code == 400  # exceeds total_semesters=8


def test_semester_filtering(client, hierarchy):
    mk_sem(client, number=1)
    mk_sem(client, number=2, is_current=True)
    mk_sem(client, session="2031-32", number=1)
    ids = lambda q: sorted(s["semester_number"] for s in client.get(f"/api/v1/semesters{q}", headers=AUTH).json()["items"])
    assert ids("") == [1, 1, 2]
    assert ids("?program_id=btcs&academic_session_id=2030-31") == [1, 2]
    assert ids("?semester_number=1") == [1, 1]
    assert ids("?is_current=true") == [2]
    assert ids("?academic_session_id=2031-32&is_active=true") == [1]


def test_only_one_current_semester_per_program(client, hierarchy):
    mk_sem(client, number=1, is_current=True)
    mk_sem(client, number=2, is_current=True)
    cur = client.get("/api/v1/semesters?is_current=true", headers=AUTH).json()["items"]
    assert [s["semester_number"] for s in cur] == [2]


def test_semester_update_and_immutable_fields(client, hierarchy):
    mk_sem(client)
    sid = "btcs__2030-31__1"
    r = client.patch(f"/api/v1/semesters/{sid}", headers=AUTH, json={"name": "Autumn"})
    assert r.status_code == 200 and r.json()["name"] == "Autumn"
    assert client.patch(f"/api/v1/semesters/{sid}", headers=AUTH, json={"program_id": "x"}).status_code == 422
    r = client.patch(f"/api/v1/semesters/{sid}", headers=AUTH, json={"end_date": "2030-01-01"})
    assert r.status_code == 422


def test_program_with_active_semesters_cannot_be_deactivated(client, hierarchy):
    mk_sem(client)
    assert client.patch("/api/v1/programs/btcs", headers=AUTH, json={"is_active": False}).status_code == 409
    assert client.patch("/api/v1/programs/btcs", headers=AUTH, json={"total_semesters": 0}).status_code == 422


def test_internal_errors_not_leaked(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(academic_common, "fetch", boom)
    r = client.get("/api/v1/departments/cse", headers=AUTH)
    assert r.status_code == 500 and "secret-internal-detail" not in r.text


