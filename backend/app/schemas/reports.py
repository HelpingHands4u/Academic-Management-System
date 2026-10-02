from __future__ import annotations

from datetime import date
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Report(BaseModel, Generic[T]):
    """A computed summary (from real stored data, over the same filters) plus a paginated item list."""

    summary: dict[str, Any]
    items: list[T]
    next_cursor: str | None = Field(default=None, description="Pass as `cursor` for the next page.")
