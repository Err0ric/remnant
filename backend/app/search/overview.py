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
from app.alerts.fallback import is_fallback_error
from app.alerts.targets import TargetStore
from app.auth.users import User
from app.detect.runner import RuleRunner
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.ingest.quiet import LastEvent
from app.ingest.sources import SourceConfig, SourceStore, quiet_expected, quiet_ok
from app.ingest.watcher import IngestService, source_state
from app.meta.db import MetaDB
from app.search.gaps import Gap, find_gaps
from app.search.hour_marks import mark_hours, typical
from app.search.schedules import PAUSED_BY_PERSON, ScheduleService
from app.search.source_state import BEHIND_S

HOURS = 24
BASELINE_DAYS = 7  # earlier days compared hour by hour for unusual hours (D65)
LAST_SEEN_DAYS = 7
CACHE_SECONDS = 60.0
COUNT_SECONDS = 300  # the rail's Health dot: built at most once in five minutes per viewer
MAX_DETECTIONS = 20

VOLUME_SQL = (
    "SELECT source_id, date_trunc('hour', coalesce(time, time_observed)) AS hour,"
    " count(*) AS n FROM events GROUP BY 1, 2 ORDER BY 1, 2 LIMIT 100000"
)
# When each source last received a record, and the newest time its events are dated (an
# event's own time, never later than when it arrived): a queue or an import delivers old
# events now, and "Quiet 2 d" is about the second, "Last received" about the first.
LAST_SEEN_SQL = (
    "SELECT source_id, max(time_observed) AS last,"
    " max(least(coalesce(time, time_observed), time_observed)) AS newest"
    " FROM events GROUP BY 1 LIMIT 10000"
)
LAST_EVENT_TIMEOUT_S = 10.0  # the quiet watch's one read per quiet episode (D262)
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
    quiet_expected: bool = False  # server_events: quiet when nobody uses the server
    # "Quiet is normal for up to N days" (D260), and whether the newest event is inside them.
    quiet_ok_days: int | None = None
    quiet_ok: bool = False
    # Warnings, retries, a time offset, or reading far behind: what /api/sources shows
    # admins in words. Used for the source's condition (app.search.source_state) only.
    reading_issue: bool = False
    # The newest time its events are dated, at most when they arrived: what "Quiet 2 d",
    # "Idle", and "No events for" measure, and "Quiet is normal" days count from.
    newest_event_at: str | None = None
    # Every file it lists is read by this other source (one reader per file, SPEC 3.5).
    read_by: str | None = None


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
    # Someone paused it themselves: not a blind state (a pause nobody chose is, D236).
    by_person: bool = False


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
    # F60: the comparison waits for 7 full days of history and leaves out sources newer than
    # that, so a partial first day or a source added today does not read as a jump.
    history_days: int = 0  # full days of history before the window, at most 7
    events_compared_24h: int = 0  # the last 24 hours of the sources compared
    events_usual_24h: float | None = None  # their average on the 7 earlier days
    new_sources: list[str] = field(default_factory=list)  # left out: under 7 days of data
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
        # For the numbers-only count (the rail's Health dot). Kept apart from `_cache`: a count
        # must never make the next Overview read a cached one, since that read is audited
        # only when it computes.
        self._count_cache: dict[
            tuple[str, str, tuple[str, ...] | None], tuple[float, Overview]
        ] = {}

    def forget(self) -> None:
        """Drop every cached answer and count, after a change to how sources are judged
        (D260), so Health, the Dashboard, and the rail show it on their next read."""
        with self._lock:
            self._cache = {}
            self._count_cache = {}

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

    def for_count(self, user: User) -> Overview:
        """The Overview behind `/api/health/count`. A fresh answer the viewer already has is
        used as it is; otherwise one is built and kept for COUNT_SECONDS in a cache of its
        own, so the audited cache above is never filled from here."""
        allowed = permitted_sources(self._meta, user)
        key = (user.user_id, user.role, None if allowed is None else tuple(sorted(allowed)))
        now = monotonic.monotonic()
        with self._lock:
            for cache in (self._cache, self._count_cache):
                hit = cache.get(key)
                if hit and hit[0] > now:
                    return hit[1]
        result = self._build(user, allowed)
        with self._lock:
            self._count_cache = {k: v for k, v in self._count_cache.items() if v[0] > now}
            self._count_cache[key] = (now + COUNT_SECONDS, result)
        return result

    # --- building ---------------------------------------------------------------------------

    def _build(self, user: User, allowed: list[str] | None) -> Overview:
        now = self._clock().astimezone(UTC)
        first = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=HOURS - 1)
        hours = [first + timedelta(hours=i) for i in range(HOURS)]
        configured = [
            s for s in self._sources.list() if allowed is None or s.source_id in set(allowed)
        ]
        volume, read, usual = self._volume(allowed, first, now, hours)
        last_seen, newest = self._last_seen(allowed, now)
        more_seen, more_newest = self._last_seen_marked(configured, last_seen, now)
        last_seen |= more_seen
        newest |= more_newest
        rates = self._rates(allowed, now)
        statuses = self._ingest().status()
        health = []
        for s in configured:
            st = statuses.get(s.source_id)
            error = st.error if st else None
            # Server paths are for administrators only; the fallback text has none (it names
            # the source and template, ADR-0050 row 4), so everyone who reads the source sees it.
            if error and allowed is not None and not is_fallback_error(error):
                error = "This source cannot be read right now. An administrator can see why."
            health.append(
                SourceHealth(
                    source_id=s.source_id,
                    state=source_state(s.enabled, st),
                    last_event_at=last_seen.get(s.source_id),
                    newest_event_at=newest.get(s.source_id),
                    files_waiting=st.files_waiting if st else 0,
                    records_skipped=st.records_skipped if st else 0,
                    error=error,
                    rate_per_min=rates.get(s.source_id, 0.0),
                    quiet_expected=quiet_expected(s),
                    quiet_ok_days=s.quiet_ok_days,
                    quiet_ok=quiet_ok(s, newest.get(s.source_id), now),
                    reading_issue=bool(
                        st
                        and (
                            st.warnings
                            or st.retry_at
                            or st.time_offset_h
                            or (st.behind_s or 0) > BEHIND_S
                        )
                    ),
                    read_by=st.read_by if st and s.enabled else None,
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
            history_days=usual.days,
            events_compared_24h=sum(v.total for v in volume if v.source_id in usual.compared),
            events_usual_24h=usual.average,
            new_sources=usual.new,
            sources_in_scope=read,
        )

    def _volume(
        self, allowed: list[str] | None, start: datetime, end: datetime, hours: list[datetime]
    ) -> tuple[list[SourceVolume], list[str], "UsualDay"]:
        early = start - timedelta(days=BASELINE_DAYS)
        result = self._engine.run(
            VOLUME_SQL, QueryScope(sources=allowed, start=early, end=end), page=True
        )
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
        return volume, list(result.sources), _usual_day(before, series, start, end)

    def _rates(self, allowed: list[str] | None, now: datetime) -> dict[str, float]:
        # Received in the last minutes, whatever time the event itself says; the range only
        # limits which day folders are read.
        scope = QueryScope(sources=allowed, start=now - timedelta(days=2), end=now)
        since = (now - timedelta(minutes=RATE_MINUTES)).isoformat()
        result = self._engine.run(RATE_SQL, scope, {"since": since}, page=True)
        return {str(r[0]): round(int(r[1]) / RATE_MINUTES, 1) for r in result.rows}

    def _last_seen(
        self, allowed: list[str] | None, now: datetime
    ) -> tuple[dict[str, str], dict[str, str]]:
        scope = QueryScope(sources=allowed, start=now - timedelta(days=LAST_SEEN_DAYS), end=now)
        return _seen(self._engine.run(LAST_SEEN_SQL, scope, page=True).rows)

    def newest_event(self, source_id: str, days: int, now: datetime) -> LastEvent | None:
        """The newest time one source's events are dated (at most when they arrived), and
        when its last record arrived, looked up over its own days: the first is what "Quiet
        is normal" is measured from, as Health reads it, for the quiet watch's hold (D262).
        Reads only that source's day folders, as the system, on the background slot (never a
        page query's) with a short timeout; raises on failure."""
        scope = QueryScope(sources=[source_id], start=now - timedelta(days=days), end=now)
        result = self._engine.run(
            LAST_SEEN_SQL, scope, timeout_s=LAST_EVENT_TIMEOUT_S, background=True
        )
        found = [
            LastEvent(newest=_utc(r[2]), received=_utc(r[1]))
            for r in result.rows
            if r[1] is not None and r[2] is not None
        ]
        return found[0] if found else None

    def _last_seen_marked(
        self, configured: list[SourceConfig], seen: dict[str, str], now: datetime
    ) -> tuple[dict[str, str], dict[str, str]]:
        """The newest event of sources marked "Quiet is normal" for longer than the 7 days
        looked up above (D260), when nothing came in those 7 days. Reads only those sources'
        folders, so most loads run nothing more."""
        days = {
            s.source_id: s.quiet_ok_days or 0
            for s in configured
            if (s.quiet_ok_days or 0) > LAST_SEEN_DAYS and s.source_id not in seen
        }
        if not days:
            return {}, {}
        start = now - timedelta(days=max(days.values()))
        result = self._engine.run(
            LAST_SEEN_SQL, QueryScope(sources=sorted(days), start=start, end=now), page=True
        )
        return _seen(result.rows)

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
            PausedSchedule(
                s.schedule_id,
                s.name,
                s.kind,
                s.paused_reason,
                # No reason at all is a pause from before reasons were kept: a person's.
                s.paused_reason in (None, PAUSED_BY_PERSON),
            )
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


def _seen(rows: list[list[Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """Last received and newest dated time per source, from LAST_SEEN_SQL's rows."""
    last = {str(r[0]): _utc(r[1]).isoformat() for r in rows if r[1] is not None}
    newest = {str(r[0]): _utc(r[2]).isoformat() for r in rows if r[2] is not None}
    return last, newest


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


@dataclass(frozen=True, slots=True)
class UsualDay:
    days: int  # full days of history before the window, at most BASELINE_DAYS
    average: float | None  # None until BASELINE_DAYS full days exist
    compared: frozenset[str]  # sources with the full history
    new: list[str]  # sources with less, left out of the comparison


def _usual_day(
    earlier: dict[str, dict[datetime, int]],
    current: dict[str, list[int]],
    start: datetime,
    end: datetime,
) -> UsualDay:
    """The same 24 hours on each of the 7 earlier days, averaged, for sources that have all
    7 days (F60). A source whose first event falls inside that week is new: left out and
    named, so adding a source today does not read as a jump in events."""
    week = start - timedelta(days=BASELINE_DAYS)
    first = {src: min(hours) for src, hours in earlier.items() if hours}
    names = set(current) | set(first)
    if not first:
        return UsualDay(0, None, frozenset(), sorted(names))
    oldest = min(first.values())
    days = min(BASELINE_DAYS, int((start - oldest).total_seconds() // 86400))
    compared = frozenset(src for src, at in first.items() if at < week + timedelta(days=1))
    new = sorted(names - compared)
    if days < BASELINE_DAYS or not compared:
        return UsualDay(days, None, compared, new)
    totals = []
    for back in range(1, BASELINE_DAYS + 1):
        lo, hi = start - timedelta(days=back), end - timedelta(days=back)
        totals.append(
            sum(n for src in compared for at, n in earlier.get(src, {}).items() if lo <= at <= hi)
        )
    return UsualDay(days, round(sum(totals) / len(totals), 1), compared, new)


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
