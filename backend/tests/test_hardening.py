"""Regression checks for Phase 12; no network or production credentials."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.core import firebase, security
from app.core.config import Settings
from app.core.errors import AcademicConflictError
from app.schemas.user import UserProfile, UserRole
from app.services import academic_common, results
from app.services.audit import sanitize_metadata


def isolated_settings(**overrides):
    return Settings(
        _env_file=None,
        FIREBASE_PROJECT_ID=None,
        FIREBASE_CLIENT_EMAIL=None,
        FIREBASE_PRIVATE_KEY=None,
        GROQ_API_KEY=None,
        **overrides,
    )


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setattr(main, "get_settings", lambda: isolated_settings(FRONTEND_URL="http://localhost:5500"))
    return main.create_application()


def test_every_protected_operation_has_bearer_security_and_rejects_anonymous(application, monkeypatch):
    def unexpected_token_verification(*args, **kwargs):
        pytest.fail("An anonymous request must not contact Firebase")

    monkeypatch.setattr(security, "verify_id_token", unexpected_token_verification)
    schema = application.openapi()
    operation_ids = []
    with TestClient(application) as client:
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                operation_ids.append(operation["operationId"])
                if path == "/api/v1/health":
                    assert not operation.get("security")
                    continue
                assert operation["security"] == [{"FirebaseBearer": []}], (method, path)
                concrete_path = path
                for parameter in operation.get("parameters", []):
                    if parameter["in"] == "path":
                        concrete_path = concrete_path.replace("{" + parameter["name"] + "}", "unknown")
                response = client.request(method, concrete_path)
                assert response.status_code == 401, (method, path, response.text)
                assert response.headers["WWW-Authenticate"] == "Bearer"
                assert response.headers["Cache-Control"] == "no-store"
    assert len(operation_ids) == len(set(operation_ids))


def test_vercel_entrypoint_and_documentation(application):
    from api.index import app

    assert app is main.app
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8-sig"))
    assert config["builds"][0]["src"] == "api/index.py"
    assert config["routes"][0]["dest"] == "api/index.py"
    with TestClient(application) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 200
        assert client.get("/api/v1/health").json() == {
            "status": "ok", "service": "Brainware University Academic Management Portal",
        }


def test_cors_preflight_and_error_responses(application, caplog):
    @application.get("/api/v1/test-failure")
    def failure():
        raise RuntimeError("sensitive-provider-sentinel")

    with TestClient(application) as client:
        headers = {"Origin": "http://localhost:5500", "Access-Control-Request-Method": "PATCH",
                   "Access-Control-Request-Headers": "Authorization,Content-Type"}
        allowed = client.options("/api/v1/users/example", headers=headers)
        assert allowed.status_code == 200
        assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5500"
        denied = client.options("/api/v1/users/example", headers={**headers, "Origin": "https://untrusted.example"})
        assert denied.status_code == 400
        assert "Access-Control-Allow-Origin" not in denied.headers
        response = client.get("/api/v1/test-failure", headers={"Origin": "http://localhost:5500"})
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error."}
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5500"
        assert response.headers["Cache-Control"] == "no-store"
    assert "sensitive-provider-sentinel" not in caplog.text


def test_wildcard_cors_is_disabled():
    assert isolated_settings(FRONTEND_URL="*").cors_origins == []
    assert isolated_settings(FRONTEND_URL="http://localhost:5500/, https://portal.example/").cors_origins == [
        "http://localhost:5500", "https://portal.example",
    ]


@pytest.mark.parametrize("origin", [
    "https://portal.example/path", "https://user:password@portal.example",
    "https://*.example", "null", "http://localhost:invalid",
])
def test_invalid_frontend_origins_rejected(origin):
    with pytest.raises(ValidationError):
        isolated_settings(FRONTEND_URL=origin)


def test_environment_bom_newlines_and_secret_serialization(monkeypatch):
    for name in ("FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL", "FIREBASE_PRIVATE_KEY", "GROQ_API_KEY", "FRONTEND_URL"):
        monkeypatch.delenv(name, raising=False)
    with TemporaryDirectory(prefix="bwu-env-check-") as directory:
        env = Path(directory) / ".env"
        env.write_text(
            "FIREBASE_PROJECT_ID=unit-test-project\nFIREBASE_PRIVATE_KEY='line1\\nline2'\nGROQ_API_KEY=unit-test-secret\n",
            encoding="utf-8-sig",
        )
        settings = Settings(_env_file=env)
    assert settings.firebase_project_id == "unit-test-project"
    assert settings.firebase_private_key_normalized == "line1\nline2"
    assert settings.groq_api_key == "unit-test-secret"
    assert "line1" not in repr(settings) and "unit-test-secret" not in repr(settings)
    assert "firebase_private_key" not in settings.model_dump()
    assert "groq_api_key" not in settings.model_dump()
    example = Settings(_env_file=".env.example")
    assert example.firebase_private_key is None and example.groq_api_key is None


def test_revoked_and_disabled_firebase_tokens_are_checked(monkeypatch):
    seen = {}
    monkeypatch.setattr(firebase, "require_firebase_app", lambda: "test-app")

    def verify(token, **kwargs):
        seen.update(kwargs)
        return {"uid": "test-user"}

    monkeypatch.setattr(firebase.auth, "verify_id_token", verify)
    assert firebase.verify_id_token("test-token") == {"uid": "test-user"}
    assert seen == {"app": "test-app", "check_revoked": True}


def test_firebase_initialization_reuses_app_across_threads(monkeypatch):
    state = {"app": None, "created": 0}
    settings = SimpleNamespace(firebase_project_id="unit-test", firebase_client_email="unit-test@example.test",
                               firebase_private_key_normalized="unit-test-only")
    monkeypatch.setattr(firebase, "get_settings", lambda: settings)
    monkeypatch.setattr(firebase.credentials, "Certificate", lambda data: object())

    def existing():
        if state["app"] is None:
            raise ValueError("No default app")
        return state["app"]

    def initialize(*args):
        state["created"] += 1
        state["app"] = object()
        return state["app"]

    monkeypatch.setattr(firebase.firebase_admin, "get_app", existing)
    monkeypatch.setattr(firebase.firebase_admin, "initialize_app", initialize)
    with ThreadPoolExecutor(max_workers=8) as pool:
        apps = list(pool.map(lambda _: firebase.get_firebase_app(), range(16)))
    assert state["created"] == 1
    assert all(app is state["app"] for app in apps)


def test_role_demotion_rejects_stale_admin_claim(application, monkeypatch):
    monkeypatch.setattr(security, "verify_id_token", lambda token: {"uid": "u1", "role": "ADMIN"})
    monkeypatch.setattr(security, "get_user_profile", lambda uid: UserProfile(uid=uid, role=UserRole.STUDENT))
    with TestClient(application) as client:
        response = client.get("/api/v1/users", headers={"Authorization": "Bearer test"})
        assert response.status_code == 403
        assert "Refresh" in response.json()["detail"]


def test_corrupt_profile_fails_closed(application, monkeypatch):
    monkeypatch.setattr(security, "verify_id_token", lambda token: {"uid": "u1", "role": "ADMIN"})

    def corrupt(uid):
        return UserProfile(uid=uid, role="corrupt")

    monkeypatch.setattr(security, "get_user_profile", corrupt)
    with TestClient(application) as client:
        response = client.get("/api/v1/users", headers={"Authorization": "Bearer test"})
        assert response.status_code == 503
        assert "corrupt" not in response.text


def test_audit_sanitizes_nested_sequences_and_key_variants():
    source = {"changes": [{"privateKey": "sentinel", "API-Key": "sentinel", "ok": 1},
                          ({"Authorization": "sentinel", "nested": {"refreshToken": "sentinel"}},)]}
    clean = sanitize_metadata(source)
    assert clean == {"changes": [{"ok": 1}, [{"nested": {}}]]}
    assert source["changes"][0]["privateKey"] == "sentinel"


def test_firestore_range_queries_order_by_range_field(monkeypatch):
    seen = []

    class Query:
        def collection(self, name):
            return self

        def where(self, **kwargs):
            return self

        def order_by(self, field):
            seen.append(field)
            return self

        def limit(self, limit):
            return self

        def stream(self):
            return iter([])

    monkeypatch.setattr(academic_common, "get_firestore_client", Query)
    assert academic_common.list_docs("user_sessions", [("is_active", True), ("last_seen_at", "date", ">=")], 10, None) == ([], None)
    assert seen == ["last_seen_at"]


def test_failed_recalculation_cannot_publish_stale_result(monkeypatch):
    row = {"student_id": "S-001", "student_uid": "u1", "semester_id": "semester-1", "status": "COMPLETE"}
    monkeypatch.setattr(results.common, "fetch", lambda *args: row)
    monkeypatch.setattr(results, "regenerate_if_exists", lambda *args: None)

    def unexpected_write(*args, **kwargs):
        pytest.fail("A stale result must not be published")

    monkeypatch.setattr(results.common, "write", unexpected_write)
    with pytest.raises(AcademicConflictError):
        results.set_published("result-1", True, academic_common.Actor("admin", "ADMIN"))


def test_firebase_probe_is_bounded_and_does_not_print_data(monkeypatch, capsys):
    from scripts import verify_firebase as probe

    calls = []
    monkeypatch.setattr(probe, "get_settings", lambda: SimpleNamespace(firebase_project_id="test-project"))
    monkeypatch.setattr(probe, "require_firebase_app", lambda: SimpleNamespace(project_id="test-project"))
    monkeypatch.setattr(probe.auth, "list_users", lambda **kw: calls.append(("auth", kw["max_results"])))

    class ReadOnly:
        def collection(self, name):
            calls.append(("collection", name))
            return self

        def limit(self, value):
            calls.append(("limit", value))
            return self

        def stream(self):
            return iter([{"private-data": "must-not-print"}])

    monkeypatch.setattr(probe, "get_firestore_client", ReadOnly)
    assert probe.main(["--read-only", "--expected-project", "test-project"]) == 0
    assert calls == [("auth", 1), ("collection", "users"), ("limit", 1)]
    assert "must-not-print" not in capsys.readouterr().out


def test_firebase_probe_mismatch_and_errors_are_safe(monkeypatch, capsys):
    from scripts import verify_firebase as probe

    monkeypatch.setattr(probe, "get_settings", lambda: SimpleNamespace(firebase_project_id="test-project"))

    def fail():
        raise RuntimeError("private-provider-sentinel")

    monkeypatch.setattr(probe, "require_firebase_app", fail)
    assert probe.main(["--read-only", "--expected-project", "wrong-project"]) == 1
    assert "expected project" in capsys.readouterr().out
    assert probe.main(["--read-only", "--expected-project", "test-project"]) == 1
    assert "private-provider-sentinel" not in capsys.readouterr().out


def test_audit_range_handles_mixed_datetime_offsets(monkeypatch):
    from app.core.errors import UnprocessableAcademicError
    from app.services import audit_logs

    seen = []

    def query(collection, filters, *args, **kwargs):
        seen.extend(filters)
        return [], None

    monkeypatch.setattr(audit_logs.common, "list_docs", query)
    filters = dict(actor_uid=None, actor_role=None, action=None, resource_type=None,
                   resource_id=None, limit=10, cursor=None)
    result = audit_logs.list_audit_logs(
        **filters, from_time=datetime(2026, 1, 1), to_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert result.items == []
    assert all(value.tzinfo is not None for field, value, *rest in seen if field == "timestamp")
    with pytest.raises(UnprocessableAcademicError):
        audit_logs.list_audit_logs(
            **filters, from_time=datetime(2026, 1, 3), to_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
