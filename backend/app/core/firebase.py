from __future__ import annotations

import logging
import threading
from typing import Any

import firebase_admin
from firebase_admin import auth, credentials, firestore

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()


class FirebaseNotConfiguredError(RuntimeError):
    """Raised when Firebase credentials have not been supplied."""


def has_firebase_credentials() -> bool:
    settings = get_settings()
    return all(
        [
            settings.firebase_project_id,
            settings.firebase_client_email,
            settings.firebase_private_key_normalized,
        ]
    )


def get_firebase_app() -> firebase_admin.App | None:
    """Return the default Firebase app, initializing it once if credentials exist.

    Returns None when credentials are missing. Safe across reloads/threads.
    """
    with _init_lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass

        if not has_firebase_credentials():
            return None

        settings = get_settings()
        certificate: dict[str, Any] = {
            "type": "service_account",
            "project_id": settings.firebase_project_id,
            "client_email": settings.firebase_client_email,
            "private_key": settings.firebase_private_key_normalized,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        try:
            credential = credentials.Certificate(certificate)
            return firebase_admin.initialize_app(
                credential, {"projectId": settings.firebase_project_id}
            )
        except Exception as exc:
            # Never log the exception text: it may reference key material.
            logger.error("Firebase initialization failed (%s).", type(exc).__name__)
            raise FirebaseNotConfiguredError("Firebase is not configured correctly.") from None


def require_firebase_app() -> firebase_admin.App:
    app = get_firebase_app()
    if app is None:
        raise FirebaseNotConfiguredError("Firebase credentials are not configured.")
    return app


def get_firestore_client():
    """Return a Firestore client, or raise FirebaseNotConfiguredError."""
    return firestore.client(app=require_firebase_app())


def verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify signature, expiry, revocation and the Firebase account's disabled state."""
    return auth.verify_id_token(id_token, app=require_firebase_app(), check_revoked=True)

# ---------------------------------------------------------------------------
# Firebase Authentication helpers (Admin SDK). Kept here so services never
# import firebase_admin directly and tests can patch a single layer.
# ---------------------------------------------------------------------------


def create_auth_user(email: str, password: str, display_name: str | None) -> str:
    """Create a Firebase Auth account and return its uid.

    Raises UserAlreadyExistsError for duplicate email, UserValidationError for
    values Firebase rejects. The password is never logged.
    """
    from app.core.errors import UserAlreadyExistsError, UserValidationError

    try:
        record = auth.create_user(
            email=email,
            password=password,
            display_name=display_name,
            email_verified=False,
            disabled=False,
            app=require_firebase_app(),
        )
    except auth.EmailAlreadyExistsError:
        raise UserAlreadyExistsError("A user with this email already exists.") from None
    except ValueError:
        raise UserValidationError("Firebase rejected the supplied user details.") from None
    return record.uid


def delete_auth_user(uid: str) -> None:
    auth.delete_user(uid, app=require_firebase_app())


def set_auth_role_claim(uid: str, role: str) -> None:
    """Set the custom claim `role`. Existing ID tokens keep the old claim until refreshed."""
    auth.set_custom_user_claims(uid, {"role": role}, app=require_firebase_app())


def set_auth_disabled(uid: str, disabled: bool) -> None:
    auth.update_user(uid, disabled=disabled, app=require_firebase_app())


def get_auth_account_status(uid: str) -> bool | None:
    """Return None if the Firebase Auth account does not exist, else its `disabled` flag."""
    try:
        return bool(auth.get_user(uid, app=require_firebase_app()).disabled)
    except (auth.UserNotFoundError, ValueError):
        return None


def get_auth_account_info(uid: str) -> dict | None:
    """Return None if the Firebase Auth account does not exist, else
    {"disabled": bool, "role": <role custom claim or None>}. No secrets are returned."""
    try:
        record = auth.get_user(uid, app=require_firebase_app())
    except (auth.UserNotFoundError, ValueError):
        return None
    return {"disabled": bool(record.disabled), "role": (record.custom_claims or {}).get("role")}
