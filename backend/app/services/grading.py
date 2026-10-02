from __future__ import annotations

"""Grading + GPA calculations. No grading scale is built in: the scheme is configuration stored in
Firestore (`settings/grading_scheme`) and must be supplied by the project owner."""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, NamedTuple, Sequence

from app.core.errors import AcademicConflictError, AcademicNotFoundError, UnprocessableAcademicError
from app.schemas.marks import GradeBand, GradingScheme
from app.services import academic_common as common
from app.services.academic_common import Actor

SETTINGS = "settings"
SCHEME_DOC = "grading_scheme"
TWO_PLACES = Decimal("0.01")


class Grade(NamedTuple):
    grade: str
    grade_point: float
    is_pass: bool


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def q2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def calculate_percentage(total: Decimal, maximum: Decimal) -> Decimal:
    if maximum <= 0:
        raise UnprocessableAcademicError("max_marks must be positive.")
    return q2(total * 100 / maximum)


def calculate_grade(percentage: float | Decimal, scheme: GradingScheme) -> Grade:
    """Band lookup: min <= p < max; the band ending at 100 also includes 100."""
    if isinstance(percentage, bool) or percentage is None:
        raise UnprocessableAcademicError("Invalid percentage.")
    if isinstance(percentage, float) and not math.isfinite(percentage):
        raise UnprocessableAcademicError("Invalid percentage.")
    p = dec(percentage)
    if p < 0 or p > 100:
        raise UnprocessableAcademicError("Percentage must be between 0 and 100.")
    for band in scheme.bands:
        low, high = dec(band.min_percentage), dec(band.max_percentage)
        if low <= p < high or (p == high == 100):
            return Grade(band.grade, band.grade_point, band.is_pass)
    raise UnprocessableAcademicError("Percentage is not covered by the grading scheme.")


def calculate_sgpa(courses: Sequence[tuple[Any, Any]]) -> Decimal | None:
    """SGPA = sum(credit * grade_point) / sum(credit); None when there are no credits."""
    total = sum((dec(c) for c, _ in courses), Decimal(0))
    if total <= 0:
        return None
    return q2(sum((dec(c) * dec(gp) for c, gp in courses), Decimal(0)) / total)


def calculate_cgpa(semesters: Sequence[tuple[Any, Any]]) -> Decimal | None:
    """CGPA = sum(semester credits * semester SGPA) / sum(semester credits) (a credit-weighted
    mean, not a plain average of SGPAs); None when there are no credits."""
    return calculate_sgpa(semesters)


# ---- configuration --------------------------------------------------------
def get_scheme(*, required: bool = True) -> GradingScheme | None:
    row = common.fetch(SETTINGS, SCHEME_DOC)
    if row is None:
        if required:
            raise AcademicConflictError("No grading scheme is configured. An ADMIN must set one first.")
        return None
    return GradingScheme(name=row.get("name"), bands=[GradeBand(**b) for b in row["bands"]])


def get_scheme_view() -> dict[str, Any]:
    row = common.fetch(SETTINGS, SCHEME_DOC)
    if row is None:
        raise AcademicNotFoundError("No grading scheme is configured.")
    return {"name": row.get("name"), "bands": row["bands"], "updated_at": row.get("updated_at"),
            "updated_by_uid": row.get("updated_by_uid")}


def set_scheme(scheme: GradingScheme, actor: Actor) -> dict[str, Any]:
    data = {"name": scheme.name, "bands": [b.model_dump() for b in scheme.bands],
            "updated_at": common.now(), "updated_by_uid": actor.uid}
    exists = common.fetch(SETTINGS, SCHEME_DOC) is not None
    common.write(SETTINGS, SCHEME_DOC, data, create=not exists)
    common.audit(actor, "grading_scheme.set", "grading_scheme", SCHEME_DOC, {"bands": len(scheme.bands)})
    return get_scheme_view()
