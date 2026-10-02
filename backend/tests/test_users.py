import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.errors import UserAlreadyExistsError
from app.main import app
from app.schemas.user import UserProfile, UserRole
from app.services import users as user_service

ADMIN_UID = "admin-1"
AUTH = {"Authorization": "Bearer good-token"}
PASSWORD = "Sup3rSecretPw"

VALID = {
    "email": "New.Student@Example.com",
    "password": PASSWORD,
    "display_name": "New Student",
    "role": "STUDENT",
    "student_id": "S-001",
}


class FakeFirestore:
    """Minimal in-memory Firestore double recording every write."""

    def __init__(self):
        self.docs = {}
        self.writes = []

    def collection(self, name):
        return FakeCollection(self, name)


class FakeCollection:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def document(self, uid):
        return FakeDoc(self.db, self.name, uid)

    def add(self, data):
        self.db.writes.append((self.name, None, data))


class FakeDoc:
    def __init__(self, db, coll, uid):
        self.db, self.coll, self.uid = db, coll, uid

    def create(self, data):
        self.db.writes.append((self.coll, self.uid, data))
        self.db.docs[(self.coll, self.uid)] = data


@pytest.fixture
def env(monkeypatch):
    s = {
        "claims": {"uid": ADMIN_UID, "email": "admin@example.test", "role": "ADMIN"},
        "profile": UserProfile(uid=ADMIN_UID, role=UserRole.ADMIN),
        "db": FakeFirestore(),
        "created": [],
        "deleted": [],
        "claims_set": [],
        "existing": set(),
        "fail_firestore": False,
    }

    def fake_verify(token):
        if token != "good-token":
            raise ValueError("bad")
        return s["claims"]

    def fake_create(email, password, display_name):
        if email in s["existing"]:
            raise UserAlreadyExistsError("dup")
        s["created"].append((email, password))
        return "new-uid"

    monkeypatch.setattr(security, "verify_id_token", fake_verify)
    monkeypatch.setattr(security, "get_user_profile", lambda uid: s["profile"])
    monkeypatch.setattr(user_service, "create_auth_user", fake_create)
    monkeypatch.setattr(user_service, "delete_auth_user", lambda uid: s["deleted"].append(uid))
    monkeypatch.setattr(user_service, "set_auth_role_claim", lambda uid, r: s["claims_set"].append((uid, r)))

    def fake_fs():
        if s["fail_firestore"]:
            raise RuntimeError("firestore down password=" + PASSWORD)
        return s["db"]

    monkeypatch.setattr(user_service, "get_firestore_client", fake_fs)
    from app.services import audit

    monkeypatch.setattr(audit, "get_firestore_client", fake_fs)
    return s


@pytest.fixture
def client():
    return TestClient(app)


def test_unauthenticated_401(client, env):
    assert client.post("/api/v1/users", json=VALID).status_code == 401
    assert client.get("/api/v1/users").status_code == 401


@pytest.mark.parametrize("role", ["STUDENT", "FACULTY"])
def test_non_admin_cannot_create(client, env, role):
    env["claims"] = {"uid": "u2", "role": role}
    env["profile"] = None
    assert client.post("/api/v1/users", headers=AUTH, json=VALID).status_code == 403
    assert env["created"] == []


def test_non_admin_cannot_list_or_read(client, env):
    env["claims"] = {"uid": "u2", "role": "STUDENT"}
    assert client.get("/api/v1/users", headers=AUTH).status_code == 403
    assert client.get("/api/v1/users/x", headers=AUTH).status_code == 403


def test_forged_body_role_does_not_grant_admin(client, env):
    env["claims"] = {"uid": "u2", "role": "STUDENT"}
    r = client.post("/api/v1/users", headers={**AUTH, "X-Role": "ADMIN"}, json={**VALID, "admin": True})
    assert r.status_code == 403


def test_admin_creates_user_and_profile(client, env):
    r = client.post("/api/v1/users", headers=AUTH, json=VALID)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["uid"] == "new-uid"
    assert body["email"] == "new.student@example.com"
    assert body["role"] == "STUDENT"
    assert body["is_active"] is True
    assert body["created_at"] and body["updated_at"]
    assert env["claims_set"] == [("new-uid", "STUDENT")]
    doc = env["db"].docs[("users", "new-uid")]
    assert doc["uid"] == "new-uid" and doc["role"] == UserRole.STUDENT


def test_password_never_returned(client, env):
    r = client.post("/api/v1/users", headers=AUTH, json=VALID)
    assert PASSWORD not in r.text
    assert "password" not in r.json()


