"""One "now" for the read paths (queries, windows such as "the last 30 days", pages), so a
test can pin it next to its fixed event dates and give the same result on any day. Ingest,
sign-in, and audit times read the real clock. Outside tests nothing pins it."""

from __future__ import annotations

from datetime import UTC, datetime

_pinned: datetime | None = None


def now() -> datetime:
    """The current time in UTC, or the pinned time in a test."""
    return _pinned if _pinned is not None else datetime.now(UTC)


def pin(at: datetime | None) -> None:
    """Pin "now" to `at` (tz-aware), or unpin with None. Tests only."""
    if at is not None and at.tzinfo is None:
        raise ValueError("a pinned time must be timezone-aware")
    global _pinned
    _pinned = at


def utc_words(at: datetime) -> str:
    """'2026-10-27 09:00 UTC': a time in an alert's text and its messages."""
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
