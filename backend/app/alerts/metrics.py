"""How alerts are handled (BACKLOG P2, D261): time to close, opened against closed by day,
open and overdue now. Numbers only, read from `alert_items` in one query; no lake read.

What each number counts, for the alerts the viewer may know of (`can_see`) and read (every
source of the alert in the viewer's sources; an alert outside them is left out). As D243
defines it, `restricted` is true when an open alert the viewer may know of reads a source
the viewer may not read; it never depends on the range, so the range cannot date a hidden
alert. It looks at every open alert, where the Queue's flag reads the newest 200, so above
200 open alerts the two can differ.

- Left out of everything: alerts closed as Muted (closed the moment they were raised,
  because their subject was muted, so they never waited in the queue) and as Merged (an
  older duplicate folded into another alert, which is counted).
- Opened: alerts first raised in the range. A grouped alert is one alert however many
  repeats joined it; a reopened alert is counted once, on the day it was first raised.
- Closed: alerts closed now whose close falls in the range, by a person or by the server
  (Resolved when the condition ended, Superseded by rule change). An alert closed before
  close times were kept counts on the day it was raised, as Alerts > Closed lists it. A
  reopened alert counts by its latest close, and not at all while it is open again.
- Time to close: from first raised to the latest close, for the closed alerts above that a
  person closed and that have a close time. The other closed alerts, closed by the server or
  with no close time recorded, are counted apart (`closed_not_timed`). Median and 90th
  percentile by linear interpolation between ranks: with one value both are that value;
  with two, the median is their mean.
- Open now: every alert open now, whatever the range, by severity and by kind. The Queue
  and `/alerts/count` read only the newest 200 open alerts (`AlertItems.items`), so they
  agree up to 200 open alerts; above that this is the full count and theirs is lower.
- Overdue now: open alerts raised longer ago than their severity's days (`alerts.*` in the
  config): High and Medium by their own setting, an alert with no severity by Low. No alert
  is stored as Critical today (the store holds High, Medium, or none), so that setting
  applies to none yet. A reopened alert's age runs from when it was first raised.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.alerts.items import can_see
from app.auth.users import User
from app.meta.db import MetaDB

SEVERITIES = ("high", "medium", "other")  # as the Queue counts them (`by_severity`)
KINDS = ("rule", "schedule", "ai_watch", "gap")
LEFT_OUT = ("muted", "merged")


@dataclass(slots=True)
class Thresholds:
    critical: int = 1
    high: int = 3
    medium: int = 7
    low: int = 30

    def days(self, severity: str) -> int:
        return {"high": self.high, "medium": self.medium}.get(severity, self.low)


@dataclass(slots=True)
class Spread:
    count: int = 0
    median_s: int | None = None
    p90_s: int | None = None


@dataclass(slots=True)
class Handling:
    start: datetime
    end: datetime
    thresholds: Thresholds
    time_to_close: Spread
    time_to_close_by_severity: dict[str, Spread]
    closed_not_timed: int
    days: list[tuple[str, int, int]]  # (install-time-zone day, opened, closed)
    opened: int
    closed: int
    open_by_severity: dict[str, int]
    open_by_kind: dict[str, int]
    overdue_by_severity: dict[str, int]
    restricted: bool
    open: int = field(init=False)
    overdue: int = field(init=False)

    def __post_init__(self) -> None:
        self.open = sum(self.open_by_severity.values())
        self.overdue = sum(self.overdue_by_severity.values())


def percentile(values: list[float], q: float) -> float | None:
    """The q-th quantile (0 to 1) of `values`, interpolated between ranks; None when empty."""
    if not values:
        return None
    s = sorted(values)
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def spread(seconds: list[float]) -> Spread:
    med, p90 = percentile(seconds, 0.5), percentile(seconds, 0.9)
    return Spread(
        len(seconds),
        None if med is None else round(med),
        None if p90 is None else round(p90),
    )


def _at(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text)


def handling(
    meta: MetaDB,
    user: User,
    allowed: list[str] | None,
    start: datetime,
    end: datetime,
    now: datetime,
    day_of: Callable[[datetime], str],
    thresholds: Thresholds,
) -> Handling:
    """The numbers for [start, end] (both ends included, as Alerts > Closed filters) and
    now, for `user`, whose readable sources are `allowed` (None: every source)."""
    lower = start.astimezone(UTC).isoformat()  # stored as UTC ISO text
    with meta.connect() as con:
        rows = con.execute(
            "SELECT kind, severity, state, created_at, closed_at, closed_by, close_reason,"
            " owner_id, shared, sources FROM alert_items"
            " WHERE state = 'open' OR created_at >= ? OR COALESCE(closed_at, created_at) >= ?",
            (lower, lower),
        ).fetchall()
    readable = None if allowed is None else set(allowed)
    first, last = day_of(start), day_of(end)
    opened: dict[str, int] = {}
    closed: dict[str, int] = {}
    took: dict[str, list[float]] = {s: [] for s in SEVERITIES}
    not_timed = 0
    open_sev = dict.fromkeys(SEVERITIES, 0)
    open_kind = dict.fromkeys(KINDS, 0)
    overdue = dict.fromkeys(SEVERITIES, 0)
    restricted = False
    for r in rows:
        if r["close_reason"] in LEFT_OUT or not can_see(r["owner_id"], bool(r["shared"]), user):
            continue
        if readable is not None and not set(json.loads(r["sources"] or "[]")) <= readable:
            restricted = restricted or r["state"] == "open"  # D243: open alerts only
            continue
        sev = r["severity"] if r["severity"] in ("high", "medium") else "other"
        raised = datetime.fromisoformat(r["created_at"])  # NOT NULL
        if start <= raised <= end:
            day = day_of(raised)
            opened[day] = opened.get(day, 0) + 1
        if r["state"] == "open":
            open_sev[sev] += 1
            if r["kind"] in open_kind:
                open_kind[r["kind"]] += 1
            if now - raised > timedelta(days=thresholds.days(sev)):
                overdue[sev] += 1
            continue
        shut = _at(r["closed_at"])
        when = shut or raised
        if not start <= when <= end:
            continue
        day = day_of(when)
        closed[day] = closed.get(day, 0) + 1
        if shut is not None and r["closed_by"] is not None:
            took[sev].append((shut - raised).total_seconds())
        else:
            not_timed += 1
    d0, d1 = datetime.fromisoformat(first).date(), datetime.fromisoformat(last).date()
    days: list[tuple[str, int, int]] = []
    for n in range((d1 - d0).days + 1):  # never steps past the last day (year 9999)
        key = (d0 + timedelta(days=n)).isoformat()
        days.append((key, opened.get(key, 0), closed.get(key, 0)))
    return Handling(
        start=start,
        end=end,
        thresholds=thresholds,
        time_to_close=spread([v for s in SEVERITIES for v in took[s]]),
        time_to_close_by_severity={s: spread(took[s]) for s in SEVERITIES},
        closed_not_timed=not_timed,
        days=days,
        opened=sum(opened.values()),
        closed=sum(closed.values()),
        open_by_severity=open_sev,
        open_by_kind=open_kind,
        overdue_by_severity=overdue,
        restricted=restricted,
    )
