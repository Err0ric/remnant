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
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import structlog

from app.alerts.dispatch import AlertDispatcher
from app.alerts.items import AlertItems
from app.alerts.render import Alert, AlertKind
from app.auth.users import LOCAL_USER, User, UserStore
from app.core.branding import PRODUCT_NAME
from app.core.config import SchedulesConfig
from app.core.errors import AppError, ConflictError, NotFoundError, ParamInvalidError
from app.core.ids import AUTO_PARSER, new_id
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
PanelWidth = Literal["third", "half", "full"]
PanelView = Literal["table", "bars"]
# The number on a Dashboard panel (ADR-0034 row 1): row count, or a value of one column
# over the whole result.
HeadlineKind = Literal["rows", "sum", "distinct", "first"]

# What one row is, from its key columns (the panels' `rowNoun` in headline.ts): "3
# addresses" only when every key column names the same kind of thing; else "rows".
_NOUNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|_)(ip|addr|address|src|dst)(_|$)|src_endpoint|dst_endpoint"), "addresses"),
    (re.compile(r"user|person|actor|account|who"), "people"),
    (re.compile(r"host|device|machine|computer"), "devices"),
    (re.compile(r"source"), "sources"),
    (re.compile(r"service|app"), "services"),
    (re.compile(r"rule"), "rules"),
    (re.compile(r"domain|site|url"), "domains"),
]
_NOT_KEY = re.compile(r"^(n|count|total)$|_count$|[^s]s$", re.IGNORECASE)


_ONE = {
    "addresses": "address", "people": "person", "devices": "device", "sources": "source",
    "services": "service", "rules": "rule", "domains": "domain", "matches": "match",
    "rows": "row",
}  # fmt: skip


def counted(n: int, noun: str) -> str:
    """ "1 address", "32 addresses"; an owner's own label is kept as written."""
    return f"{n:,} {_ONE.get(noun, noun) if n == 1 else noun}"


def _noun_of(column: str) -> str | None:
    c = column.lower()
    return next((n for rx, n in _NOUNS if rx.search(c)), None)


def row_noun(sched: "Schedule", columns: list[str]) -> str:
    if sched.kind == "rule":
        return "matches"
    if sched.headline_label and sched.headline_kind == "rows":
        return sched.headline_label
    keys = [c for c in columns if not _NOT_KEY.search(c)]
    named = {n for c in keys if (n := _noun_of(c)) is not None}
    first = _noun_of(columns[0]) if columns else None
    return first if first and len(named) == 1 else "rows"


COLUMN_NAME_MAX = 120
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
    # Dashboard display (trial finding): the owner's choice, seen by everyone.
    panel_width: PanelWidth = "third"
    panel_view: PanelView = "table"
    # What changed in the definition since the last run (F37); the next run records it.
    definition_change: str | None = None
    headline_kind: HeadlineKind = "rows"
    headline_column: str | None = None
    headline_label: str | None = None


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
    # Set when the run found nothing, the one before found rows, and a source it read
    # switched parser (template) in between (trial finding F36).
    parser_change: str | None = None
    # The first run after the target, its parameters, its range, or the saved search
    # changed says what changed (F37).
    definition_change: str | None = None
    # The panel's number for this run (ADR-0034): None when the column was not in the
    # result, so the panel says so instead of showing a wrong number.
    headline: str | None = None