def test_password_never_written_to_firestore(client, env):
    client.post("/api/v1/users", headers=AUTH, json=VALID)
    assert env["db"].writes
    assert PASSWORD not in repr(env["db"].writes)
    for _, _, data in env["db"].writes:
        assert "password" not in data
    # password only went to the Auth layer
    assert env["created"] == [("new.student@example.com", PASSWORD)]


def test_duplicate_email_409(client, env):
    env["existing"].add("new.student@example.com")
    r = client.post("/api/v1/users", headers=AUTH, json=VALID)
    assert r.status_code == 409
    assert env["db"].writes == []


def test_invalid_role_422(client, env):
    r = client.post("/api/v1/users", headers=AUTH, json={**VALID, "role": "SUPERUSER"})
    assert r.status_code == 422
    assert PASSWORD not in r.text


@pytest.mark.parametrize("missing", ["email", "password", "display_name", "role"])
def test_missing_required_fields_422(client, env, missing):
    body = {k: v for k, v in VALID.items() if k != missing}
    assert client.post("/api/v1/users", headers=AUTH, json=body).status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"email": "not-an-email"},
        {"password": "short"},
        {"password": "alllowercase123"},
        {"student_id": "bad id!"},
        {"student_id": None},  # STUDENT requires student_id
    ],
)
def test_invalid_values_422_and_no_password_echo(client, env, patch):
    r = client.post("/api/v1/users", headers=AUTH, json={**VALID, **patch})
    assert r.status_code == 422
    assert PASSWORD not in r.text
    assert "alllowercase123" not in r.text


def test_firestore_failure_rolls_back_auth_user(client, env):
    env["db"] = FakeFirestore()
    calls = {"n": 0}
    real = user_service.get_firestore_client

    def flaky():
        calls["n"] += 1
        raise RuntimeError("boom " + PASSWORD)

    user_service.get_firestore_client = flaky
    try:
        r = client.post("/api/v1/users", headers=AUTH, json=VALID)
    finally:
        user_service.get_firestore_client = real
    assert r.status_code == 500
    assert env["deleted"] == ["new-uid"]
    assert PASSWORD not in r.text and "boom" not in r.text


def test_inactive_admin_blocked(client, env):
    env["profile"] = UserProfile(uid=ADMIN_UID, role=UserRole.ADMIN, is_active=False)
    assert client.post("/api/v1/users", headers=AUTH, json=VALID).status_code == 403
    assert client.get("/api/v1/auth/me", headers=AUTH).status_code == 403
    assert client.get("/api/v1/users/me", headers=AUTH).status_code == 403


def test_auth_me_active_admin(client, env):
    r = client.get("/api/v1/auth/me", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"
    assert r.json()["profile_provisioned"] is True


def test_auth_me_without_profile(client, env):
    env["profile"] = None
    env["claims"] = {"uid": "x"}
    r = client.get("/api/v1/auth/me", headers=AUTH)
    assert r.status_code == 200 and r.json()["profile_provisioned"] is False
    assert client.get("/api/v1/users/me", headers=AUTH).status_code == 404


def test_users_me_returns_profile(client, env):
    r = client.get("/api/v1/users/me", headers=AUTH)
    assert r.status_code == 200 and r.json()["uid"] == ADMIN_UID


def test_get_user_by_uid_404_and_200(client, env, monkeypatch):
    monkeypatch.setattr(user_service, "get_user_profile", lambda uid: None)
    assert client.get("/api/v1/users/nope", headers=AUTH).status_code == 404
    monkeypatch.setattr(user_service, "get_user_profile", lambda uid: UserProfile(uid=uid, role=UserRole.FACULTY))
    assert client.get("/api/v1/users/f1", headers=AUTH).json()["uid"] == "f1"


def test_list_users_admin(client, env, monkeypatch):
    from app.schemas.user import UserListResponse

    seen = {}

    def fake_list(**kw):
        seen.update(kw)
        return UserListResponse(items=[], next_cursor=None)

    monkeypatch.setattr(user_service, "list_users", fake_list)
    r = client.get("/api/v1/users?role=FACULTY&limit=5", headers=AUTH)
    assert r.status_code == 200
    assert seen["role"] == UserRole.FACULTY and seen["limit"] == 5
    assert client.get("/api/v1/users?limit=1000", headers=AUTH).status_code == 422


def test_audit_sanitizes_secrets():
    from app.services.audit import sanitize_metadata

    out = sanitize_metadata({"role": "X", "password": "p", "id_token": "t", "n": {"private_key": "k", "ok": 1}})
    assert out == {"role": "X", "n": {"ok": 1}}

