"""Event times that look a whole number of hours off (trial finding).

A source whose events carry local time with no zone, read with the wrong time zone, lands
every event a fixed number of hours early or late: `time_observed - time` sits at, say,
7.0 hours for every line. Ingest keeps the most recent differences per source; when they
are steady and close to a whole or half hour of at least one hour, Sources and Health say
so. Reading old files (a backfill) gives differences that are anything but steady, so it
does not trigger the warning.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

SAMPLES = 300  # recent events per source
MIN_SAMPLES = 30
MIN_OFFSET_S = 50 * 60  # under this, it is delivery delay, not a zone
SPREAD_S = 10 * 60  # 10th to 90th percentile: steady means within ten minutes
NEAR_S = 5 * 60  # this close to a half hour


def offset_hours(diffs: Iterable[float]) -> float | None:
    """Whole or half hours the event times look off (positive: they look early), or None."""
    xs = sorted(diffs)
    n = len(xs)
    if n < MIN_SAMPLES:
        return None
    median, p10, p90 = xs[n // 2], xs[n // 10], xs[(9 * n) // 10]
    if p90 - p10 > SPREAD_S or abs(median) < MIN_OFFSET_S:
        return None
    halves = round(median / 1800)
    if abs(median - halves * 1800) > NEAR_S:
        return None
    return halves / 2


class SkewTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._diffs: dict[str, deque[float]] = {}

    def observe(self, source_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
        recent = list(rows)[-SAMPLES:]
        diffs = [
            (r["time_observed"] - r["time"]).total_seconds()
            for r in recent
            if isinstance(r.get("time"), datetime) and isinstance(r.get("time_observed"), datetime)
        ]
        if not diffs:
            return
        with self._lock:
            self._diffs.setdefault(source_id, deque(maxlen=SAMPLES)).extend(diffs)

    def offsets(self) -> dict[str, float]:
        with self._lock:
            snapshot = {sid: list(d) for sid, d in self._diffs.items()}
        out = {}
        for sid, diffs in snapshot.items():
            hours = offset_hours(diffs)
            if hours is not None:
                out[sid] = hours
        return out

    def forget(self, source_id: str) -> None:
        """A source's time zone changed: start over."""
        with self._lock:
            self._diffs.pop(source_id, None)


def skew_text(hours: float) -> str:
    n = f"{abs(hours):g}"
    unit = "hour" if abs(hours) == 1 else "hours"
    way = "early" if hours > 0 else "late"
    return f"Event times look {n} {unit} {way}; check this source's time zone"
