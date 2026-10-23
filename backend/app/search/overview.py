"""The Overview page's numbers (ADR-0008 rows 7 and 8).

Everything is read as the viewer: event counts come from the viewer's `events` view through
the guard, like any query; schedules and rule runs follow the same visibility rules as their
own pages, and a run that read a source the viewer may not read is left out, not counted.
Alert delivery health is for administrators only.

Results are cached per viewer and per set of readable sources for `CACHE_SECONDS`, so a
refresh does not rerun the queries or write another audit row, and a change of access is
never served from the cache.
"""

import threading
import time as monotonic
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.alerts.dispatch import AlertDispatcher
from app.alerts.targets import TargetStore
from app.auth.users import User
from app.detect.runner import RuleRunner
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.ingest.sources import SourceStore
from app.ingest.watcher import IngestService, source_state
from app.meta.db import MetaDB
from app.search.gaps import Gap, find_gaps
from app.search.hour_marks import mark_hours, typical
from app.search.schedules import ScheduleService

HOURS = 24
BASELINE_DAYS = 7  # earlier days compared hour by hour for unusual hours (D65)
LAST_SEEN_DAYS = 7
CACHE_SECONDS = 60.0
MAX_DETECTIONS = 20

VOLUME_SQL = (
    "SELECT source_id, date_trunc('hour', coalesce(time, time_observed)) AS hour,"
    " count(*) AS n FROM events GROUP BY 1, 2 ORDER BY 1, 2 LIMIT 100000"
)
LAST_SEEN_SQL = "SELECT source_id, max(time_observed) AS last FROM events GROUP BY 1 LIMIT 10000"
RATE_MINUTES = 15  # "current rate": events received in the last 15 minutes, per minute
RATE_SQL = (
    "SELECT source_id, count(*) FROM events"
    " WHERE time_observed >= CAST($since AS TIMESTAMPTZ) GROUP BY 1 LIMIT 10000"
)


@dataclass(frozen=True, slots=True)
class SourceVolume:
    source_id: str
    counts: list[int]  # one per hour, oldest first
    typical: list[float | None]  # median of the same hour on earlier days (D65)
    marks: list[str]  # busy | quiet | "" per hour
    total: int = 0  # events in the 24 hours
    gaps: list[Gap] = field(default_factory=list)  # F55: hours with nothing from a steady source


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: str
    state: str  # waiting | reading | error | disabled
    last_event_at: str | None  # when the newest event was received (up to 7 days back)
    files_waiting: int
    records_skipped: int
    error: str | None
    rate_per_min: float = 0.0  # received over the last RATE_MINUTES


@dataclass(frozen=True, slots=True)
class Detection:
    kind: str  # rule | search
    name: str
    level: str | None  # Sigma level, rules only
    count: int
    reason: str | None
    started_at: str
    run_id: str
    schedule_id: str | None


@dataclass(frozen=True, slots=True)
class PausedSchedule:
    schedule_id: str
    name: str
    kind: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class TargetHealth:
    target_id: str
    name: str
    kind: str
    consecutive_failures: int
    failing: bool
    last_error: str | None


@dataclass(frozen=True, slots=True)
class AlertHealth:
    targets: list[TargetHealth]  # targets whose last send failed
    failed_deliveries: int  # in the last 24 hours


@dataclass(frozen=True, slots=True)
class Overview:
    generated_at: str
    hours: list[str]  # start of each hour bucket, UTC, oldest first
    volume: list[SourceVolume]
    sources: list[SourceHealth]
    detections: list[Detection]
    paused: list[PausedSchedule]
    alerts: AlertHealth | None  # None for non-admins
    events_24h: int = 0
    # Average of the same 24 hours on up to 7 earlier days with data; None without history.
    events_usual_24h: float | None = None
    sources_in_scope: list[str] = field(default_factory=list)


