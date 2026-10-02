from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from app.core.firebase import FirebaseNotConfiguredError, verify_id_token
from app.schemas.user import UserProfile, UserRole
from app.services.users import get_user_profile

logger = logging.getLogger(__name__)

_BEARER_HEADERS = {"WWW-Authenticate": "Bearer"}
_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="FirebaseBearer",
    description="Firebase Authentication ID token. Roles and academic scope are checked server-side.",
)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers=_BEARER_HEADERS
    )


@dataclass(frozen=True)
class FirebaseUser:
    uid: str
    email: str | None
    email_verified: bool | None
    display_name: str | None
    claims: dict[str, Any]


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise _unauthorized("Missing Authorization header.")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _unauthorized("Authorization header must be 'Bearer <Firebase ID token>'.")
    return parts[1]


def get_firebase_user(
    authorization: str | None = Header(default=None, include_in_schema=False),
    _credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> FirebaseUser:
    """Dependency: verify the Bearer Firebase ID token and return the identity."""
    token = extract_bearer_token(authorization)
    try:
        decoded = verify_id_token(token)
    except FirebaseNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured.",
        ) from None
    except Exception as exc:
        # Do not leak Firebase internals to clients.
        logger.info("ID token rejected (%s).", type(exc).__name__)
        raise _unauthorized("Invalid or expired authentication token.") from None

    uid = decoded.get("uid") or decoded.get("user_id") or decoded.get("sub")
    if not uid:
        raise _unauthorized("Invalid or expired authentication token.")
    return FirebaseUser(
        uid=uid,
        email=decoded.get("email"),
        email_verified=decoded.get("email_verified"),
        display_name=decoded.get("name"),
        claims=decoded,
    )


def get_current_uid(user: FirebaseUser = Depends(get_firebase_user)) -> str:
    return user.uid


def is_authenticated(authorization: str | None) -> bool:
    """Non-raising check for use outside of dependency injection."""
    try:
        get_firebase_user(authorization)
    except HTTPException:
        return False
    return True


def _parse_role(value: Any) -> UserRole | None:
    if not isinstance(value, str):
        return None
    try:
        return UserRole(value.strip().upper())
    except ValueError:
        return None


@dataclass(frozen=True)
class AuthContext:
    user: FirebaseUser
    role: UserRole | None
    role_source: str | None  # "claims" | "profile" | None
    profile: UserProfile | None


def _load_profile(uid: str) -> UserProfile | None:
    try:
        return get_user_profile(uid)
    except FirebaseNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is not configured.",
        ) from None
    except ValidationError:
        logger.error("Malformed users/%s profile document.", uid)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile service is temporarily unavailable.",
        ) from None
    except Exception as exc:
        logger.error("Firestore profile lookup failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile service is temporarily unavailable.",
        ) from None


def get_auth_context(user: FirebaseUser = Depends(get_firebase_user)) -> AuthContext:
    """Resolve the trusted role: Firebase custom claim first, then Firestore profile.

    Roles are never read from the request body, query, or client headers.
    """
    profile = _load_profile(user.uid)
    if profile is not None and not profile.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled.")

    claim_role = _parse_role(user.claims.get("role"))
    if claim_role is not None and profile is not None and claim_role != profile.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account role has changed. Refresh your authentication token.",
        )
    if claim_role is not None:
        return AuthContext(user, claim_role, "claims", profile)
    if profile is not None:
        return AuthContext(user, profile.role, "profile", profile)
    return AuthContext(user, None, None, None)


def require_roles(*allowed: UserRole) -> Callable[..., AuthContext]:
    """Build a dependency that returns 401 if unauthenticated, 403 if role not allowed."""
    allowed_set = frozenset(allowed)

    def dependency(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if ctx.role is None or ctx.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return ctx

    return dependency


def require_admin() -> Callable[..., AuthContext]:
    return require_roles(UserRole.ADMIN)


def require_faculty() -> Callable[..., AuthContext]:
    return require_roles(UserRole.FACULTY)


def require_student() -> Callable[..., AuthContext]:
    return require_roles(UserRole.STUDENT)


def require_authenticated_user(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Dependency: verified token + active profile (if any). Role not required."""
    return ctx
