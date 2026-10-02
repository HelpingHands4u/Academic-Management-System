import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import security
from app.core.firebase import FirebaseNotConfiguredError
from app.main import app
from app.schemas.user import UserProfile, UserRole

UID = "uid-123"


def _decoded(**extra):
    return {"uid": UID, "email": "a@example.test", "email_verified": True, "name": "Test User", **extra}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_firebase(monkeypatch):
    """Patch token verification and Firestore profile lookup; no real Firebase."""
    state = {"decoded": _decoded(), "profile": None}

    def fake_verify(token):
        if token != "good-token":
            raise ValueError("bad token")
        return state["decoded"]

    monkeypatch.setattr(security, "verify_id_token", fake_verify)
    monkeypatch.setattr(security, "get_user_profile", lambda uid: state["profile"])
    return state


AUTH = {"Authorization": "Bearer good-token"}


def test_health_still_works(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_me_missing_header_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "Bearer a b", "abc"])
def test_me_malformed_header_401(client, header):
    assert client.get("/api/v1/auth/me", headers={"Authorization": header}).status_code == 401


def test_me_invalid_token_401_no_leak(client, mock_firebase):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert "bad token" not in r.text


def test_me_unconfigured_firebase_503(client, monkeypatch):
    def boom(token):
        raise FirebaseNotConfiguredError("x")

    monkeypatch.setattr(security, "verify_id_token", boom)
    assert client.get("/api/v1/auth/me", headers=AUTH).status_code == 503


def test_me_no_profile(client, mock_firebase):
    r = client.get("/api/v1/auth/me", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["uid"] == UID
    assert body["email"] == "a@example.test"
    assert body["display_name"] == "Test User"
    assert body["profile_provisioned"] is False
    assert body["role"] is None
    assert "not yet been provisioned" in body["message"]


def test_me_role_from_claims(client, mock_firebase):
    mock_firebase["decoded"] = _decoded(role="ADMIN")
    body = client.get("/api/v1/auth/me", headers=AUTH).json()
    assert body["role"] == "ADMIN"
    assert body["role_source"] == "claims"


def test_me_role_from_profile(client, mock_firebase):
    mock_firebase["profile"] = UserProfile(uid=UID, role=UserRole.STUDENT)
    body = client.get("/api/v1/auth/me", headers=AUTH).json()
    assert body["role"] == "STUDENT"
    assert body["role_source"] == "profile"
    assert body["profile_provisioned"] is True


def test_request_body_role_is_ignored(client, mock_firebase):
    r = client.get("/api/v1/auth/me", headers={**AUTH, "X-Role": "ADMIN"}, params={"role": "ADMIN"})
    assert r.json()["role"] is None


def test_disabled_profile_403(client, mock_firebase):
    mock_firebase["profile"] = UserProfile(uid=UID, role=UserRole.STUDENT, is_active=False)
    assert client.get("/api/v1/auth/me", headers=AUTH).status_code == 403


@pytest.fixture
def role_client(mock_firebase):
    test_app = FastAPI()

    @test_app.get("/admin")
    def admin(ctx=Depends(security.require_admin())):
        return {"ok": True}

    @test_app.get("/faculty")
    def faculty(ctx=Depends(security.require_faculty())):
        return {"ok": True}

    @test_app.get("/student")
    def student(ctx=Depends(security.require_student())):
        return {"ok": True}

    return TestClient(test_app)


def test_role_unauthenticated_401(role_client):
    assert role_client.get("/admin").status_code == 401


def test_role_insufficient_403(role_client, mock_firebase):
    mock_firebase["decoded"] = _decoded(role="STUDENT")
    assert role_client.get("/admin", headers=AUTH).status_code == 403
    assert role_client.get("/faculty", headers=AUTH).status_code == 403
    assert role_client.get("/student", headers=AUTH).status_code == 200


def test_role_without_any_role_403(role_client):
    assert role_client.get("/student", headers=AUTH).status_code == 403


def test_role_allowed(role_client, mock_firebase):
    mock_firebase["decoded"] = _decoded(role="admin")
    assert role_client.get("/admin", headers=AUTH).status_code == 200
