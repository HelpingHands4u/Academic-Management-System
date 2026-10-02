from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from app.core.errors import (
    UserAlreadyExistsError,
    UserNotFoundError,
    UserProvisioningError,
    UserValidationError,
)
from app.core.firebase import FirebaseNotConfiguredError
from app.core.security import AuthContext, require_admin, require_authenticated_user
from app.schemas.user import UserCreate, UserListResponse, UserProfile, UserRole, UserUpdate
from app.services import users as user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UserAlreadyExistsError):
        return HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    if isinstance(exc, UserNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if isinstance(exc, UserValidationError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, FirebaseNotConfiguredError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "User service is not configured.")
    if isinstance(exc, UserProvisioningError):
        return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "User could not be created.")
    logger.error("Unexpected user-service error (%s).", type(exc).__name__)
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error.")


@router.post("", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, ctx: AuthContext = Depends(require_admin())) -> UserProfile:
    try:
        return user_service.create_user(
            payload, actor_uid=ctx.user.uid, actor_role=ctx.role.value if ctx.role else None
        )
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/me", response_model=UserProfile)
def read_my_profile(ctx: AuthContext = Depends(require_authenticated_user)) -> UserProfile:
    if ctx.profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Portal profile has not been provisioned.")
    return ctx.profile


@router.get("", response_model=UserListResponse)
def list_users(
    role: UserRole | None = None,
    is_active: bool | None = None,
    department_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=128),
    _: AuthContext = Depends(require_admin()),
) -> UserListResponse:
    try:
        return user_service.list_users(
            role=role, is_active=is_active, department_id=department_id, limit=limit, cursor=cursor
        )
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/{uid}", response_model=UserProfile)
def read_user(uid: str, _: AuthContext = Depends(require_admin())) -> UserProfile:
    try:
        return user_service.require_user_profile(uid)
    except ValidationError:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Stored profile is malformed.") from None
    except Exception as exc:
        raise _http_error(exc) from None


@router.patch("/{uid}", response_model=UserProfile)
def update_user(uid: str, payload: UserUpdate, ctx: AuthContext = Depends(require_admin())) -> UserProfile:
    """ADMIN only: activate/deactivate an account or change its role (audited)."""
    try:
        return user_service.update_user(
            uid, payload, actor_uid=ctx.user.uid, actor_role=ctx.role.value if ctx.role else None
        )
    except Exception as exc:
        raise _http_error(exc) from None
