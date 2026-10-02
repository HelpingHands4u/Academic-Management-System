from datetime import timedelta

import pytest

from app.services import academic_common as common
from app.services import sessions as sess_svc
from test_academic import AUTH, as_role, client, identity, store  # noqa: F401
from test_people import login


def start(client, **kw):
    return client.post("/api/v1/sessions", headers=AUTH, **kw)


def test_start_session_uses_verified_identity(client, identity, store):
    login(identity, "stu-1", "STUDENT")
    r = start(client, json={"metadata": {"platform": "web"}})
    assert r.status_code == 201, r.text
    b = r.json()
    assert set(b) == {"session_id", "login_at", "last_seen_at", "is_active"} and b["is_active"] is True
    doc = store.docs[("user_sessions", b["session_id"])]
    assert (doc["uid"], doc["role"], doc["logout_at"]) == ("stu-1", "STUDENT", None)
    assert doc["metadata"] == {"platform": "web"}
    assert "token" not in str(doc).lower() and "authorization" not in str(doc).lower()


def test_body_cannot_set_uid_or_role(client, identity):
    assert start(client, json={"uid": "other", "role": "ADMIN"}).status_code == 422


def test_sensitive_metadata_dropped_and_limits(client, identity, store):
    r = start(client, json={"metadata": {"id_token": "abc", "ok": "1"}})
    assert r.status_code == 201
    assert store.docs[("user_sessions", r.json()["session_id"])]["metadata"] == {"ok": "1"}
    assert start(client, json={"metadata": {f"k{i}": 1 for i in range(11)}}).status_code == 422


def test_start_without_body_and_user_agent_truncated(client, identity, store):
    r = client.post("/api/v1/sessions", headers={**AUTH, "User-Agent": "x" * 1000})
    assert r.status_code == 201
    assert len(store.docs[("user_sessions", r.json()["session_id"])]["user_agent"]) == 300


def test_unauthenticated_401(client):
    assert client.post("/api/v1/sessions").status_code == 401
    assert client.patch("/api/v1/sessions/x/heartbeat").status_code == 401


def test_each_start_creates_distinct_session(client, identity):
    assert start(client).json()["session_id"] != start(client).json()["session_id"]


def test_heartbeat_updates_last_seen_only(client, identity, store):
    sid = start(client).json()["session_id"]
    store.docs[("user_sessions", sid)]["last_seen_at"] = common.now() - timedelta(hours=1)
    before = store.docs[("user_sessions", sid)]["login_at"]
    r = client.patch(f"/api/v1/sessions/{sid}/heartbeat", headers=AUTH)
    assert r.status_code == 200 and r.json()["is_active"] is True
    doc = store.docs[("user_sessions", sid)]
    assert doc["last_seen_at"] > common.now() - timedelta(minutes=1) and doc["login_at"] == before


def test_logout_closes_but_keeps_document_and_is_idempotent(client, identity, store):
    sid = start(client).json()["session_id"]
    r = client.post(f"/api/v1/sessions/{sid}/logout", headers=AUTH)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["logout_at"]
    assert ("user_sessions", sid) in store.docs
    first = store.docs[("user_sessions", sid)]["logout_at"]
    assert client.post(f"/api/v1/sessions/{sid}/logout", headers=AUTH).status_code == 200
    assert store.docs[("user_sessions", sid)]["logout_at"] == first


def test_heartbeat_on_closed_session_409(client, identity):
    sid = start(client).json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/logout", headers=AUTH)
    assert client.patch(f"/api/v1/sessions/{sid}/heartbeat", headers=AUTH).status_code == 409


def test_unknown_session_404(client, identity):
    assert client.patch("/api/v1/sessions/ghost/heartbeat", headers=AUTH).status_code == 404
    assert client.post("/api/v1/sessions/ghost/logout", headers=AUTH).status_code == 404


