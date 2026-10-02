from __future__ import annotations

from app.core.errors import AcademicNotFoundError, AcademicValidationError
from app.core.firebase import get_auth_account_info
from app.schemas.user import UserProfile, UserRole
from app.services.users import get_user_profile


def load_linkable_user(uid: str, role: UserRole, id_field: str, id_value: str) -> UserProfile:
    """Verify a Firebase user may be linked to a student/faculty profile.

    The Auth account must exist and be enabled; users/{uid} must exist, be active,
    have the expected role (and not contradict the role custom claim), and any
    existing student_id/faculty_id on it must equal the one being linked.
    """
    info = get_auth_account_info(uid)
    if info is None:
        raise AcademicNotFoundError("Firebase user not found.")
    profile = get_user_profile(uid)
    if profile is None:
        raise AcademicNotFoundError("Portal user profile not found for this Firebase user.")
    if profile.role != role:
        raise AcademicValidationError(f"Linked user must have role {role.value}.")
    claim = info.get("role")
    if isinstance(claim, str) and claim.strip().upper() != role.value:
        raise AcademicValidationError("User role claim does not match the user profile role.")
    if info.get("disabled") or not profile.is_active:
        raise AcademicValidationError("Linked user account is not active.")
    existing = getattr(profile, id_field)
    if existing and existing.lower() != id_value.lower():
        raise AcademicValidationError(f"User profile already has a different {id_field}.")
    return profile