class OverviewService:
    def __init__(
        self,
        meta: MetaDB,
        engine: QueryEngine,
        sources: SourceStore,
        ingest: Callable[[], IngestService],
        schedules: ScheduleService,
        rule_runner: RuleRunner,
        targets: TargetStore,
        dispatcher: AlertDispatcher,
        clock: Callable[[], datetime],
    ) -> None:
        self._meta = meta
        self._engine = engine
        self._sources = sources
        self._ingest = ingest
        self._schedules = schedules
        self._rules = rule_runner
        self._targets = targets
        self._dispatcher = dispatcher
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str, tuple[str, ...] | None], tuple[float, Overview]] = {}

    def get(self, user: User) -> tuple[Overview, bool]:
        """The Overview for this viewer, and whether it was computed now (not cached)."""
        allowed = permitted_sources(self._meta, user)
        key = (user.user_id, user.role, None if allowed is None else tuple(sorted(allowed)))
        now = monotonic.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return hit[1], False
        result = self._build(user, allowed)
        with self._lock:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            self._cache[key] = (now + CACHE_SECONDS, result)
        return result, True

    # --- building ---------------------------------------------------------------------------

    def _build(self, user: User, allowed: list[str] | None) -> Overview:
        now = self._clock().astimezone(UTC)
        first = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=HOURS - 1)
        hours = [first + timedelta(hours=i) for i in range(HOURS)]
        configured = [
            s for s in self._sources.list() if allowed is None or s.source_id in set(allowed)
        ]
        volume, read, usual_24h = self._volume(allowed, first, now, hours)
        last_seen = self._last_seen(allowed, now)
        rates = self._rates(allowed, now)
        statuses = self._ingest().status()
        health = []
        for s in configured:
            st = statuses.get(s.source_id)
            error = st.error if st else None
            if error and allowed is not None:  # server paths are for administrators only
                error = "This source cannot be read right now. An administrator can see why."
            health.append(
                SourceHealth(
                    source_id=s.source_id,
                    state=source_state(s.enabled, st),
                    last_event_at=last_seen.get(s.source_id),
                    files_waiting=st.files_waiting if st else 0,
                    records_skipped=st.records_skipped if st else 0,
                    error=error,
                    rate_per_min=rates.get(s.source_id, 0.0),
                )
            )
        since = now - timedelta(hours=HOURS)
        return Overview(
            generated_at=now.isoformat(),
            hours=[h.isoformat() for h in hours],
            volume=volume,
            sources=health,
            detections=self._detections(user, allowed, since),
            paused=self._paused(user),
            alerts=self._alerts(since) if user.role == "admin" else None,
            events_24h=sum(v.total for v in volume),
            events_usual_24h=usual_24h,
            sources_in_scope=read,
        )

    def _volume(
        self, allowed: list[str] | None, start: datetime, end: datetime, hours: list[datetime]
    ) -> tuple[list[SourceVolume], list[str], float | None]:
        early = start - timedelta(days=BASELINE_DAYS)
        result = self._engine.run(VOLUME_SQL, QueryScope(sources=allowed, start=early, end=end))
        index = {h: i for i, h in enumerate(hours)}
        series: dict[str, list[int]] = {}
        before: dict[str, dict[datetime, int]] = {}  # earlier hours, for the baseline
        for source_id, hour, n in result.rows:
            at = _utc(hour)
            slot = index.get(at)
            if slot is not None:
                series.setdefault(str(source_id), [0] * len(hours))[slot] += int(n)
            elif at < start:
                seen = before.setdefault(str(source_id), {})
                seen[at] = seen.get(at, 0) + int(n)
        everyone = [sum(c[i] for c in series.values()) for i in range(len(hours))]
        volume = []
        for source_id, counts in sorted(series.items()):
            usual = _baseline(before.get(source_id, {}), hours)
            marks = mark_hours(counts, usual, current=len(hours) - 1)
            others = [everyone[i] - n for i, n in enumerate(counts)]
            gaps = find_gaps(counts, hours, others)
            volume.append(SourceVolume(source_id, counts, usual, marks, sum(counts), gaps))
        return volume, list(result.sources), _usual_day(before, start, end)

    def _rates(self, allowed: list[str] | None, now: datetime) -> dict[str, float]:
        # Received in the last minutes, whatever time the event itself says; the range only
        # limits which day folders are read.
        scope = QueryScope(sources=allowed, start=now - timedelta(days=2), end=now)
        since = (now - timedelta(minutes=RATE_MINUTES)).isoformat()
        result = self._engine.run(RATE_SQL, scope, {"since": since})
        return {str(r[0]): round(int(r[1]) / RATE_MINUTES, 1) for r in result.rows}

    def _last_seen(self, allowed: list[str] | None, now: datetime) -> dict[str, str]:
        scope = QueryScope(sources=allowed, start=now - timedelta(days=LAST_SEEN_DAYS), end=now)
        result = self._engine.run(LAST_SEEN_SQL, scope)
        return {str(r[0]): _utc(r[1]).isoformat() for r in result.rows if r[1] is not None}

    def _detections(
        self, user: User, allowed: list[str] | None, since: datetime
    ) -> list[Detection]:
        def readable(read: list[str]) -> bool:
            return allowed is None or set(read) <= set(allowed)

        found: list[Detection] = []
        for r in self._rules.runs(user, limit=200):  # already filtered to readable runs
            if r.match_count > 0 and r.status == "ok" and _after(r.started_at, since):
                found.append(
                    Detection(
                        "rule", r.title, r.level, r.match_count, None, r.started_at, r.run_id, None
                    )
                )
        for s in self._schedules.all():
            if s.kind != "search" or not _sees(s.owner_id, s.shared, user):
                continue
            for run in self._schedules.runs(s.schedule_id):
                if not _after(run.started_at, since):
                    break  # newest first
                if run.flagged and readable(run.sources_in_scope):
                    found.append(
                        Detection(
                            "search",
                            s.name,
                            None,
                            run.row_count or 0,
                            run.flag_reason,
                            run.started_at,
                            run.run_id,
                            s.schedule_id,
                        )
                    )
        found.sort(key=lambda d: d.started_at, reverse=True)
        return found[:MAX_DETECTIONS]

    def _paused(self, user: User) -> list[PausedSchedule]:
        return [
            PausedSchedule(s.schedule_id, s.name, s.kind, s.paused_reason)
            for s in self._schedules.all()
            if s.paused and _sees(s.owner_id, s.shared, user)
        ]

    def _alerts(self, since: datetime) -> AlertHealth:
        targets = [
            TargetHealth(
                t.target_id, t.name, t.kind, t.consecutive_failures, t.failing, t.last_error
            )
            for t in self._targets.all()
            if t.consecutive_failures > 0
        ]
        return AlertHealth(targets, self._dispatcher.failed_since(since))


