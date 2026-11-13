"""One state per source for Health and the Dashboard footer (handoff item 4).

Both pages read it from GET /api/overview, so "N of M healthy", the quiet list, and the
longest wait are counted once, here. Quiet is not healthy. The built-in `server_events`
records only when someone uses or probes the server (sign-ins, changes, refusals), so a
quiet night is expected: it is never called quiet and never the longest wait; its errors
still count.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

Condition = Literal["healthy", "quiet", "gap", "attention", "error", "paused"]
BEHIND_S = 3600  # reading more than this far behind needs attention (as Health showed)


@dataclass(frozen=True, slots=True)
class SourceInput:
    source_id: str
    state: str  # waiting | reading | error | disabled
    last_event_at: str | None = None
    total_24h: int = 0
    gaps: int = 0  # gaps in the 24 hours
    ongoing_gap: bool = False
    quiet_since: str | None = None  # the quiet watch is firing
    gap_alert: str | None = None  # an open source gap alert
    quiet_expected: bool = False
    # Reading problems (warnings, retries, a time offset, far behind): needs attention.
    reading_issue: bool = False
    records_skipped: int = 0
    files_waiting: int = 0


@dataclass(frozen=True, slots=True)
class Wait:
    source_id: str
    last_event_at: str | None  # None: never sent


@dataclass(frozen=True, slots=True)
class SourceSummary:
    total: int  # every source; a paused one counts in the total but is never healthy
    healthy: int
    quiet: list[Wait] = field(default_factory=list)  # longest quiet first
    gaps: int = 0  # gaps in 24 hours on sources that are not quiet
    longest_wait: Wait | None = None  # over sources that are not quiet


def condition(s: SourceInput) -> Condition:
    if s.state == "disabled":
        return "paused"
    if s.state == "error":
        return "error"
    if s.state == "waiting":
        return "attention"  # not read yet
    if not s.quiet_expected and (s.quiet_since or s.gap_alert or s.ongoing_gap or s.total_24h == 0):
        return "quiet"
    if s.reading_issue or s.records_skipped or s.files_waiting:
        return "attention"
    if s.gaps and not s.quiet_expected:
        return "gap"
    return "healthy"


def needing_attention(conditions: Iterable[Condition]) -> int:
    """How many sources have something wrong: every condition but healthy and paused. A
    source someone paused on purpose is not a problem to flag (the rail's Health dot)."""
    return sum(1 for c in conditions if c not in ("healthy", "paused"))


def assess(sources: list[SourceInput]) -> tuple[dict[str, Condition], SourceSummary]:
    """Each source's condition, and the one summary both pages print."""
    conditions = {s.source_id: condition(s) for s in sources}
    on = [s for s in sources if conditions[s.source_id] != "paused"]
    oldest_first = sorted(on, key=lambda s: s.last_event_at or "")
    quiet = [
        Wait(s.source_id, s.last_event_at)
        for s in oldest_first
        if conditions[s.source_id] == "quiet"
    ]
    waits = [
        s
        for s in oldest_first
        if s.last_event_at and conditions[s.source_id] != "quiet" and not s.quiet_expected
    ]
    summary = SourceSummary(
        total=len(sources),  # as Health counted before (paused in the total)
        healthy=sum(1 for s in on if conditions[s.source_id] == "healthy"),
        quiet=quiet,
        gaps=sum(s.gaps for s in on if conditions[s.source_id] != "quiet" and not s.quiet_expected),
        longest_wait=Wait(waits[0].source_id, waits[0].last_event_at) if waits else None,
    )
    return conditions, summary
