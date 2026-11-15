"""One state per source for Health and the Dashboard footer (handoff item 4).

Both pages read it from GET /api/overview, so "N of M healthy", the quiet list, and the
longest wait are counted once, here. Quiet is not healthy. The built-in `server_events`
records only when someone uses or probes the server (sign-ins, changes, refusals), so a
quiet night is expected: it is never called quiet and never the longest wait; its errors
still count.

An admin may also mark a push source "Quiet is normal for up to N days" (D260): while its
newest event is inside those days (`quiet_ok`), no events in 24 hours and gap hours are not a
problem and it counts as healthy ("idle" when it is silent now). Errors (a listener that is
down, a full spool), reading problems, refused records, and an alert someone set up (a
firing quiet alert, an open gap alert) still count. Past N days, or never sent, it is quiet.
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
    # Marked "Quiet is normal" and its newest event is inside that period (D260).
    quiet_ok: bool = False
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
    idle: int = 0  # healthy sources silent inside their "Quiet is normal" days (D260)


def condition(s: SourceInput) -> Condition:
    if s.state == "disabled":
        return "paused"
    if s.state == "error":
        return "error"
    if s.state == "waiting":
        return "attention"  # not read yet
    silent = (s.ongoing_gap or s.total_24h == 0) and not s.quiet_ok
    if not s.quiet_expected and (s.quiet_since or s.gap_alert or silent):
        return "quiet"
    if s.reading_issue or s.records_skipped or s.files_waiting:
        return "attention"
    if s.gaps and not s.quiet_expected and not s.quiet_ok:
        return "gap"
    return "healthy"


def idle(s: SourceInput, c: Condition) -> bool:
    """Healthy and silent now, inside its "Quiet is normal" days: Health says "Idle"."""
    return c == "healthy" and s.quiet_ok and (s.ongoing_gap or s.total_24h == 0)


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
        if s.last_event_at
        and conditions[s.source_id] != "quiet"
        and not (s.quiet_expected or s.quiet_ok)
    ]
    summary = SourceSummary(
        total=len(sources),  # as Health counted before (paused in the total)
        healthy=sum(1 for s in on if conditions[s.source_id] == "healthy"),
        quiet=quiet,
        gaps=sum(
            s.gaps
            for s in on
            if conditions[s.source_id] != "quiet" and not (s.quiet_expected or s.quiet_ok)
        ),
        longest_wait=Wait(waits[0].source_id, waits[0].last_event_at) if waits else None,
        idle=sum(1 for s in on if idle(s, conditions[s.source_id])),
    )
    return conditions, summary
