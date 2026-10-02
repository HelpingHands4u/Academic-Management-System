from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.core.errors import (
    AcademicForbiddenError,
    AcademicConflictError,
    AcademicNotFoundError,
    AcademicValidationError,
    UnprocessableAcademicError,
)
from app.core.firebase import FirebaseNotConfiguredError

logger = logging.getLogger(__name__)


def to_http(exc: Exception) -> HTTPException:
    """Map domain errors to safe HTTP errors; never expose internals."""
    if isinstance(exc, AcademicForbiddenError):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(exc, AcademicNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, AcademicConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, UnprocessableAcademicError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if isinstance(exc, AcademicValidationError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, FirebaseNotConfiguredError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Data service is not configured.")
    logger.error("Unexpected academic-service error (%s).", type(exc).__name__)
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error.")


