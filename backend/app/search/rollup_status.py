"""Rollup status for the Health page (owner, 2026-11-01): per rollup, the closed days still
to build, when it last ran and last built a day, and when today so far was last built, so
it is plain at a glance whether the builds are running. Counts and times only: no source
names, so every signed-in person may see it (rule 13)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

MANIFEST = "_built.json"
TODAY_LATE_S = 15 * 60  # three missed 5-minute builds
LABELS = {
    "auth_rollup": "Attacks and access",
    "m365_rollup": "Microsoft 365",
    "ai_rollup": "AI usage",
}


class Rollup(Protocol):
    @property
    def folder(self) -> Path: ...

    def today_mark(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class Run:
    at: datetime
    pending: int | None = None
    error: bool = False


@dataclass(slots=True)
class RunLog:
    """What the maintenance jobs did since start, by job name ("m365_rollup",
    "m365_rollup.today")."""

    runs: dict[str, Run] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def ran(self, name: str, pending: int | None = None, error: bool = False) -> None:
        with self.lock:
            self.runs[name] = Run(datetime.now(UTC), pending, error)

    def get(self, name: str) -> Run | None:
        with self.lock:
            return self.runs.get(name)


@dataclass(slots=True)
class RollupStatus:
    name: str
    label: str
    days_built: int
    pending: int | None  # None: not checked since the server started
    last_run: str | None
    last_built: str | None
    today_built: str | None
    today_cutoff: str | None
    state: str  # healthy | attention | unhealthy | unknown
    reason: str | None


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t is not None else None


def _built(folder: Path) -> tuple[int, datetime | None]:
    days, newest = 0, 0.0
    for m in folder.glob(f"source=*/day=*/{MANIFEST}"):
        days += 1
        try:
            newest = max(newest, m.stat().st_mtime)
        except OSError:
            continue
    return days, datetime.fromtimestamp(newest, UTC) if newest else None


def status(name: str, rollup: Rollup, log: RunLog, now: datetime) -> RollupStatus:
    days, last_built = _built(rollup.folder)
    run, today_run = log.get(name), log.get(f"{name}.today")
    mark = rollup.today_mark()
    today_at = datetime.fromisoformat(mark["built_at"]) if mark.get("built_at") else None
    pending = run.pending if run is not None else None
    state, reason = "healthy", None
    if (run is not None and run.error) or (today_run is not None and today_run.error):
        state, reason = "unhealthy", "The last build failed; see the server log"
    elif today_at is None or (now - today_at).total_seconds() > TODAY_LATE_S:
        state = "attention"
        reason = "Today so far has not been built in the last 15 minutes"
    elif pending is None:
        state, reason = (
            "unknown",
            "Not checked since the server started (after the next compaction)",
        )
    elif pending:
        state, reason = "attention", f"{pending} closed days still to build"
    return RollupStatus(
        name=name,
        label=LABELS.get(name, name),
        days_built=days,
        pending=pending,
        last_run=_iso(run.at) if run else None,
        last_built=_iso(last_built),
        today_built=_iso(today_at),
        today_cutoff=mark.get("cutoff"),
        state=state,
        reason=reason,
    )
