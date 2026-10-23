"""Gaps: hours a source that normally sends every hour sent nothing (F55, ADR-0034 row 14).

Needs no history: a source that sent in most complete hours of the window and then sent
nothing for two or more hours in a row has a gap, and so does one that has been silent from
some hour until now. The current hour is still filling, so it only extends a silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_HOURS = 2  # shorter runs are normal for bursty sources
USUAL_SHARE = 0.75  # sent in at least this share of the other complete hours
MIN_OTHER_HOURS = 6  # too little left outside the run to call anything usual


@dataclass(frozen=True, slots=True)
class Gap:
    start: str  # ISO start of the first empty hour
    end: str | None  # ISO end of the last empty hour; None while it continues
    hours: int
    ongoing: bool
    others_flowing: bool  # every other readable source sent events in each of these hours


def find_gaps(
    counts: list[int], hours: list[datetime], others: list[int] | None = None
) -> list[Gap]:
    """Gaps in one source's hourly counts (oldest first; the last hour is the current one).
    `others` is the hourly total of every other source, for "other sources kept flowing"."""
    if len(counts) < 2 or len(counts) != len(hours):
        return []
    complete = len(counts) - 1
    runs: list[tuple[int, int]] = []  # [first, last] empty complete hours
    i = 0
    while i < complete:
        if counts[i] == 0:
            j = i
            while j + 1 < complete and counts[j + 1] == 0:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    gaps = []
    for first, last in runs:
        ongoing = last == complete - 1 and counts[-1] == 0
        length = last - first + 1
        if length < MIN_HOURS and not (ongoing and length >= 1):
            continue
        outside = [n for k, n in enumerate(counts[:complete]) if not first <= k <= last]
        if len(outside) < MIN_OTHER_HOURS:
            continue
        if sum(1 for n in outside if n > 0) < USUAL_SHARE * len(outside):
            continue
        span = range(first, (len(counts) if ongoing else last + 1))
        flowing = bool(others) and all((others or [])[k] > 0 for k in span)
        gaps.append(
            Gap(
                start=hours[first].isoformat(),
                end=None if ongoing else (hours[last] + timedelta(hours=1)).isoformat(),
                hours=length + (1 if ongoing else 0),
                ongoing=ongoing,
                others_flowing=flowing,
            )
        )
    return gaps
