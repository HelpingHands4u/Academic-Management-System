from datetime import timedelta

import pytest

from app.services import academic_common as common
from app.services import sessions as sess_svc
from test_academic import AUTH, as_role, client, identity, mk_dept, mk_prog, mk_sem, mk_session, store  # noqa: F401
from test_courses import accounts, base, mk_course, mk_off, ready  # noqa: F401
from test_people import SEM, enrol, login, mk_enr, mk_fac, mk_student, people  # noqa: F401


def logs(client, **params):
    r = client.get("/api/v1/audit-logs", headers=AUTH, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---- audit logs -------------------------------------------------------------
def test_mutation_generates_audit_record_with_fields(client, base, store):
    body = logs(client, action="department.create")
    assert body["items"], "department creation must be audited"
    item = body["items"][0]
    assert item["audit_id"] == item["id"]
    assert (item["actor_uid"], item["actor_role"], item["resource_type"], item["resource_id"]) == (
        "admin-1", "ADMIN", "department", "cse")
    assert item["timestamp"] and isinstance(item["metadata"], dict)


def test_sensitive_metadata_is_excluded(client, base, store):
    common.audit(common.Actor("admin-1", "ADMIN"), "x.test", "x", "1",
                 {"password": "p", "id_token": "t", "api_key": "k", "private_key": "pk", "ok": 1,
                  "nested": {"Authorization": "Bearer z", "fine": 2}})
    item = logs(client, action="x.test")["items"][0]
    assert item["metadata"] == {"ok": 1, "nested": {"fine": 2}}


def test_audit_filters_and_pagination(client, enrol):
    assert all(i["actor_role"] == "ADMIN" for i in logs(client, actor_role="admin")["items"])
    assert logs(client, resource_type="course")["items"]
    assert all(i["resource_type"] == "course" for i in logs(client, resource_type="course")["items"])
    assert logs(client, actor_uid="nobody")["items"] == []
    assert logs(client, resource_id="cs101", resource_type="course")["items"]
    first = logs(client, limit=2)
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = logs(client, limit=2, cursor=first["next_cursor"])
    assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in second["items"])


def test_audit_time_range(client, base):
    now = common.now()
    inside = logs(client, **{"from": (now - timedelta(hours=1)).isoformat(), "to": (now + timedelta(hours=1)).isoformat()})
    assert inside["items"]
    future = logs(client, **{"from": (now + timedelta(hours=1)).isoformat()})
    assert future["items"] == []
    r = client.get("/api/v1/audit-logs", headers=AUTH,
                   params={"from": (now + timedelta(hours=2)).isoformat(), "to": now.isoformat()})
    assert r.status_code == 422


@pytest.mark.parametrize("role", ["STUDENT", "FACULTY"])
def test_audit_non_admin_denied(client, identity, base, role):
    as_role(identity, role)
    assert client.get("/api/v1/audit-logs", headers=AUTH).status_code == 403


def test_audit_unauthenticated(client):
    assert client.get("/api/v1/audit-logs").status_code == 401


def test_timetable_and_user_actions_audited(client, identity, store, monkeypatch):
    from app.services import users as users_svc
    from app.schemas.user import UserProfile, UserRole
    calls = []
    store.docs[("users", "u9")] = {"uid": "u9", "role": "STUDENT", "is_active": True}
    monkeypatch.setattr(users_svc, "get_firestore_client", lambda: _fs(store))
    monkeypatch.setattr(users_svc, "set_auth_disabled", lambda uid, d: calls.append(("disabled", uid, d)))
    monkeypatch.setattr(users_svc, "set_auth_role_claim", lambda uid, r: calls.append(("role", uid, r)))
    r = client.patch("/api/v1/users/u9", headers=AUTH, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = client.patch("/api/v1/users/u9", headers=AUTH, json={"role": "FACULTY"})
    assert r.status_code == 200 and r.json()["role"] == "FACULTY"
    actions = [i["action"] for i in logs(client, resource_type="user")["items"]]
    assert actions == ["user.deactivate", "user.role_change"]
    assert calls == [("disabled", "u9", True), ("role", "u9", "FACULTY")]


class _FS:
    """users_svc uses .collection(name).document(uid).update(...): route to the fake store."""

    def __init__(self, store):
        self.store = store

    def collection(self, name):
        store = self.store

        class Doc:
            def __init__(self, uid):
                self.uid = uid

            def get(self):
                return store.collection(name).document(self.uid).get()

            def update(self, data):
                store.docs[(name, self.uid)].update(data)

        class Col:
            def document(self, uid):
                return Doc(uid)

            def add(self, data):
                return store.collection(name).add(data)

        return Col()


def _fs(store):
    return _FS(store)


def test_user_update_rules(client, identity, store, monkeypatch):
    from app.services import users as users_svc
    store.docs[("users", "admin-1")] = {"uid": "admin-1", "role": "ADMIN", "is_active": True}
    monkeypatch.setattr(users_svc, "get_firestore_client", lambda: _fs(store))
    monkeypatch.setattr(users_svc, "set_auth_disabled", lambda *a: None)
    monkeypatch.setattr(users_svc, "set_auth_role_claim", lambda *a: None)
    assert client.patch("/api/v1/users/admin-1", headers=AUTH, json={"is_active": False}).status_code == 400
    assert client.patch("/api/v1/users/ghost", headers=AUTH, json={"is_active": False}).status_code == 404
    assert client.patch("/api/v1/users/admin-1", headers=AUTH, json={"role": "bogus"}).status_code == 422
    as_role(identity, "STUDENT")
    assert client.patch("/api/v1/users/admin-1", headers=AUTH, json={"is_active": False}).status_code == 403