def _baseline(earlier: dict[datetime, int], hours: list[datetime]) -> list[float | None]:
    """Typical count per hour: the same hour on each earlier day since the source's first
    event in the window (an hour with no events that day counts as 0)."""
    if not earlier:
        return [None] * len(hours)
    first_day = min(earlier).replace(hour=0)
    out: list[float | None] = []
    for h in hours:
        history = []
        for back in range(1, BASELINE_DAYS + 1):
            at = h - timedelta(days=back)
            if at.replace(hour=0) < first_day:
                break
            history.append(earlier.get(at, 0))
        out.append(typical(history))
    return out


def _usual_day(
    earlier: dict[str, dict[datetime, int]], start: datetime, end: datetime
) -> float | None:
    """Average events in the same window on each earlier day that has any data."""
    totals = []
    for back in range(1, BASELINE_DAYS + 1):
        lo, hi = start - timedelta(days=back), end - timedelta(days=back)
        day = [n for src in earlier.values() for at, n in src.items() if lo <= at <= hi]
        if day:
            totals.append(sum(day))
    return round(sum(totals) / len(totals), 1) if totals else None


def _sees(owner_id: str, shared: bool, user: User) -> bool:
    return user.role == "admin" or owner_id == user.user_id or shared


def _after(stamp: str, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(stamp).astimezone(UTC) >= since
    except ValueError:
        return False


def _utc(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise TypeError("expected a timestamp")
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
