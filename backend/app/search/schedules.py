"""Scheduled saved searches and Sigma rules (SPEC 5.5, Slice 4).

A schedule runs a saved search's SQL or an imported rule on a cron schedule, as its owner.
Nothing is ever sent to a model: schedules run stored SQL or a stored rule only.

Every run first checks that the schedule may still run, and pauses it with a reason when:
- the owner is gone or disabled, or can no longer run schedules (auditor role), or the
  schedule was made in the no-accounts local mode and accounts now exist;
- the saved search is deleted, no longer visible to the owner, or its SQL or parameters
  changed since the schedule was made or last resumed (someone must review the change);
- the rule is gone or disabled;
- the owner lost access to a source the schedule read when it was made or resumed.
Resuming takes a new snapshot of the definition and of the owner's sources.

Ranges are half-open, [start, end): a run ends `lag_seconds` before its fire time (so late
events are still caught) and the next run starts where the last successful one ended, so
nothing falls between runs and nothing is counted twice. A failed run does not move the
start forward; the next run covers its range again.

Each run stores row count, duration, the sources read, and a capped sample (rule runs store
the match list and point at the rule run). Only the newest `keep_runs` runs are kept per
schedule; every run is in the audit log regardless (`schedule.run`).
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import structlog

from app.alerts.dispatch import AlertDispatcher
from app.alerts.render import Alert, AlertKind
from app.auth.users import LOCAL_USER, User, UserStore
from app.core.branding import PRODUCT_NAME
from app.core.config import SchedulesConfig
from app.core.errors import AppError, ConflictError, NotFoundError, ParamInvalidError
from app.core.ids import new_id
from app.detect.runner import RuleRunner
from app.detect.store import RuleStore
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources, scope_sources
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.search.cron import PRESETS, Cron
from app.search.params import bind, compile_sql
from app.search.saved import SavedSearch, SavedSearchStore

log = structlog.get_logger()

Kind = Literal["search", "rule"]
ThresholdKind = Literal["above", "below", "change_pct"]
LATE = timedelta(minutes=5)  # a run this late covers up to now, not just to its fire time
MAX_LAST_INTERVAL = timedelta(days=31)
DUE_PER_TICK = 20


@dataclass(frozen=True, slots=True)
class Schedule:
    schedule_id: str
    kind: Kind
    target_id: str
    name: str
    owner_id: str
    shared: bool
    cron: str
    lookback_minutes: int | None
    params: dict[str, Any]
    target_sha256: str
    scope_sources: list[str] | None  # None: every source (owner was an admin)
    threshold_kind: ThresholdKind | None
    threshold_value: float | None
    paused: bool
    paused_reason: str | None
    next_run_at: str | None
    last_run_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ScheduleRun:
    run_id: str
    schedule_id: str
    started_at: str
    range_start: str | None
    range_end: str | None
    status: str
    row_count: int | None
    elapsed_ms: int | None
    sources_in_scope: list[str]
    columns: list[str]
    sample: list[list[Any]]
    truncated: bool
    flagged: bool
    flag_reason: str | None
    error: str | None
    rule_run_id: str | None


class _Stop(Exception):  # noqa: N818  # a signal to pause, not an error
    """The schedule may not run as it stands; the message says why."""


def search_sha(search: SavedSearch) -> str:
    """What a review covers: the SQL and the parameter definitions."""
    defn = {"sql": search.sql, "params": [p.model_dump() for p in search.params]}
    return hashlib.sha256(json.dumps(defn, sort_keys=True).encode()).hexdigest()


class ScheduleService:
    def __init__(
        self,
        meta: MetaDB,
        config: SchedulesConfig,
        users: UserStore,
        local_mode: Callable[[], bool],
        searches: SavedSearchStore,
        rules: RuleStore,
        rule_runner: RuleRunner,
        engine: QueryEngine,
        audit: AuditLog,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        *,
        dispatcher: AlertDispatcher | None = None,
        link: str | None = None,
    ) -> None:
        self._meta = meta
        self._config = config
        self._tz = ZoneInfo(config.timezone)
        self._users = users
        self._local_mode = local_mode
        self._searches = searches
        self._rules = rules
        self._rule_runner = rule_runner
        self._engine = engine
        self._audit = audit
        self._clock = clock
        self._dispatcher = dispatcher
        self._link = link

    # --- definition snapshot -----------------------------------------------------------------

    def snapshot(
        self, kind: Kind, target_id: str, owner: User
    ) -> tuple[str, list[str] | None, str]:
        """(definition sha256, the owner's sources for it now, display name of the target).
        Raises NotFoundError when the owner cannot see the target."""
        allowed = permitted_sources(self._meta, owner)
        if kind == "search":
            search = self._searches.get(target_id, owner)
            return search_sha(search), scope_sources(allowed, search.sources), search.name
        row, _ = self._rules.get(target_id)
        return row.sha256, allowed, row.title

    def next_run(self, cron: str, after: datetime) -> str:
        return Cron.parse(cron).next_after(after, self._tz).isoformat()

    # --- changes (the API checks who may make them) ----------------------------------------

    def create(
        self,
        owner: User,
        kind: Kind,
        target_id: str,
        name: str | None,
        cron: str,
        lookback_minutes: int | None,
        params: dict[str, Any],
        shared: bool,
        threshold_kind: ThresholdKind | None,
        threshold_value: float | None,
    ) -> Schedule:
        expr = _cron(cron)
        if (threshold_kind is None) != (threshold_value is None):
            raise ParamInvalidError("Give both a threshold kind and a value, or neither")
        sha, scope, target_name = self.snapshot(kind, target_id, owner)
        now = self._clock().astimezone(UTC)
        if kind == "search":
            search = self._searches.get(target_id, owner)
            bind(search.params, params, now, now, search.sql)  # refuses bad params now
        elif params:
            raise ParamInvalidError("Rules take no parameters")
        sid = new_id()
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO schedules (schedule_id, kind, target_id, name, owner_id, shared,"
                " cron, lookback_minutes, params, target_sha256, scope_sources, threshold_kind,"
                " threshold_value, paused, next_run_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    sid,
                    kind,
                    target_id,
                    name or target_name[:120],
                    owner.user_id,
                    int(shared),
                    expr,
                    lookback_minutes,
                    json.dumps(params),
                    sha,
                    None if scope is None else json.dumps(scope),
                    threshold_kind,
                    threshold_value,
                    self.next_run(expr, now),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get(sid)

    def update(
        self,
        s: Schedule,
        name: str | None = None,
        cron: str | None = None,
        lookback_minutes: int | None = None,  # 0 clears it: last interval
        shared: bool | None = None,
        threshold_kind: str | None = None,  # "none" clears it
        threshold_value: float | None = None,
        paused: bool | None = None,
    ) -> Schedule:
        sets: dict[str, Any] = {}
        if name is not None:
            sets["name"] = name
        expr = s.cron
        if cron is not None:
            expr = sets["cron"] = _cron(cron)
        if lookback_minutes is not None:
            sets["lookback_minutes"] = lookback_minutes or None
        if shared is not None:
            sets["shared"] = int(shared)
        if threshold_kind == "none":
            sets["threshold_kind"] = sets["threshold_value"] = None
        elif threshold_kind is not None:
            if threshold_value is None:
                raise ParamInvalidError("Give a threshold value with the threshold kind")
            sets["threshold_kind"], sets["threshold_value"] = threshold_kind, threshold_value
        if paused is True and not s.paused:
            sets["paused"], sets["paused_reason"] = 1, "Paused by a person"
        elif paused is False and s.paused:
            # Resuming is a review: a new snapshot of the definition and of the owner's
            # sources, taken as the owner, so a change is only ever accepted on purpose.
            try:
                owner = self._owner(s)
                sha, scope, _ = self.snapshot(s.kind, s.target_id, owner)
            except (_Stop, NotFoundError) as exc:
                raise ConflictError(f"Cannot resume: {exc}") from exc
            sets |= {
                "paused": 0,
                "paused_reason": None,
                "target_sha256": sha,
                "scope_sources": None if scope is None else json.dumps(scope),
            }
        running = not s.paused if paused is None else not paused
        if running and ("cron" in sets or "paused" in sets):
            sets["next_run_at"] = self.next_run(expr, self._clock().astimezone(UTC))
        if not sets:
            return s
        sets["updated_at"] = self._clock().astimezone(UTC).isoformat()
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._meta.connect() as con:
            con.execute(
                f"UPDATE schedules SET {cols} WHERE schedule_id = ?",  # noqa: S608  # keys are fixed names set above
                (*sets.values(), s.schedule_id),
            )
        return self.get(s.schedule_id)

    def delete(self, s: Schedule) -> None:
        with self._meta.connect() as con:
            con.execute("DELETE FROM schedules WHERE schedule_id = ?", (s.schedule_id,))

    # --- alert targets (ADR-0007) ------------------------------------------------------------

    def check_targets(self, target_ids: list[str]) -> None:
        with self._meta.connect() as con:
            known = {r[0] for r in con.execute("SELECT target_id FROM alert_targets").fetchall()}
        if set(target_ids) - known:
            raise ParamInvalidError("Unknown alert target")

    def set_targets(self, schedule_id: str, target_ids: list[str]) -> None:
        wanted = sorted(set(target_ids))
        self.check_targets(wanted)
        with self._meta.connect() as con:
            con.execute("DELETE FROM schedule_alert_targets WHERE schedule_id = ?", (schedule_id,))
            con.executemany(
                "INSERT INTO schedule_alert_targets (schedule_id, target_id) VALUES (?, ?)",
                [(schedule_id, t) for t in wanted],
            )

    def targets_of(self, schedule_id: str) -> list[str]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT target_id FROM schedule_alert_targets WHERE schedule_id = ? ORDER BY 1",
                (schedule_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def _notify(self, sched: Schedule, run: ScheduleRun) -> None:
        """Queue an alert for a flagged run, a rule run with matches (when no threshold is
        set), or a schedule that paused itself. Summaries only (ADR-0007 row 2)."""
        if self._dispatcher is None:
            return
        targets = self.targets_of(sched.schedule_id)
        if not targets:
            return
        kind: AlertKind | None = None
        if run.status == "paused":
            kind = "pause"
        elif run.status == "ok" and run.flagged:
            kind = "flag"
        elif (
            run.status == "ok"
            and sched.kind == "rule"
            and sched.threshold_kind is None
            and (run.row_count or 0) > 0
        ):
            kind = "match"
        if kind is None:
            return
        if kind == "pause":
            detail = f"Paused: {run.error or 'no reason given'}"
        elif sched.kind == "rule":
            try:
                row, _ = self._rules.get(sched.target_id)
                detail = f"Rule: {row.title} by {row.author or 'author not stated'}"
            except NotFoundError:
                detail = "Rule"
        else:
            detail = "Saved search"
        alert = Alert(
            kind=kind,
            title=sched.name,
            detail=detail,
            count=None if kind == "pause" else run.row_count,
            reason=run.flag_reason,
            range_start=run.range_start,
            range_end=run.range_end,
            link=f"{self._link}/dashboard" if self._link else None,
            product=PRODUCT_NAME,
        )
        self._dispatcher.enqueue(alert, targets, sched.schedule_id, run.run_id)

    # --- reading ---------------------------------------------------------------------------

    def get(self, schedule_id: str) -> Schedule:
        with self._meta.connect() as con:
            r = con.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
            ).fetchone()
        if r is None:
            raise NotFoundError("No such schedule")
        return _schedule(r)

    def all(self) -> list[Schedule]:
        with self._meta.connect() as con:
            rows = con.execute("SELECT * FROM schedules ORDER BY name COLLATE NOCASE").fetchall()
        return [_schedule(r) for r in rows]

    def runs(self, schedule_id: str, limit: int = 30) -> list[ScheduleRun]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM schedule_runs WHERE schedule_id = ?"
                " ORDER BY started_at DESC, run_id DESC LIMIT ?",
                (schedule_id, limit),
            ).fetchall()
        return [_run(r) for r in rows]

    # --- running ---------------------------------------------------------------------------

    def tick(self) -> int:
        """Run every schedule that is due. Returns how many ran (including pauses)."""
        now = self._clock().astimezone(UTC)
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM schedules WHERE paused = 0 AND next_run_at IS NOT NULL"
                " AND next_run_at <= ? ORDER BY next_run_at LIMIT ?",
                (now.isoformat(), DUE_PER_TICK),
            ).fetchall()
        for r in rows:
            sched = _schedule(r)
            fire = datetime.fromisoformat(sched.next_run_at or now.isoformat())
            try:
                self.run(sched, fire)
            except Exception as exc:  # one broken schedule never stops the others
                log.warning(
                    "schedule.tick_failed", schedule_id=sched.schedule_id, error=type(exc).__name__
                )
            with self._meta.connect() as con:
                con.execute(
                    "UPDATE schedules SET next_run_at = ? WHERE schedule_id = ? AND paused = 0",
                    (self.next_run(sched.cron, max(now, fire)), sched.schedule_id),
                )
        return len(rows)

    def run(self, sched: Schedule, fire: datetime | None = None) -> ScheduleRun:
        """Run one schedule now (or for the fire time it was due at), as its owner."""
        now = self._clock().astimezone(UTC)
        fire = fire or now
        nominal = now if now - fire > LATE else fire
        end = nominal - timedelta(seconds=self._config.lag_seconds)
        start = self._range_start(sched, end, nominal)
        last = end - timedelta(microseconds=1)  # the engine's range is inclusive: [start, last]
        run_id = new_id()
        try:
            owner = self._check(sched)
        except _Stop as exc:
            return self._pause(sched, run_id, now, str(exc))
        status, error = "ok", None
        columns: list[str] = []
        sample: list[list[Any]] = []
        count: int | None = None
        elapsed = 0
        read: list[str] = []
        truncated = False
        rule_run_id: str | None = None
        try:
            if sched.kind == "search":
                search = self._searches.get(sched.target_id, owner)
                values = bind(search.params, sched.params, start, last, search.sql)
                allowed = permitted_sources(self._meta, owner)
                sources = scope_sources(allowed, search.sources)
                scope = QueryScope(sources, start, last)
                sql = compile_sql(search.sql).strip().rstrip(";")
                # The full count, not just the rows a result can hold.
                total = self._engine.run(
                    f"SELECT count(*) FROM ({sql}) AS counted",  # noqa: S608  # saved, guarded SQL
                    scope,
                    values,
                )
                result = self._engine.run(sql, scope, values, row_cap=self._config.sample_rows)
                count = int(total.rows[0][0]) if total.rows else 0
                columns, elapsed, read = (
                    result.columns,
                    total.elapsed_ms + result.elapsed_ms,
                    result.sources,
                )
                sample = result.rows
                truncated = count > len(sample)
            else:
                rr = self._rule_runner.run(sched.target_id, owner, start, last, None)
                rule_run_id, count, elapsed, read = (
                    rr.run_id,
                    rr.match_count,
                    rr.elapsed_ms,
                    rr.sources_in_scope,
                )
                if rr.status == "failed":
                    status, error = "failed", rr.error
                matches = self._rule_runner.matches(rr.run_id, owner)
                columns = ["event_id", "event_time", "source_id"]
                sample = [
                    [m.event_id, m.event_time, m.source_id]
                    for m in matches[: self._config.sample_rows]
                ]
                truncated = count > len(sample)
        except AppError as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        flagged, reason = (
            self._flag(sched, count) if status == "ok" and count is not None else (False, None)
        )
        run = ScheduleRun(
            run_id, sched.schedule_id, now.isoformat(), start.isoformat(), end.isoformat(),
            status, count, elapsed, read, columns, sample, truncated, flagged, reason, error,
            rule_run_id,
        )  # fmt: skip
        self._save(run)
        self._notify(sched, run)
        self._audit.write(
            "schedule.run",
            "failure" if error else "success",
            sched.owner_id,
            None,
            {
                "schedule_id": sched.schedule_id,
                "run_id": run_id,
                "kind": sched.kind,
                "target_id": sched.target_id,
                "rows": count,
                "flagged": flagged,
                "sources_in_scope": read,
                **({"error": error} if error else {}),
            },
        )
        return run

    def _range_start(self, sched: Schedule, end: datetime, nominal: datetime) -> datetime:
        if sched.lookback_minutes:
            return end - timedelta(minutes=sched.lookback_minutes)
        with self._meta.connect() as con:
            prev = con.execute(
                "SELECT range_end FROM schedule_runs WHERE schedule_id = ? AND range_end IS NOT"
                " NULL AND status = 'ok' ORDER BY started_at DESC LIMIT 1",
                (sched.schedule_id,),
            ).fetchone()
        if prev is not None:
            last = datetime.fromisoformat(prev["range_end"])
            if timedelta(0) < end - last <= MAX_LAST_INTERVAL:
                return last
        # First run, or a long gap: one interval of the schedule (measured from the fire
        # time, before the lag shifts it), ending at this run's end.
        nxt = Cron.parse(sched.cron).next_after(nominal, self._tz)
        return end - min(nxt - nominal, MAX_LAST_INTERVAL)

    def _owner(self, sched: Schedule) -> User:
        if sched.owner_id == LOCAL_USER.user_id:
            if not self._local_mode():
                raise _Stop("Made before accounts existed; an administrator must take it over")
            owner = LOCAL_USER
        else:
            found = self._users.get(sched.owner_id)
            if found is None or found.disabled:
                raise _Stop("The owner's account is disabled or removed")
            owner = found
        if owner.role == "auditor":
            raise _Stop("The owner's role can no longer run schedules")
        return owner

    def _check(self, sched: Schedule) -> User:
        owner = self._owner(sched)
        try:
            sha, scope, _ = self.snapshot(sched.kind, sched.target_id, owner)
        except NotFoundError as exc:
            what = "saved search" if sched.kind == "search" else "rule"
            raise _Stop(f"The {what} was deleted or is no longer visible to the owner") from exc
        if sched.kind == "search" and sha != sched.target_sha256:
            raise _Stop("The saved search changed since this schedule was set; review and resume")
        if sched.kind == "rule":
            row, _ = self._rules.get(sched.target_id)
            if not row.enabled:
                raise _Stop("The rule was disabled")
            if row.sha256 != sched.target_sha256:
                raise _Stop("The rule was re-imported with different content; review and resume")
        if sched.scope_sources is None and scope is not None:
            raise _Stop("The owner no longer has access to every source")
        if sched.scope_sources is not None and scope is not None:
            lost = set(sched.scope_sources) - set(scope)
            if lost:
                raise _Stop(f"The owner lost access to {len(lost)} source(s) this schedule read")
        return owner

    def _pause(self, sched: Schedule, run_id: str, now: datetime, reason: str) -> ScheduleRun:
        with self._meta.connect() as con:
            con.execute(
                "UPDATE schedules SET paused = 1, paused_reason = ?, updated_at = ?"
                " WHERE schedule_id = ?",
                (reason, now.isoformat(), sched.schedule_id),
            )
        run = ScheduleRun(
            run_id, sched.schedule_id, now.isoformat(), None, None, "paused", None, None, [],
            [], [], False, False, None, reason, None,
        )  # fmt: skip
        self._save(run)
        self._notify(sched, run)
        self._audit.write(
            "schedule.pause",
            "success",
            sched.owner_id,
            None,
            {"schedule_id": sched.schedule_id, "reason": reason, "by": "system"},
        )
        return run

    def _flag(self, sched: Schedule, count: int) -> tuple[bool, str | None]:
        v = sched.threshold_value
        if sched.threshold_kind is None or v is None:
            return False, None
        if sched.threshold_kind == "above":
            return (count > v, f"{count} is above {v:g}") if count > v else (False, None)
        if sched.threshold_kind == "below":
            return (count < v, f"{count} is below {v:g}") if count < v else (False, None)
        with self._meta.connect() as con:
            prev = con.execute(
                "SELECT row_count FROM schedule_runs WHERE schedule_id = ? AND status = 'ok'"
                " ORDER BY started_at DESC LIMIT 1",
                (sched.schedule_id,),
            ).fetchone()
        if prev is None or prev["row_count"] is None:
            return False, None
        before = int(prev["row_count"])
        if before == 0:
            return (count > 0, f"{count} after 0") if count > 0 else (False, None)
        change = abs(count - before) / before * 100
        if change > v:
            return True, f"{count} vs {before}: changed {change:.0f}%"
        return False, None

    def _save(self, run: ScheduleRun) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO schedule_runs (run_id, schedule_id, started_at, range_start,"
                " range_end, status, row_count, elapsed_ms, sources_in_scope, columns, sample,"
                " truncated, flagged, flag_reason, error, rule_run_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.schedule_id,
                    run.started_at,
                    run.range_start,
                    run.range_end,
                    run.status,
                    run.row_count,
                    run.elapsed_ms,
                    json.dumps(run.sources_in_scope),
                    json.dumps(run.columns),
                    json.dumps(run.sample, default=str),
                    int(run.truncated),
                    int(run.flagged),
                    run.flag_reason,
                    run.error,
                    run.rule_run_id,
                ),
            )
            con.execute(
                "UPDATE schedules SET last_run_at = ? WHERE schedule_id = ?",
                (run.started_at, run.schedule_id),
            )
            con.execute(
                "DELETE FROM schedule_runs WHERE schedule_id = ? AND run_id NOT IN ("
                " SELECT run_id FROM schedule_runs WHERE schedule_id = ?"
                " ORDER BY started_at DESC, run_id DESC LIMIT ?)",
                (run.schedule_id, run.schedule_id, self._config.keep_runs),
            )


def _cron(text: str) -> str:
    """A preset name (hourly, daily, weekdays) or five cron fields, normalized."""
    return Cron.parse(PRESETS.get(text.strip().lower(), text)).expr


def _schedule(r: sqlite3.Row) -> Schedule:
    scope = r["scope_sources"]
    return Schedule(
        schedule_id=r["schedule_id"],
        kind=r["kind"],
        target_id=r["target_id"],
        name=r["name"],
        owner_id=r["owner_id"],
        shared=bool(r["shared"]),
        cron=r["cron"],
        lookback_minutes=r["lookback_minutes"],
        params=json.loads(r["params"]),
        target_sha256=r["target_sha256"],
        scope_sources=None if scope is None else [str(s) for s in json.loads(scope)],
        threshold_kind=r["threshold_kind"],
        threshold_value=r["threshold_value"],
        paused=bool(r["paused"]),
        paused_reason=r["paused_reason"],
        next_run_at=r["next_run_at"],
        last_run_at=r["last_run_at"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


def _run(r: sqlite3.Row) -> ScheduleRun:
    return ScheduleRun(
        run_id=r["run_id"],
        schedule_id=r["schedule_id"],
        started_at=r["started_at"],
        range_start=r["range_start"],
        range_end=r["range_end"],
        status=r["status"],
        row_count=r["row_count"],
        elapsed_ms=r["elapsed_ms"],
        sources_in_scope=[str(s) for s in json.loads(r["sources_in_scope"])],
        columns=json.loads(r["columns"] or "[]"),
        sample=json.loads(r["sample"] or "[]"),
        truncated=bool(r["truncated"]),
        flagged=bool(r["flagged"]),
        flag_reason=r["flag_reason"],
        error=r["error"],
        rule_run_id=r["rule_run_id"],
    )
