"""Run the enabled rules over the rows a done reparse job rewrote (ADR-0050 row 7, slice 3b;
D233).

While a source's template was missing, its rows were stored envelope-only or generic and the
rules that ran then could not match fields only the template gives. Once a reparse job is
done, an admin can run every enabled rule whose logsource applies to the source over the
rows that job rewrote, and only those: the job records their event ids
(`reparse_job_events`), and each rule's query binds them in chunks, inside the job's range
[time_min, time_max] on that source. Rows parsed normally between two outages were seen by
the scheduled runs already and are not read again. The scope comes from the job, never from
the request (CLAUDE.md rule 13), and the admin's permitted sources apply.

A stopped job (`interrupted` or `failed`) normally hands its ids to the source's next job.
When it rewrote the last waiting rows there is no next job to start, so its own re-run can
start once nothing is left to reparse and no reparse is running.

Each rule run is a normal one (`RuleRunner.run`: `rule_runs`, `rule_matches`, `rule.run`
audit). A run with matches raises an alert item as a scheduled rule run does: kind `rule`,
grouped by rule and day, so an item already open for the rule today grows (D200). Its ref id
is `reparse:<job>:<rule>`, and the item is marked late with the job's event range (D241).

When the run ends (done or partial), each alert target of a schedule whose scheduled run
would have alerted on a rule's late matches gets one "Late detection from reparse" message
listing those rules and their match counts, with the source and the event range (D241).
Such a schedule runs the rule, is not paused, would not pause itself, its owner may read the
source, and the matches meet its threshold (`ScheduleService.late_targets`). A rule with no
such schedule, or muted, sends nothing. Each rule is announced once: the messages are
queued in the transaction that marks its progress row `notified`.

No stop repeats a rule's matches or its item count: a rule's progress for the job
(`reparse_rule_runs`) is written in the transaction that stores its run (`stored`) and in
the one that raises or grows its item (`done`). A start after a stop uses a stored run
instead of running the rule again, and skips a done rule. A rule that cannot run is
`failed`: the job ends `partial`, and the next start runs only the rules that did not
complete. Audited as `source.reparse_rules` at start and end.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

import structlog

from app.alerts.dispatch import AlertDispatcher
from app.alerts.items import AlertItems
from app.alerts.render import Alert
from app.auth.users import User
from app.core.branding import PRODUCT_NAME
from app.core.errors import AppError, ConflictError, NotFoundError
from app.detect.runner import MAX_RANGE, RuleRunner, RunRow
from app.detect.store import RuleRow, RuleStore
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.reparse import STOPPED, ReparseJob, ReparseJobs, RulesState
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

if TYPE_CHECKING:
    from app.search.schedules import ScheduleService

log = structlog.get_logger(__name__)

INTERRUPTED = (
    "The server stopped while the rules ran. Start it again to run the rules that have not run yet."
)
ABOUT_IDS = 500  # event ids read back for who and which devices an item is about
LISTED_RULES = 5  # rules named in one late-detection message; the rest are counted


@dataclass(frozen=True, slots=True)
class RuleFailure:
    rule_id: str
    title: str
    error: str


class ReparseRules:
    def __init__(
        self,
        meta: MetaDB,
        jobs: ReparseJobs,
        runner: RuleRunner,
        rules: RuleStore,
        items: AlertItems,
        engine: QueryEngine,
        audit: AuditLog,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        dispatcher: AlertDispatcher | None = None,
        link: str | None = None,
        schedules: ScheduleService | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._schedules = schedules
        self._link = link
        self._meta = meta
        self._jobs = jobs
        self._runner = runner
        self._rules = rules
        self._items = items
        self._engine = engine
        self._audit = audit
        self._clock = clock
        self._lock = threading.Lock()
        self._running: dict[str, threading.Thread] = {}

    def interrupt_left_running(self) -> int:
        """At start: a re-run a restart cut short."""
        with self._meta.connect() as con:
            cur = con.execute(
                "UPDATE reparse_jobs SET rules_state = 'interrupted', rules_finished_at = ?,"
                " rules_error = ? WHERE rules_state = 'running'",
                (self._clock().isoformat(), INTERRUPTED),
            )
            return int(cur.rowcount)

    def failures(self, job_ids: list[str]) -> dict[str, list[RuleFailure]]:
        """The rules that could not run, per job (a `partial` re-run)."""
        if not job_ids:
            return {}
        marks = ", ".join("?" for _ in job_ids)
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT job_id, rule_id, title, error FROM reparse_rule_runs"  # noqa: S608
                f" WHERE job_id IN ({marks}) AND state = 'failed' ORDER BY title, rule_id",
                job_ids,
            ).fetchall()
        out: dict[str, list[RuleFailure]] = {}
        for r in rows:
            out.setdefault(r["job_id"], []).append(
                RuleFailure(r["rule_id"], r["title"] or r["rule_id"], r["error"] or "")
            )
        return out

    def ready(self, jobs: list[ReparseJob]) -> set[str]:
        """The jobs whose rule re-run is offered (or was started), from metadata only, never
        the lake (the source list calls it): a done job, or a stopped job whose rules
        already started or that holds rewritten event ids. The source list shows only each
        source's latest job, so no reparse of the source is running. Whether rows are still
        waiting to be reparsed is checked when the re-run starts."""
        out = set()
        for job in jobs:
            if job.state == "done" or (
                job.state in STOPPED
                and (job.rules_state is not None or self._has_events(job.job_id))
            ):
                out.add(job.job_id)
        return out

    def start(self, source_id: str, job_id: str, user: User, ip: str | None) -> ReparseJob:
        job = self._jobs.get(source_id, job_id)  # 404 for another source's job
        if job.state not in ("done", *STOPPED):
            raise ConflictError(
                "The reparse has not finished, so there are no reparsed events to run rules"
                " over yet"
            )
        _refuse_if_started(job.rules_state)
        if not self._has_events(job_id):
            raise ConflictError(
                "This reparse rewrote no events, so there are none to run rules over"
            )
        if job.state != "done" and job.rules_state is None:
            left = self._jobs.left(job)  # the lake, read only here and not from the list
            if left > 0:
                raise ConflictError(
                    f"Reparse the remaining {left:,} {'event' if left == 1 else 'events'}"
                    " first. That reparse includes the events this one rewrote, and its"
                    " rules can run once it is done"
                )
        if job.time_min is None or job.time_max is None:
            raise ConflictError("This reparse has no time range to run rules over")
        start, end = _range(job.time_min, job.time_max)
        if end - start > MAX_RANGE:
            raise ConflictError("The reparsed range is longer than a rule run can cover (366 days)")
        with self._lock:
            with self._meta.connect() as con:
                # A stopped job's ids may have been taken over by a reparse started since,
                # and none may be running: checked in the same write as the claim.
                claimed = con.execute(
                    "UPDATE reparse_jobs SET rules_state = 'running', rules_run_at = ?,"
                    " rules_finished_at = NULL, rules_error = NULL WHERE job_id = ?"
                    " AND (state = 'done' OR (state IN (?, ?) AND NOT EXISTS (SELECT 1"
                    " FROM reparse_jobs r WHERE r.source_id = ? AND r.state = 'running')))"
                    " AND EXISTS (SELECT 1 FROM reparse_job_events e WHERE e.job_id = ?)"
                    " AND (rules_state IS NULL"
                    " OR rules_state IN ('partial', 'failed', 'interrupted'))",
                    (self._clock().isoformat(), job_id, *STOPPED, source_id, job_id),
                ).rowcount
                if claimed:  # failed rules run again
                    con.execute(
                        "DELETE FROM reparse_rule_runs WHERE job_id = ? AND state = 'failed'",
                        (job_id,),
                    )
                progress = {
                    r["rule_id"]: (r["state"], r["run_id"])
                    for r in con.execute(
                        "SELECT rule_id, state, run_id FROM reparse_rule_runs WHERE job_id = ?",
                        (job_id,),
                    )
                }
            if not claimed:
                _refuse_if_started(self._jobs.get(source_id, job_id).rules_state)
                raise ConflictError("The rules cannot start over this reparse now")
            try:
                every = self._rules.all()
                # A rule whose run was stored before a stop finishes from that run, even if
                # it was disabled since; the others run if enabled and not done for the job.
                stored = {rid: run for rid, (st, run) in progress.items() if st == "stored"}
                todo = [r for r in every if r.rule_id in stored] + [
                    r
                    for r in self._runner.rules_for_source(
                        [r for r in every if r.enabled], source_id
                    )
                    if r.rule_id not in progress
                ]
                self._audit.write(
                    "source.reparse_rules",
                    "success",
                    user.user_id,
                    ip,
                    {
                        "step": "start",
                        "job_id": job_id,
                        "source_id": source_id,
                        "rules": len(todo),
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                    },
                )
                thread = threading.Thread(
                    target=self._work,
                    args=(job, user, todo, stored, start, end, ip),
                    name=f"reparse-rules-{source_id}",
                    daemon=True,
                )
                self._running[job_id] = thread
                thread.start()
            except BaseException:
                self._running.pop(job_id, None)
                self._end(job, user, "failed", "The rules could not start", [])
                raise
        return self._jobs.get(source_id, job_id)

    def join(self, job_id: str, timeout: float = 60.0) -> None:
        """Wait for a job's re-run to end (tests and shutdown)."""
        thread = self._running.get(job_id)
        if thread is not None:
            thread.join(timeout)

    def _work(
        self,
        job: ReparseJob,
        user: User,
        todo: list[RuleRow],
        stored: dict[str, str | None],
        start: datetime,
        end: datetime,
        ip: str | None,
    ) -> None:
        failed: list[str] = []
        try:
            for row in todo:
                run = self._stored_run(stored.get(row.rule_id), user)
                if run is None:
                    try:
                        run = self._runner.run(
                            row.rule_id, user, start, end, ip,
                            only_source=job.source_id,
                            only_events=self._chunks(job.job_id),
                            on_save=partial(self._stored, job_id=job.job_id, row=row),
                        )  # fmt: skip
                    except AppError as exc:  # refused before a run was stored
                        log.warning("reparse_rules.rule_failed", error=type(exc).__name__)
                        with self._meta.connect() as con:
                            self._stored(
                                con, None, "failed", str(exc) or type(exc).__name__,
                                job_id=job.job_id, row=row,
                            )  # fmt: skip
                        failed.append(row.rule_id)
                        continue
                if run.status == "failed":  # recorded as failed with the run
                    failed.append(row.rule_id)
                    continue
                if run.status == "ok" and run.match_count > 0:
                    self._raise(job, user, row, run)
                else:
                    with self._meta.connect() as con:
                        self._done(con, job.job_id, row.rule_id, run.match_count, 0)
            error = (
                f"{len(failed)} of {len(todo)} rules could not run. Run the remaining rules to"
                " try them again."
                if failed
                else None
            )
            notified = self._notify(job)
            self._end(job, user, "partial" if failed else "done", error, failed, notified)
        except Exception as exc:
            log.warning("reparse_rules.failed", source_id=job.source_id, error=type(exc).__name__)
            self._end(
                job,
                user,
                "failed",
                f"The rules stopped ({type(exc).__name__}). Start them again to run the rules"
                " that have not run yet.",
                failed,
            )
        finally:
            with self._lock:
                self._running.pop(job.job_id, None)

    # --- the rule's progress for the job, each in the transaction of what it records ------

    def _stored_run(self, run_id: str | None, user: User) -> RunRow | None:
        if run_id is None:
            return None
        try:
            return self._runner.get_run(run_id, user)
        except NotFoundError:  # pruned since, with its matches: run the rule again
            return None

    def _stored(
        self,
        con: sqlite3.Connection,
        run_id: str | None,
        status: str,
        error: str | None,
        *,
        job_id: str,
        row: RuleRow,
    ) -> None:
        """With the run's rows: `stored`, or `failed` with the reason."""
        failed = status == "failed"
        con.execute(
            "INSERT OR REPLACE INTO reparse_rule_runs (job_id, rule_id, run_id, state, title,"
            " error) VALUES (?, ?, ?, ?, ?, ?)",
            (
                job_id,
                row.rule_id,
                run_id,
                "failed" if failed else "stored",
                row.title,
                ((error or "The rule could not run") if failed else None),
            ),
        )

    def _done(
        self, con: sqlite3.Connection, job_id: str, rule_id: str, matched: int, items: int
    ) -> None:
        """With the item's raise or growth: the rule is done for the job, counted once."""
        if con.execute(
            "UPDATE reparse_rule_runs SET state = 'done', matched = ? WHERE job_id = ?"
            " AND rule_id = ? AND state = 'stored'",
            (matched, job_id, rule_id),
        ).rowcount:
            con.execute(
                "UPDATE reparse_jobs SET rules_count = rules_count + 1,"
                " rules_matched = rules_matched + ?, rules_items = rules_items + ?"
                " WHERE job_id = ?",
                (matched, items, job_id),
            )

    def _has_events(self, job_id: str) -> bool:
        with self._meta.connect() as con:
            return (
                con.execute(
                    "SELECT 1 FROM reparse_job_events WHERE job_id = ? LIMIT 1", (job_id,)
                ).fetchone()
                is not None
            )

    def _chunks(self, job_id: str) -> Iterator[list[str]]:
        """The job's rewritten event ids, one stored chunk at a time."""
        seq = -1
        while True:
            with self._meta.connect() as con:
                r = con.execute(
                    "SELECT seq, event_ids FROM reparse_job_events WHERE job_id = ? AND seq > ?"
                    " ORDER BY seq LIMIT 1",
                    (job_id, seq),
                ).fetchone()
            if r is None:
                return
            seq = int(r["seq"])
            yield [str(i) for i in json.loads(r["event_ids"])]

    def _raise(self, job: ReparseJob, user: User, row: RuleRow, run: RunRow) -> None:
        people, devices = self._about(job.source_id, user, run)
        self._items.raise_item(
            "rule",
            row.rule_id,
            run.title,
            ref_id=f"reparse:{job.job_id}:{row.rule_id}",
            detail=(
                f"Found when the rules ran over events of source {job.source_id} that were"
                " parsed again after its template was missing."
            ),
            count=run.match_count,
            sources=run.sources_in_scope,
            owner_id=user.user_id,
            shared=True,
            range_start=run.range_start,
            range_end=run.range_end,
            people=people,
            devices=devices,
            # One open item per rule and day, as scheduled rule runs (ADR-0043 row 1, D200).
            group=(row.rule_id, "rule"),
            change=(
                f"{run.match_count} rows, {run.range_start} to {run.range_end}"
                f" (reparsed events of {job.source_id})"
            ),
            # Done for the job in the same transaction: a stop never grows the item twice.
            also=lambda con: self._done(con, job.job_id, row.rule_id, run.match_count, 1),
            # Found late, over these events' times (D241).
            late=(job.time_min, job.time_max) if job.time_min and job.time_max else None,
        )

    def _notify(self, job: ReparseJob) -> dict[str, int]:
        """One "Late detection from reparse" message per target for the rules done for the
        job with matches and not announced yet (D241). A rule's targets are those of its
        schedules whose scheduled run would have alerted on these matches on this source
        (`ScheduleService.late_targets`: not paused, would not pause, the owner may read
        the source, the threshold met); a rule with none, or muted, is marked announced and
        sends nothing. The messages and the marks are one transaction, so a stop sends them
        all or none, and a start after it sends only what is left."""
        now = self._clock().astimezone(UTC).isoformat()
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT rule_id, title, matched FROM reparse_rule_runs WHERE job_id = ?"
                " AND state = 'done' AND notified = 0 AND matched > 0 ORDER BY title, rule_id",
                (job.job_id,),
            ).fetchall()
            muted = {
                str(m[0])
                for m in con.execute(
                    "SELECT subject FROM alert_mutes WHERE kind = 'rule' AND ended_at IS NULL"
                    " AND until > ?",
                    (now,),
                )
            }
        if not rows:
            return {"targets": 0, "rules": 0}
        # Who hears, read before the write: each schedule's owner, sources, and threshold.
        hears: dict[str, list[sqlite3.Row]] = {}
        if self._dispatcher is not None and self._schedules is not None:
            for r in rows:
                if r["rule_id"] in muted:
                    continue
                for tid in self._schedules.late_targets(
                    r["rule_id"], job.source_id, int(r["matched"])
                ):
                    hears.setdefault(tid, []).append(r)
        with self._meta.connect() as con:
            con.executemany(
                "UPDATE reparse_rule_runs SET notified = 1 WHERE job_id = ? AND rule_id = ?",
                [(job.job_id, r["rule_id"]) for r in rows],
            )
            if self._dispatcher is not None:
                for tid, rules in sorted(hears.items()):
                    self._dispatcher.enqueue(
                        self._late_alert(job, rules), [tid], None, None,
                        source_id=job.source_id, con=con,
                    )  # fmt: skip
        announced = {r["rule_id"] for rules in hears.values() for r in rules}
        return {"targets": len(hears), "rules": len(announced)}

    def _late_alert(self, job: ReparseJob, rules: list[sqlite3.Row]) -> Alert:
        """A summary (ADR-0007 row 2): the rules and their match counts, no event content."""
        named = [
            f"{r['title'] or r['rule_id']} ({r['matched']}"
            f" {'match' if r['matched'] == 1 else 'matches'})"
            for r in rules[:LISTED_RULES]
        ]
        more = len(rules) - LISTED_RULES
        if more > 0:
            named.append(f"and {more} more")
        return Alert(
            kind="late_detection",
            title=f"Reparsed events of source {job.source_id}",
            detail=(
                "Rules matched events parsed again after the source's template was missing: "
                + ", ".join(named)
                + "."
            ),
            count=sum(int(r["matched"]) for r in rules),
            reason=None,
            range_start=job.time_min,
            range_end=job.time_max,
            link=f"{self._link}/alerts" if self._link else None,
            product=PRODUCT_NAME,
        )

    def _about(self, source_id: str, user: User, run: RunRow) -> tuple[list[str], list[str]]:
        """Who and which devices the matched events are about (ADR-0038 row 28)."""
        ids = [m.event_id for m in self._runner.matches(run.run_id, user)][:ABOUT_IDS]
        if not ids:
            return [], []
        try:
            rows = self._engine.run(
                "SELECT DISTINCT actor_user_name, device_hostname FROM events"
                " WHERE list_contains($ids, event_id) LIMIT 100",
                QueryScope(
                    [source_id],
                    datetime.fromisoformat(run.range_start),
                    datetime.fromisoformat(run.range_end),
                ),
                {"ids": ids},
                timeout_s=20,
                intel=False,
                name="reparse_rules.about",
            ).rows
        except AppError:
            return [], []  # the item is raised without them
        return [str(p) for p, _ in rows if p], [str(d) for _, d in rows if d]

    def _end(
        self,
        job: ReparseJob,
        user: User,
        state: RulesState,
        error: str | None,
        failed: list[str],
        notified: dict[str, int] | None = None,
    ) -> None:
        with self._meta.connect() as con:
            con.execute(
                "UPDATE reparse_jobs SET rules_state = ?, rules_finished_at = ?, rules_error = ?"
                " WHERE job_id = ?",
                (state, self._clock().isoformat(), error, job.job_id),
            )
            if state == "done":  # every rule ran: the ids are not needed again
                con.execute("DELETE FROM reparse_job_events WHERE job_id = ?", (job.job_id,))
        now = self._jobs.get(job.source_id, job.job_id)
        self._audit.write(
            "source.reparse_rules",
            "success" if state == "done" else "failure",
            user.user_id,  # the admin who started it: the re-run is their action
            None,
            {
                "step": "end",
                "job_id": job.job_id,
                "source_id": job.source_id,
                "state": state,
                "rules": now.rules_count,
                "matches": now.rules_matched,
                "items": now.rules_items,
                "failed": failed,
                "notified": notified or {"targets": 0, "rules": 0},
            },
        )


def _refuse_if_started(state: RulesState | None) -> None:
    if state == "running":
        raise ConflictError("The rules are already running over this reparse")
    if state == "done":
        raise ConflictError("The rules already ran over this reparse")


def _range(time_min: str, time_max: str) -> tuple[datetime, datetime]:
    """The job's range as a rule run takes it: the engine's end is inclusive, and a run
    needs end after start, so one event's range is widened by a microsecond."""
    start, end = datetime.fromisoformat(time_min), datetime.fromisoformat(time_max)
    return start, max(end, start + timedelta(microseconds=1))