@pytest.mark.parametrize("owner,other", [("STUDENT", "FACULTY"), ("FACULTY", "STUDENT")])
def test_ownership_enforced(client, identity, store, owner, other):
    login(identity, "owner-1", owner)
    sid = start(client).json()["session_id"]
    login(identity, "other-1", other)
    assert client.patch(f"/api/v1/sessions/{sid}/heartbeat", headers=AUTH).status_code == 404
    assert client.post(f"/api/v1/sessions/{sid}/logout", headers=AUTH).status_code == 404
    assert store.docs[("user_sessions", sid)]["is_active"] is True


def test_admin_can_manage_any_session(client, identity, store):
    login(identity, "stu-1", "STUDENT")
    sid = start(client).json()["session_id"]
    login(identity, "admin-1", "ADMIN")
    assert client.patch(f"/api/v1/sessions/{sid}/heartbeat", headers=AUTH).status_code == 200
    assert client.post(f"/api/v1/sessions/{sid}/logout", headers=AUTH).status_code == 200
    assert store.docs[("user_sessions", sid)]["uid"] == "stu-1"  # ownership unchanged


# ---- active users -----------------------------------------------------------
def seed(store, sid, uid, role, ago_s, active=True):
    ts = common.now() - timedelta(seconds=ago_s)
    store.docs[("user_sessions", sid)] = {"session_id": sid, "uid": uid, "role": role, "login_at": ts,
                                          "last_seen_at": ts, "logout_at": None if active else ts, "is_active": active}


def active(client, **p):
    r = client.get("/api/v1/analytics/active-users", headers=AUTH, params=p)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(autouse=True)
def windows(monkeypatch):
    monkeypatch.setattr(sess_svc, "windows", lambda: (300, 3600))


def test_active_users_empty_state(client, identity, store):
    b = active(client)
    assert (b["active_user_count"], b["recently_active_count"], b["total_users"]) == (0, 0, 0)
    assert b["active_window_seconds"] == 300 and b["recent_window_seconds"] == 3600


def test_active_users_threshold_roles_and_exclusions(client, identity, store):
    seed(store, "s1", "stu-1", "STUDENT", 10)
    seed(store, "s1b", "stu-1", "STUDENT", 20)           # same user twice counts once
    seed(store, "s2", "stu-2", "STUDENT", 299)
    seed(store, "s3", "stu-3", "STUDENT", 301)           # idle beyond window: not active, still recent
    seed(store, "f1", "fac-1", "FACULTY", 30)
    seed(store, "a1", "adm-1", "ADMIN", 5)
    seed(store, "x1", "stu-9", "STUDENT", 5, active=False)  # logged out: excluded from active
    seed(store, "old", "stu-8", "STUDENT", 7200)         # outside the recent window too
    b = active(client)
    assert (b["active_user_count"], b["active_student_count"], b["active_faculty_count"],
            b["active_admin_count"]) == (4, 2, 1, 1)
    assert b["recently_active_count"] == 6  # stu-1, stu-2, stu-3, fac-1, adm-1, stu-9
    assert b["active_sessions"] is None


def test_registered_counts_separate_from_active(client, identity, store):
    for uid, role in [("u1", "STUDENT"), ("u2", "STUDENT"), ("u3", "FACULTY"), ("u4", "ADMIN")]:
        store.docs[("users", uid)] = {"uid": uid, "role": role}
    b = active(client)
    assert (b["total_users"], b["total_students"], b["total_faculty"], b["total_admins"]) == (4, 2, 1, 1)
    assert b["active_user_count"] == 0  # a profile alone never makes anyone "online"


def test_active_sessions_listing_exposes_only_identifiers(client, identity, store):
    seed(store, "s1", "stu-1", "STUDENT", 10)
    b = active(client, include_sessions=True)
    assert b["active_sessions"] == [{"session_id": "s1", "uid": "stu-1", "role": "STUDENT"}]


@pytest.mark.parametrize("role", ["STUDENT", "FACULTY"])
def test_active_users_admin_only(client, identity, role):
    as_role(identity, role)
    assert client.get("/api/v1/analytics/active-users", headers=AUTH).status_code == 403
    assert client.get("/api/v1/analytics/admin", headers=AUTH).status_code == 403


def test_active_users_unauthenticated(client):
    assert client.get("/api/v1/analytics/active-users").status_code == 401

