from __future__ import annotations


class UserServiceError(Exception):
    """Base class for user-service domain errors (safe to map to HTTP)."""


class UserAlreadyExistsError(UserServiceError):
    pass


class UserNotFoundError(UserServiceError):
    pass


class UserProvisioningError(UserServiceError):
    """Account could not be provisioned; any partial state was rolled back."""


class UserValidationError(UserServiceError):
    pass


class AcademicNotFoundError(UserServiceError):
    """A referenced academic record does not exist (message is client-safe)."""


class AcademicConflictError(UserServiceError):
    """Uniqueness conflict (duplicate code / combination)."""


class AcademicValidationError(UserServiceError):
    """Semantically invalid request (e.g. inactive parent)."""


class UnprocessableAcademicError(AcademicValidationError):
    """Request is well-formed but semantically invalid; maps to HTTP 422."""


class InvalidDateRangeError(UnprocessableAcademicError):
    """start_date is not before end_date."""



class AcademicForbiddenError(UserServiceError):
    """Authenticated caller is not allowed to act on this resource (maps to HTTP 403)."""