# Templates per source in the earlier part (before $cur) and in this run's range.
def _parser_name(template_id: Any) -> str:
    return "Automatic" if template_id in (None, AUTO_PARSER) else str(template_id)


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
        items: AlertItems | None = None,
    ) -> None:
        self._items = items
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
        panel_width: PanelWidth | None = None,
        panel_view: PanelView | None = None,
        headline_kind: HeadlineKind | None = None,
        headline_column: str | None = None,  # "" clears it
        headline_label: str | None = None,  # "" clears it
        kind: Kind | None = None,
        target_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Schedule:
        sets: dict[str, Any] = {}
        notes: list[str] = []
        new_kind, new_target = kind or s.kind, target_id or s.target_id
        retarget = (new_kind, new_target) != (s.kind, s.target_id)
        if retarget or (params is not None and params != s.params):
            # A new definition: checked as the owner it runs as, like a new schedule.
            try:
                owner = self._owner(s)
            except _Stop as exc:
                raise ConflictError(f"Cannot change it: {exc}") from exc
            sha, scope, target_name = self.snapshot(new_kind, new_target, owner)
            # A new target starts without the old target's parameters unless given.
            values = params if params is not None else ({} if retarget else s.params)
            if new_kind == "search":
                search = self._searches.get(new_target, owner)
                now = self._clock().astimezone(UTC)
                bind(search.params, values, now, now, search.sql)  # refuses bad params now
            elif values:
                raise ParamInvalidError("Rules take no parameters")
            sets |= {
                "kind": new_kind,
                "target_id": new_target,
                "params": json.dumps(values),
                "target_sha256": sha,
                "scope_sources": None if scope is None else json.dumps(scope),
            }
            what = "saved search" if new_kind == "search" else "rule"
            notes.append(
                f"Now runs the {what} {target_name[:120]}" if retarget else "Parameters changed"
            )
        if panel_width is not None:
            sets["panel_width"] = panel_width
        if panel_view is not None:
            sets["panel_view"] = panel_view
        if headline_kind is not None:
            sets["headline_kind"] = headline_kind
        if headline_column is not None:
            sets["headline_column"] = headline_column.strip()[:COLUMN_NAME_MAX] or None
        if headline_label is not None:
            sets["headline_label"] = headline_label.strip()[:60] or None
        kind_after = sets.get("headline_kind", s.headline_kind)
        column_after = sets.get("headline_column", s.headline_column)
        if kind_after != "rows" and not column_after:
            raise ParamInvalidError("Pick the column the headline reads")
        if name is not None:
            sets["name"] = name
        expr = s.cron
        if cron is not None:
            expr = sets["cron"] = _cron(cron)
        if lookback_minutes is not None and (lookback_minutes or None) != s.lookback_minutes:
            sets["lookback_minutes"] = lookback_minutes or None
            notes.append(
                f"Range changed from {_range_label(s.lookback_minutes)}"
                f" to {_range_label(lookback_minutes or None)}"
            )
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
            if sha != s.target_sha256:
                what = "saved search" if s.kind == "search" else "rule"
                notes.append(f"The {what} changed; accepted on resume")
        running = not s.paused if paused is None else not paused
        if running and ("cron" in sets or "paused" in sets):
            sets["next_run_at"] = self.next_run(expr, self._clock().astimezone(UTC))
        if not sets:
            return s
        if notes:
            sets["definition_change"] = "; ".join(filter(None, [s.definition_change, *notes]))[:500]
        sets["updated_at"] = self._clock().astimezone(UTC).isoformat()
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._meta.connect() as con:
            con.execute(
                f"UPDATE schedules SET {cols} WHERE schedule_id = ?",  # noqa: S608  # keys are fixed names set above
                (*sets.values(), s.schedule_id),
            )
        return self.get(s.schedule_id)

    def accept_search_change(self, search_id: str, editor: User) -> list[str]:
        """The owner of a saved search changed it: their own running schedules of it take
        the new definition at once and note it (F37). Anyone else's schedules of it still
        pause at their next run until their owner reviews and resumes (SPEC 5.5)."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM schedules WHERE kind = 'search' AND target_id = ?"
                " AND owner_id = ? AND paused = 0",
                (search_id, editor.user_id),
            ).fetchall()
        changed = []
        for r in rows:
            s = _schedule(r)
            try:
                sha, scope, _ = self.snapshot("search", search_id, editor)
            except NotFoundError:
                continue
            if sha == s.target_sha256:
                continue
            note = "; ".join(filter(None, [s.definition_change, "The saved search was edited"]))
            with self._meta.connect() as con:
                con.execute(
                    "UPDATE schedules SET target_sha256 = ?, scope_sources = ?,"
                    " definition_change = ?, updated_at = ? WHERE schedule_id = ?",
                    (
                        sha,
                        None if scope is None else json.dumps(scope),
                        note[:500],
                        self._clock().astimezone(UTC).isoformat(),
                        s.schedule_id,
                    ),
                )
            changed.append(s.schedule_id)
        return changed

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

    def _about(self, run: ScheduleRun) -> tuple[list[str], list[str]]:
        """Who and which devices the run's rows are about (ADR-0038 row 28): from the kept
        rows' own columns, or for a rule run (it keeps event ids) from those events, read
        from the sources the run read."""
        people, devices = _column(run, "actor_user_name"), _column(run, "device_hostname")
        ids = _column(run, "event_id")
        if (people or devices) or not ids or not run.sources_in_scope:
            return people, devices
        start = datetime.fromisoformat(run.range_start) if run.range_start else None
        end = datetime.fromisoformat(run.range_end) if run.range_end else None
        try:
            rows = self._engine.run(
                "SELECT DISTINCT actor_user_name, device_hostname FROM events"
                " WHERE list_contains($ids, event_id) LIMIT 100",
                QueryScope(run.sources_in_scope, start, end), {"ids": ids[:500]},
                timeout_s=20, intel=False, name="schedule.about",
            ).rows  # fmt: skip
        except AppError:
            return [], []  # the item is raised without them
        return [str(p) for p, _ in rows if p], [str(d) for _, d in rows if d]

    def _notify(self, sched: Schedule, run: ScheduleRun) -> None:
        """Raise an alert item and queue an alert for a flagged run or a rule run with
        matches (when no threshold is set); queue an alert for a schedule that paused itself.
        Summaries only (ADR-0007 row 2); the message links to the item (ADR-0037 row 9)."""
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
        link = f"{self._link}/dashboard" if self._link else None
        if kind != "pause" and self._items is not None:
            about = self._about(run)
            item = self._items.raise_item(
                "rule" if sched.kind == "rule" else "schedule",
                sched.target_id if sched.kind == "rule" else sched.schedule_id,
                sched.name,
                ref_id=run.run_id,
                why=run.flag_reason,
                count=run.row_count,
                sources=run.sources_in_scope,
                owner_id=sched.owner_id,
                shared=sched.shared,
                range_start=run.range_start,
                range_end=run.range_end,
                people=about[0],
                devices=about[1],
            )
            if item.state == "closed":
                return  # muted: recorded, not sent
            link = f"{self._link}/alerts#item={item.item_id}" if self._link else None
        if self._dispatcher is None:
            return
        targets = self.targets_of(sched.schedule_id)
        if not targets:
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
            link=link,
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
        headline: str | None = None
        search_sql: str | None = None
        values: dict[str, Any] = {}
        try:
            if sched.kind == "search":
                search = self._searches.get(sched.target_id, owner)
                values = bind(search.params, sched.params, start, last, search.sql)
                allowed = permitted_sources(self._meta, owner)
                sources = scope_sources(allowed, search.sources)
                scope = QueryScope(sources, start, last)
                sql = compile_sql(search.sql).strip().rstrip(";")
                search_sql = sql
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
                headline = self._headline(sched, sql, scope, values, columns, sample, count)
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
                headline = str(count)
        except AppError as exc:
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        flagged, reason = (
            self._flag(sched, count, columns)
            if status == "ok" and count is not None
            else (False, None)
        )
        changed = (
            self._parser_change(sched, start, last, read, search_sql, values)
            if status == "ok" and count == 0 and read
            else None
        )
        run = ScheduleRun(
            run_id, sched.schedule_id, now.isoformat(), start.isoformat(), end.isoformat(),
            status, count, elapsed, read, columns, sample, truncated, flagged, reason, error,
            rule_run_id, changed, sched.definition_change, headline,
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

    def _parser_change(
        self,
        sched: Schedule,
        start: datetime,
        last: datetime,
        read: list[str],
        sql: str | None = None,
        values: dict[str, Any] | None = None,
    ) -> str | None:
        """A zero right after rows: did an administrator change the parser of a source this
        panel reads since that run? Searches written against `message` stop matching when a
        source moves from a generic parser to a specific one (F36).

        Only an audited `source.parser_change` counts, never the template mix shifting under
        Automatic (F53). The source must be one the run read, and for a saved search, one the
        query returned rows from in the run before the change; a panel that never read the
        source never shows its change."""
        with self._meta.connect() as con:
            prev = con.execute(
                "SELECT started_at, range_start, range_end, row_count FROM schedule_runs"
                " WHERE schedule_id = ? AND status = 'ok' ORDER BY started_at DESC LIMIT 1",
                (sched.schedule_id,),
            ).fetchone()
            if prev is None or not prev["row_count"] or prev["range_start"] is None:
                return None  # the panel must have had rows last time and none now
            audits = con.execute(
                "SELECT ts, detail FROM audit_log WHERE action = 'source.parser_change'"
                " AND outcome = 'success' ORDER BY audit_id"
            ).fetchall()
        before = datetime.fromisoformat(prev["range_start"])
        prev_end = datetime.fromisoformat(prev["range_end"] or prev["range_start"])
        since = datetime.fromisoformat(prev["started_at"])  # changes after that run
        if before >= start:
            return None
        changes: dict[str, tuple[datetime, Any, Any]] = {}
        for row in audits:
            try:
                at = datetime.fromisoformat(row["ts"])
                detail = json.loads(row["detail"])
            except (ValueError, TypeError):
                continue
            source = str(detail.get("source_id", ""))
            if at > since and source in read:
                first = changes.get(source)
                changes[source] = (at, first[1] if first else detail.get("from"), detail.get("to"))
        notes = []
        for source in sorted(changes):
            if sql is not None and not self._fed(sql, source, before, prev_end, values or {}):
                continue
            at, old, new = changes[source]
            when = at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
            notes.append(f"{source} at {when} ({_parser_name(old)} to {_parser_name(new)})")
        if not notes:
            return None
        return (
            "Parser changed for " + "; ".join(notes)[:400] + ". Searches on message may no"
            " longer match: use raw or parsed fields."
        )

    def _fed(
        self, sql: str, source: str, start: datetime, end: datetime, values: dict[str, Any]
    ) -> bool:
        """Did this search return rows from `source` over the earlier run's range?"""
        try:
            result = self._engine.run(
                f"SELECT count(*) FROM ({sql}) AS counted",  # noqa: S608  # saved, guarded SQL
                QueryScope([source], start, end),
                values,
            )
        except AppError:
            return False
        return bool(result.rows and int(result.rows[0][0]) > 0)

    def _flag(
        self, sched: Schedule, count: int, columns: list[str] | None = None
    ) -> tuple[bool, str | None]:
        """Whether the run is flagged, and why in plain words: "32 addresses over
        threshold (0)", never "32 is above 0" (ADR-0038, owner 16:21)."""
        v = sched.threshold_value
        if sched.threshold_kind is None or v is None:
            return False, None
        noun = row_noun(sched, columns or [])
        if sched.threshold_kind == "above":
            return (
                (True, f"{counted(count, noun)} over threshold ({v:g})")
                if count > v
                else (False, None)
            )
        if sched.threshold_kind == "below":
            return (
                (True, f"{counted(count, noun)} under threshold ({v:g})")
                if count < v
                else (False, None)
            )
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
            return (count > 0, f"{counted(count, noun)}, up from 0") if count > 0 else (False, None)
        change = abs(count - before) / before * 100
        if change > v:
            return True, f"{counted(count, noun)}, was {before:,}: changed {change:.0f}%"
        return False, None

    def _headline(
        self,
        sched: Schedule,
        sql: str,
        scope: QueryScope,
        values: dict[str, Any],
        columns: list[str],
        sample: list[list[Any]],
        count: int,
    ) -> str | None:
        """The panel's number over the whole result (not the stored sample), as text."""
        kind, col = sched.headline_kind, sched.headline_column
        if kind == "rows" or not col:
            return str(count)
        if col not in columns:
            return None
        if kind == "first":
            return (
                None
                if not sample or sample[0][columns.index(col)] is None
                else (str(sample[0][columns.index(col)]))
            )
        ident = '"' + col.replace('"', '""') + '"'
        agg = f"sum({ident})" if kind == "sum" else f"count(DISTINCT {ident})"
        try:
            got = self._engine.run(
                f"SELECT {agg} FROM ({sql}) AS headline",  # noqa: S608  # saved, guarded SQL; quoted column from the result
                scope,
                values,
            )
        except AppError:
            return None  # a sum over text, for example: shown as "no value", the run is fine
        value = got.rows[0][0] if got.rows else None
        if value is None:
            return "0"
        return str(int(value)) if float(value).is_integer() else f"{float(value):.6g}"

    def _save(self, run: ScheduleRun) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO schedule_runs (run_id, schedule_id, started_at, range_start,"
                " range_end, status, row_count, elapsed_ms, sources_in_scope, columns, sample,"
                " truncated, flagged, flag_reason, error, rule_run_id, parser_change,"
                " definition_change, headline)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    run.parser_change,
                    run.definition_change,
                    run.headline,
                ),
            )
            if run.definition_change and run.status == "ok":
                con.execute(
                    "UPDATE schedules SET definition_change = NULL WHERE schedule_id = ?",
                    (run.schedule_id,),
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
        panel_width=r["panel_width"],
        panel_view=r["panel_view"],
        definition_change=r["definition_change"],
        headline_kind=r["headline_kind"],
        headline_column=r["headline_column"],
        headline_label=r["headline_label"],
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
        parser_change=r["parser_change"],
        definition_change=r["definition_change"],
        headline=r["headline"],
    )


def _range_label(minutes: int | None) -> str:
    if not minutes:
        return "since the last run"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"last {days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"last {hours} hour{'s' if hours != 1 else ''}"
    return f"last {minutes} minutes"


def _column(run: ScheduleRun, name: str) -> list[str]:
    """Distinct values of one column in the run's kept rows (who and which devices fired)."""
    if name not in (run.columns or []):
        return []
    i = run.columns.index(name)
    return [str(r[i]) for r in run.sample or [] if i < len(r) and r[i] not in (None, "")]
