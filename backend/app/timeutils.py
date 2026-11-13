"""Shared timezone helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime | None) -> datetime | None:
    """Return a timezone-aware UTC datetime, or ``None``.

    SQLite drops ``tzinfo`` on read, so normalise values before Python-side
    comparisons.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
