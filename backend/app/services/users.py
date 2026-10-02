from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.errors import (
    UserAlreadyExistsError,
    UserNotFoundError,
    UserProvisioningError,
    UserValidationError,
)
from app.core.firebase import (
    create_auth_user,
    delete_auth_user,
    get_firestore_client,
    set_auth_disabled,
    set_auth_role_claim,
)
from app.schemas.user import UserCreate, UserListResponse, UserProfile, UserRole, UserUpdate
from app.services.audit import record_audit_event

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users"
MAX_PAGE_SIZE = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_user_profile_data(uid: str) -> dict[str, Any] | None:
    """Fetch raw users/{uid} data; None if the document does not exist."""
    snapshot = get_firestore_client().collection(USERS_COLLECTION).document(uid).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict() or {}


def get_user_profile(uid: str) -> UserProfile | None:
    """Fetch users/{uid} as a UserProfile. Never creates documents.

    Raises pydantic.ValidationError if the stored document is malformed.
    """
    data = get_user_profile_data(uid)
    if data is None:
        return None
    data["uid"] = uid  # document id is authoritative
    return UserProfile(**data)


def require_user_profile(uid: str) -> UserProfile:
    profile = get_user_profile(uid)
    if profile is None:
        raise UserNotFoundError("User not found.")
    return profile


def create_user(payload: UserCreate, *, actor_uid: str | None, actor_role: str | None) -> UserProfile:
    """Create the Firebase Auth account, set the role claim, and write users/{uid}.

    The password is passed only to Firebase Auth. If anything after Auth
    creation fails, the Auth account is deleted so no orphan remains.
    """
    uid = create_auth_user(
        email=payload.email,
        password=payload.password.get_secret_value(),
        display_name=payload.display_name,
    )
    now = _now()
    profile = UserProfile(
        uid=uid,
        email=payload.email,
        display_name=payload.display_name,
        role=payload.role,
        student_id=payload.student_id,
        faculty_id=payload.faculty_id,
        department_id=payload.department_id,
        program_id=payload.program_id,
        semester_id=payload.semester_id,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    try:
        set_auth_role_claim(uid, payload.role.value)
        # create() fails if the document already exists: never overwrite.
        get_firestore_client().collection(USERS_COLLECTION).document(uid).create(
            profile.model_dump(mode="python")
        )
    except Exception as exc:
        logger.error("User provisioning failed after Auth creation (%s); rolling back.", type(exc).__name__)
        try:
            delete_auth_user(uid)
        except Exception as rollback_exc:
            logger.critical(
                "Rollback failed for uid %s (%s); manual cleanup required.", uid, type(rollback_exc).__name__
            )
        raise UserProvisioningError("User could not be created.") from None

    record_audit_event(
        actor_uid=actor_uid,
        actor_role=actor_role,
        action="user.create",
        resource_type="user",
        resource_id=uid,
        metadata={"role": payload.role.value, "email": payload.email},
    )
    return profile


def list_users(
    *,
    role: UserRole | None = None,
    is_active: bool | None = None,
    department_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> UserListResponse:
    from google.cloud.firestore_v1.base_query import FieldFilter

    limit = max(1, min(limit, MAX_PAGE_SIZE))
    collection = get_firestore_client().collection(USERS_COLLECTION)
    query = collection
    if role is not None:
        query = query.where(filter=FieldFilter("role", "==", role.value))
    if is_active is not None:
        query = query.where(filter=FieldFilter("is_active", "==", is_active))
    if department_id:
        query = query.where(filter=FieldFilter("department_id", "==", department_id))
    query = query.order_by("__name__")
    if cursor:
        cursor_snap = collection.document(cursor).get()
        if cursor_snap.exists:
            query = query.start_after(cursor_snap)
    snaps = list(query.limit(limit + 1).stream())

    items: list[UserProfile] = []
    for snap in snaps[:limit]:
        data = snap.to_dict() or {}
        data["uid"] = snap.id
        try:
            items.append(UserProfile(**data))
        except Exception:
            logger.error("Skipping malformed users/%s document.", snap.id)
    next_cursor = snaps[limit - 1].id if len(snaps) > limit else None
    return UserListResponse(items=items, next_cursor=next_cursor)


def user_exists_with_role(role: UserRole) -> bool:
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = (
        get_firestore_client()
        .collection(USERS_COLLECTION)
        .where(filter=FieldFilter("role", "==", role.value))
        .limit(1)
    )
    return any(True for _ in query.stream())


__all__ = [
    "UserAlreadyExistsError",
    "create_user",
    "get_user_profile",
    "get_user_profile_data",
    "list_users",
    "require_user_profile",
    "user_exists_with_role",
]


def update_user(uid: str, payload: UserUpdate, *, actor_uid: str | None, actor_role: str | None) -> UserProfile:
    """ADMIN: activate/deactivate or change the role. Auth (disabled flag / role claim) and the
    Firestore profile are kept in sync; admins cannot lock themselves out."""
    profile = require_user_profile(uid)
    changes = payload.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise UserValidationError("Fields cannot be null.")
    if uid == actor_uid and (changes.get("is_active") is False or
                             ("role" in changes and changes["role"] != profile.role)):
        raise UserValidationError("You cannot deactivate or change the role of your own account.")
    events: list[tuple[str, dict[str, Any]]] = []
    if "is_active" in changes and changes["is_active"] != profile.is_active:
        set_auth_disabled(uid, not changes["is_active"])
        events.append(("user.activate" if changes["is_active"] else "user.deactivate", {}))
    if "role" in changes and changes["role"] != profile.role:
        set_auth_role_claim(uid, changes["role"].value)
        events.append(("user.role_change", {"from": profile.role.value, "to": changes["role"].value}))
    if not events:
        return profile
    update = {"updated_at": _now()}
    if "is_active" in changes:
        update["is_active"] = changes["is_active"]
    if "role" in changes:
        update["role"] = changes["role"].value
    get_firestore_client().collection(USERS_COLLECTION).document(uid).update(update)
    for action, meta in events:
        record_audit_event(actor_uid=actor_uid, actor_role=actor_role, action=action,
                           resource_type="user", resource_id=uid, metadata=meta)
    return profile.model_copy(update={**update, "role": UserRole(update["role"]) if "role" in update else profile.role})
