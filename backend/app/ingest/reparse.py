"""Reparse a source's template_missing rows once its template loads again (ADR-0050 rows 7
and 8; D233).

An admin starts the job for one source. It rewrites only that source's rows with
`parse_status = 'template_missing'` and the source's configured `template_id`, inside the
source's retention window, parsing each row's `raw` with the template exactly as ingest
would. `event_id`, `raw`, `raw_bytes_invalid`, `time` (so a row never changes day folder),
`time_observed`, `classification`, `owner_id`, and `source_id` stay as stored; everything
else, `parse_status` included, comes from the new parse. Values ingest fills after the
parser keep the same rule (`ingest_fills`): a listener's sender as `device_ip` when the parse
has none, and a Loki row's stream labels in `envelope`. Other rows of a rewritten file are
copied unchanged.

Crash safety is compaction's (D183): a file is rewritten whole into a new part file in the
same folder, a manifest names the new file and the one it replaces before it is published
by atomic rename, and the old file is then retired and deleted after `RETIRE_GRACE_S` by a
later maintenance pass, which records the removal in the integrity ledger. A crash leaves
the old rows (no output: the next pass discards the manifest) or the new rows (reads skip a
manifest's inputs once its output is in place), never both and never neither.

The job holds the lake lock, so compaction, retention, and backups wait for it; ingest
never does. One job per source, on its own thread at low CPU priority.

The job records the event ids it rewrites (`reparse_job_events`) and their range as the
engine reads time, `coalesce(time, time_observed)`, for the rule re-run over those rows
(slice 3b). Each file's ids and range are recorded before the file is published (marked
`published` once it is), so a stop between the two never loses them: the ids are the
`event_id`s the rewrite keeps. A later job skips rows already rewritten, so a new job takes
over the recorded ids of the source's earlier jobs that ended `interrupted` or `failed`
before their rules could run, and widens its range to theirs: its re-run then covers those
rows too, once. Ids recorded for a file that was never published belong to rows still
waiting; the new job rewrites them with the same ids and does not record them twice.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import structlog

from app.core import clock as _clock
from app.core import lake_files
from app.core.errors import ConflictError, NotFoundError
from app.core.ids import AUTO_PARSER, new_id
from app.core.schema import arrow_schema
from app.core.threads import run_low
from app.ingest.compaction import (
    REPARSED,
    ROW_GROUP_ROWS,
    conform,
    finish,
    new_part,
    write_manifest,
)
from app.ingest.durable import publish
from app.ingest.integrity import LakeEvents
from app.ingest.lakelock import lake_lock
from app.ingest.records import DecodedLine
from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import template_normalizer
from app.ingest.writer import rows_table
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.templates.registry import TemplateRegistry
from app.templates.runtime import TemplateNormalizer

log = structlog.get_logger(__name__)

TEMPLATE_MISSING = "template_missing"
# Kept from the stored row; every other column comes from the new parse.
KEEP = (
    "event_id",
    "raw",
    "raw_bytes_invalid",
    "time",
    "time_observed",
    "classification",
    "owner_id",
    "source_id",
)
_READ = (*KEEP, "parse_errors", "device_ip", "envelope")
_DAY = re.compile(r"day=(\d{4}-\d{2}-\d{2})")

State = Literal["running", "done", "failed", "interrupted"]
# The rule re-run's state: `partial` when some rules could not run (they can be retried).
RulesState = Literal["running", "done", "partial", "failed", "interrupted"]
ID_CHUNK = 10_000  # rewritten event ids per `reparse_job_events` row, as the rule re-run binds them
NormalizerFactory = Callable[[Callable[[], datetime]], TemplateNormalizer]


@dataclass(slots=True)
class ReparseResult:
    rows: int = 0
    files: int = 0
    skipped_files: int = 0  # content differs from the ledger: left for verification
    time_min: datetime | None = None
    time_max: datetime | None = None


def ingest_fills(kind: str, old: dict[str, Any], row: dict[str, Any]) -> None:
    """What ingest adds to a row after the parser (`IngestService`), taken from the stored
    row instead: a listener's sender as `device_ip` when the parse has none (ADR-0021 row 5),
    and a Loki row's stream labels in `envelope`. A time ingest supplied is in `KEEP`."""
    if kind == "syslog" and row.get("device_ip") is None and old["device_ip"] is not None:
        row["device_ip"] = old["device_ip"]
    if kind == "loki":
        labels = _json_object(old["envelope"]).get("loki_labels")
        if labels is not None:
            env = _json_object(row.get("envelope"))
            env["loki_labels"] = labels
            row["envelope"] = json.dumps(env, separators=(",", ":"))


def _json_object(text: Any) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def window(lake: Path, source_id: str, days: int, today: date) -> list[Path]:
    """The source's day folders inside its retention window, as retention counts it."""
    root = lake / f"source={source_id}"
    if root.is_symlink() or not root.is_dir():
        return []
    cutoff = today - timedelta(days=days)
    out = []
    for folder in sorted(root.glob("day=*")):
        m = _DAY.fullmatch(folder.name)
        if m is None or folder.is_symlink() or not folder.is_dir():
            continue
        try:
            day = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if day >= cutoff:
            out.append(folder)
    return out


def _matches(table: pa.Table, template_id: str) -> Any:
    mask = pc.and_(
        pc.equal(table.column("parse_status"), TEMPLATE_MISSING),
        pc.equal(table.column("template_id"), template_id),
    )
    return pc.fill_null(mask, False)


def _count_file(path: Path, template_id: str) -> int:
    """Rows of one file to reparse. Row groups whose parse_status range cannot hold
    template_missing are skipped from their statistics, without reading them."""
    pf = pq.ParquetFile(path)
    names = pf.schema_arrow.names
    if "parse_status" not in names or "template_id" not in names:
        return 0
    col = names.index("parse_status")
    total = 0
    for i in range(pf.metadata.num_row_groups):
        stats = pf.metadata.row_group(i).column(col).statistics
        if (
            stats is not None
            and stats.has_min_max
            and isinstance(stats.min, str)
            and isinstance(stats.max, str)
            and not stats.min <= TEMPLATE_MISSING <= stats.max
        ):
            continue
        group = pf.read_row_group(i, columns=["parse_status", "template_id"])
        total += int(pc.sum(_matches(group, template_id)).as_py() or 0)
    return total


def _counts(
    lake: Path, source_id: str, template_id: str, days: int, today: date
) -> list[tuple[Path, int]]:
    """Each visible file in the window with rows to reparse, and how many."""
    out = []
    for folder in window(lake, source_id, days, today):
        for path in lake_files.visible(folder):
            n = 0 if path.is_symlink() else _readable_count(path, template_id)
            if n:
                out.append((path, n))
    return out


def _readable_count(path: Path, template_id: str) -> int:
    try:
        return _count_file(path, template_id)
    except Exception as exc:  # a damaged file is maintenance's to quarantine
        log.warning("reparse.unreadable_file", file=path.name, error=type(exc).__name__)
        return 0


def pending(lake: Path, source_id: str, template_id: str, days: int, today: date) -> int:
    """How many rows a reparse of this source would rewrite now."""
    return sum(n for _, n in _counts(lake, source_id, template_id, days, today))


class Reparser:
    """Rewrites the matching rows of one source, file by file. No locking or job state:
    `ReparseJobs` holds the lake lock around it."""

    def __init__(
        self,
        lake: Path,
        events: LakeEvents,
        make_normalizer: NormalizerFactory,
        template_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        kind: str = "file",
    ) -> None:
        self._lake = lake
        self._events = events
        self._make = make_normalizer
        self._template_id = template_id
        self._clock = clock
        self._kind = kind  # the source's kind, for `ingest_fills`
        self._schema = arrow_schema()

    def run(
        self,
        source_id: str,
        days: int,
        today: date,
        progress: Callable[[ReparseResult], None] | None = None,
        rewriting: Callable[[list[str], ReparseResult], None] | None = None,
    ) -> ReparseResult:
        """`rewriting` is told each file's event ids to rewrite, with the result whose range
        already covers them, before the file is published; `progress` after."""
        result = ReparseResult()
        # Year inference and time-based transforms see the time the row was received.
        observed = [self._clock()]
        normalizer = self._make(lambda: observed[0])
        for path, _ in _counts(self._lake, source_id, self._template_id, days, today):
            # Never rewrite a file whose content differs from the ledger: the edit would be
            # laundered into a new, legitimately recorded file (as compaction).
            if not self._events.unchanged([path]):
                log.warning("reparse.changed_file_kept", file=path.name)
                result.skipped_files += 1
                continue
            self._rewrite(path, normalizer, observed, result, rewriting)
            if progress is not None:
                progress(result)
        return result

    def _rewrite(
        self,
        path: Path,
        normalizer: TemplateNormalizer,
        observed: list[datetime],
        result: ReparseResult,
        rewriting: Callable[[list[str], ReparseResult], None] | None = None,
    ) -> None:
        table = conform(pq.read_table(path), self._schema)
        flags = _matches(table, self._template_id).to_pylist()
        changed = [i for i, f in enumerate(flags) if f]
        if not changed:
            return
        kept = [i for i, f in enumerate(flags) if not f]
        rows = []
        for old in table.take(pa.array(changed, pa.int64())).select(list(_READ)).to_pylist():
            observed[0] = old["time_observed"] or self._clock()
            errors = (old["parse_errors"] or "").split(",")
            line = DecodedLine(
                text=old["raw"],
                bytes_invalid=bool(old["raw_bytes_invalid"]),
                truncated="truncated" in errors,
            )
            row = normalizer.normalize(line)
            ingest_fills(self._kind, old, row)
            row.update({k: old[k] for k in KEEP})
            rows.append(row)
            # Where the engine places the row (`coalesce(time, time_observed)`), so a row
            # with no event time is inside the range too.
            when = old["time"] or old["time_observed"]
            if when is not None:
                result.time_min = when if result.time_min is None else min(result.time_min, when)
                result.time_max = when if result.time_max is None else max(result.time_max, when)
        kept_rows = table.take(pa.array(kept, pa.int64()))
        merged = pa.concat_tables([kept_rows, rows_table(rows, self._schema)])
        # Back in the original row order (a compacted file is sorted for skipping).
        out = merged.take(pc.sort_indices(pa.array(kept + changed, type=pa.int64())))
        if rewriting is not None:  # recorded first: a stop after the publish loses nothing
            rewriting([str(r["event_id"]) for r in rows], result)
        folder = path.parent
        final = new_part(folder)
        write_manifest(final, [path.name], REPARSED)
        publish(out, final, row_group_size=ROW_GROUP_ROWS)
        self._events.added([final], f"reparsed {len(rows)} rows from {path.name}")
        finish(folder, final.name, [path.name], self._clock(), REPARSED)
        result.rows += len(rows)
        result.files += 1


@dataclass(frozen=True, slots=True)
class ReparseJob:
    job_id: str
    source_id: str
    template_id: str
    user_id: str | None
    state: State
    started_at: str
    finished_at: str | None
    rows_found: int
    rows_rewritten: int
    files_rewritten: int
    time_min: str | None
    time_max: str | None
    error: str | None
    # The rule re-run over the rewritten rows (slice 3b, `detect/reparse_rules.py`).
    rules_state: RulesState | None = None
    rules_run_at: str | None = None
    rules_finished_at: str | None = None
    rules_count: int = 0
    rules_matched: int = 0
    rules_items: int = 0
    rules_error: str | None = None


@dataclass(frozen=True, slots=True)
class ReparseStatus:
    source_id: str
    template_id: str | None
    template_available: bool
    pending: int
    job: ReparseJob | None


_COLUMNS = (
    "job_id, source_id, template_id, user_id, state, started_at, finished_at, rows_found,"
    " rows_rewritten, files_rewritten, time_min, time_max, error"
)
_READ_COLUMNS = (
    _COLUMNS + ", rules_state, rules_run_at, rules_finished_at, rules_count, rules_matched,"
    " rules_items, rules_error"
)
# A job that ended so takes no rule re-run (that needs `done`): the next job takes over its ids.
STOPPED = ("interrupted", "failed")
INTERRUPTED = (
    "The server stopped during the reparse. Rows already rewritten stay rewritten;"
    " start it again to finish the rest."
)


class ReparseJobs:
    """Job state in `reparse_jobs`, the lake lock, and the worker thread."""

    def __init__(
        self,
        meta: MetaDB,
        lake: Path,
        sources: SourceStore,
        templates: TemplateRegistry,
        events: LakeEvents,
        audit: AuditLog,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        today: Callable[[], date] = lambda: _clock.now().date(),
        reparsed: Callable[[str, str], None] | None = None,
    ) -> None:
        self._meta = meta
        # Told (source, template) when a job finishes done: the source's fallback row goes,
        # and with it the reparse offer on Sources (`SourceFallbacks.reparsed`).
        self._reparsed = reparsed
        self._lake = lake
        self._sources = sources
        self._templates = templates
        self._events = events
        self._audit = audit
        self._clock = clock
        self._today = today
        self._lock = threading.Lock()
        self._running: dict[str, threading.Thread] = {}

    # --- reading ------------------------------------------------------------------------

    def latest(self, source_id: str) -> ReparseJob | None:
        with self._meta.connect() as con:
            row = con.execute(
                f"SELECT {_READ_COLUMNS} FROM reparse_jobs WHERE source_id = ?"  # noqa: S608
                " ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (source_id,),
            ).fetchone()
        return None if row is None else ReparseJob(*row)

    def latest_for(self, source_ids: list[str]) -> dict[str, ReparseJob]:
        """Each listed source's latest job (the source list), one indexed read."""
        return latest_jobs(self._meta, source_ids)

    def get(self, source_id: str, job_id: str) -> ReparseJob:
        with self._meta.connect() as con:
            row = con.execute(
                f"SELECT {_READ_COLUMNS} FROM reparse_jobs"  # noqa: S608
                " WHERE job_id = ? AND source_id = ?",
                (job_id, source_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("No such reparse job for this source")
        return ReparseJob(*row)

    def status(self, source_id: str) -> ReparseStatus:
        source = self._source(source_id)
        tid = source.template_id
        job = self.latest(source_id)
        if tid is None or tid == AUTO_PARSER:
            return ReparseStatus(source_id, tid, False, 0, job)
        n = pending(self._lake, source_id, tid, self._days(source), self._today())
        return ReparseStatus(source_id, tid, self._templates.get(tid) is not None, n, job)

    def left(self, job: ReparseJob) -> int:
        """Rows of the job's source still waiting for a reparse with the job's template."""
        source = self._source(job.source_id)
        return pending(
            self._lake, job.source_id, job.template_id, self._days(source), self._today()
        )

    # --- running ------------------------------------------------------------------------

    def interrupt_left_running(self) -> int:
        """At start: a job a restart cut short. The lake is consistent already (the next
        maintenance pass finishes or discards a half-done file from its manifest)."""
        with self._meta.connect() as con:
            cur = con.execute(
                "UPDATE reparse_jobs SET state = 'interrupted', finished_at = ?, error = ?"
                " WHERE state = 'running'",
                (self._clock().isoformat(), INTERRUPTED),
            )
            return int(cur.rowcount)

    def start(self, source_id: str, user_id: str | None, ip: str | None) -> ReparseJob:
        source = self._source(source_id)
        tid = source.template_id
        if tid is None or tid == AUTO_PARSER:
            raise ConflictError("This source has no template to reparse its events with")
        template = self._templates.get(tid)
        if template is None:
            raise ConflictError(
                f"Template {tid} is still not available. Reparse once it loads again"
            )
        tables = self._templates.tables

        def make(clock: Callable[[], datetime]) -> TemplateNormalizer:
            return template_normalizer(source, template, tables, clock)

        try:
            make(self._clock)
        except ValueError as exc:  # a lookup table it needs did not load
            raise ConflictError(f"Template {tid} cannot be used yet: {exc}") from exc
        with self._lock:
            if source_id in self._running or self._running_in_meta(source_id):
                raise ConflictError("A reparse is already running for this source")
            stack = ExitStack()
            if not stack.enter_context(lake_lock(self._lake, wait=False)):
                stack.close()
                raise ConflictError(
                    "Lake maintenance, a backup, or another reparse is running."
                    " Try again in a few minutes"
                )
            try:
                days, today = self._days(source), self._today()
                found = pending(self._lake, source_id, tid, days, today)
                if found == 0:
                    raise ConflictError("No events from this source are waiting to be reparsed")
                job, carried_from, carried = self._insert(source_id, tid, user_id, found)
                detail: dict[str, Any] = {
                    "step": "start",
                    "job_id": job.job_id,
                    "source_id": source_id,
                    "template_id": tid,
                    "events": found,
                }
                if carried_from:
                    detail |= {"carried_from": carried_from, "carried_events": carried}
                self._audit.write("source.reparse", "success", user_id, ip, detail)
                thread = threading.Thread(
                    target=self._work,
                    args=(job, make, source.kind, days, today, stack),
                    name=f"reparse-{source_id}",
                    daemon=True,
                )
                self._running[source_id] = thread
                thread.start()
            except BaseException:
                self._running.pop(source_id, None)
                stack.close()
                raise
        return job

    def join(self, source_id: str, timeout: float = 60.0) -> None:
        """Wait for a source's job to end (tests and shutdown)."""
        thread = self._running.get(source_id)
        if thread is not None:
            thread.join(timeout)

    def _work(
        self,
        job: ReparseJob,
        make: NormalizerFactory,
        kind: str,
        days: int,
        today: date,
        stack: ExitStack,
    ) -> None:
        last = [ReparseResult()]
        written: list[int] = []  # the chunks recorded for the file being rewritten
        # Taken over from a stopped job whose last file may not have been published: those
        # rows are rewritten again here with the same ids, recorded once.
        held = self._unpublished(job.job_id)

        def rewriting(ids: list[str], r: ReparseResult) -> None:
            last[0] = r  # its range covers these rows already, for the end of a stop
            written[:] = self._intend(job, r, [i for i in ids if i not in held])

        def progress(r: ReparseResult) -> None:
            last[0] = r
            self._save(job, r, written)
            written.clear()

        try:
            with stack:  # the lake lock, released when the job ends
                reparser = Reparser(
                    self._lake, self._events, make, job.template_id, self._clock, kind
                )
                result = run_low(
                    lambda: reparser.run(job.source_id, days, today, progress, rewriting)
                )
            self._end(job, "done", result, None)
            # The offer goes only when nothing was left: a file skipped (its content differs
            # from the ledger) still holds template_missing rows, so Sources keeps offering.
            if self._reparsed is not None and result.skipped_files == 0:
                self._reparsed(job.source_id, job.template_id)
        except Exception as exc:
            log.warning("reparse.failed", source_id=job.source_id, error=type(exc).__name__)
            self._end(
                job,
                "failed",
                last[0],
                f"The reparse stopped ({type(exc).__name__}). Rows already rewritten stay"
                " rewritten; start it again to finish the rest.",
            )
        finally:
            with self._lock:
                self._running.pop(job.source_id, None)

    # --- state --------------------------------------------------------------------------

    def _source(self, source_id: str) -> SourceConfig:
        for s in self._sources.list():
            if s.source_id == source_id:
                return s
        raise NotFoundError(f"No source named {source_id}")

    def _days(self, source: SourceConfig) -> int:
        return self._sources.retention_days().get(source.source_id, source.retention_days)

    def _running_in_meta(self, source_id: str) -> bool:
        with self._meta.connect() as con:
            return (
                con.execute(
                    "SELECT 1 FROM reparse_jobs WHERE source_id = ? AND state = 'running'",
                    (source_id,),
                ).fetchone()
                is not None
            )

    def _insert(
        self, source_id: str, template_id: str, user_id: str | None, found: int
    ) -> tuple[ReparseJob, list[str], int]:
        """The new job, with the ids it took over from stopped jobs (`_carry`): those jobs'
        ids, and how many events, in the same transaction."""
        job = ReparseJob(
            job_id=new_id(),
            source_id=source_id,
            template_id=template_id,
            user_id=user_id,
            state="running",
            started_at=self._clock().isoformat(),
            finished_at=None,
            rows_found=found,
            rows_rewritten=0,
            files_rewritten=0,
            time_min=None,
            time_max=None,
            error=None,
        )
        with self._meta.connect() as con:
            con.execute(
                f"INSERT INTO reparse_jobs ({_COLUMNS})"  # noqa: S608
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.source_id,
                    job.template_id,
                    job.user_id,
                    job.state,
                    job.started_at,
                    job.finished_at,
                    job.rows_found,
                    job.rows_rewritten,
                    job.files_rewritten,
                    job.time_min,
                    job.time_max,
                    job.error,
                ),
            )
            carried_from, carried, lo, hi = self._carry(con, job)
            if carried_from:
                con.execute(
                    "UPDATE reparse_jobs SET time_min = ?, time_max = ? WHERE job_id = ?",
                    (lo, hi, job.job_id),
                )
                job = replace(job, time_min=lo, time_max=hi)
        return job, carried_from, carried

    @staticmethod
    def _carry(
        con: sqlite3.Connection, job: ReparseJob
    ) -> tuple[list[str], int, str | None, str | None]:
        """Move the recorded ids of the source's jobs that stopped (`STOPPED`) before their
        rules ran to `job`, which starts with none, and return those jobs, the number of
        events, and the range that covers theirs. They keep their history (state, counts,
        range) but no ids, so they offer no rule re-run, and a later job finds none to take
        over again. Their ranges were recorded with their ids (`_save`), by the same
        `coalesce(time, time_observed)` rule."""
        stopped = con.execute(
            "SELECT job_id, time_min, time_max FROM reparse_jobs"
            " WHERE source_id = ? AND job_id <> ? AND state IN (?, ?) AND rules_state IS NULL"
            " AND EXISTS (SELECT 1 FROM reparse_job_events e"
            " WHERE e.job_id = reparse_jobs.job_id)"
            " ORDER BY started_at, rowid",
            (job.source_id, job.job_id, *STOPPED),
        ).fetchall()
        taken: list[str] = []
        events = 0
        lo: datetime | None = None
        hi: datetime | None = None
        seq = 0  # the next chunk's number in the new job
        for old in stopped:
            top, n = con.execute(
                "SELECT max(seq), coalesce(sum(json_array_length(event_ids)), 0)"
                " FROM reparse_job_events WHERE job_id = ?",
                (old["job_id"],),
            ).fetchone()
            con.execute(
                "UPDATE reparse_job_events SET job_id = ?, seq = seq + ? WHERE job_id = ?",
                (job.job_id, seq, old["job_id"]),
            )
            seq += int(top) + 1
            events += int(n)
            taken.append(old["job_id"])
            lo = _earliest(lo, _parse(old["time_min"]))
            hi = _latest(hi, _parse(old["time_max"]))
        return taken, events, _iso(lo), _iso(hi)

    def _unpublished(self, job_id: str) -> set[str]:
        """Ids the job took over whose file may not have been published (see `_intend`)."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT event_ids FROM reparse_job_events WHERE job_id = ? AND published = 0",
                (job_id,),
            ).fetchall()
        return {str(i) for r in rows for i in json.loads(r[0])}

    def _intend(self, job: ReparseJob, r: ReparseResult, ids: list[str]) -> list[int]:
        """Before a file is published: the event ids it rewrites (the rule re-run reads only
        these rows, so rows parsed normally between two outages are not alerted on again)
        and the range that covers them, in one transaction. Chunked as the re-run binds
        them, after any taken over at the start; `published` stays 0 until `_save`. A stop
        before the publish leaves the rows waiting, and the next job, which takes these ids
        over, rewrites them with the same ids. Returns the chunks written."""
        lo, hi = _span(job, r)
        with self._meta.connect() as con:
            seq = int(
                con.execute(
                    "SELECT coalesce(max(seq), -1) + 1 FROM reparse_job_events WHERE job_id = ?",
                    (job.job_id,),
                ).fetchone()[0]
            )
            chunks = [ids[i : i + ID_CHUNK] for i in range(0, len(ids), ID_CHUNK)]
            con.executemany(
                "INSERT INTO reparse_job_events (job_id, seq, event_ids, published)"
                " VALUES (?, ?, ?, 0)",
                [(job.job_id, seq + n, json.dumps(c)) for n, c in enumerate(chunks)],
            )
            con.execute(
                "UPDATE reparse_jobs SET time_min = ?, time_max = ? WHERE job_id = ?",
                (lo, hi, job.job_id),
            )
        return [seq + n for n in range(len(chunks))]

    def _save(self, job: ReparseJob, r: ReparseResult, written: list[int]) -> None:
        """Progress after a file is published, and its recorded chunks marked published."""
        lo, hi = _span(job, r)
        with self._meta.connect() as con:
            con.executemany(
                "UPDATE reparse_job_events SET published = 1 WHERE job_id = ? AND seq = ?",
                [(job.job_id, seq) for seq in written],
            )
            con.execute(
                "UPDATE reparse_jobs SET rows_rewritten = ?, files_rewritten = ?, time_min = ?,"
                " time_max = ? WHERE job_id = ?",
                (r.rows, r.files, lo, hi, job.job_id),
            )

    def _end(self, job: ReparseJob, state: State, r: ReparseResult, error: str | None) -> None:
        lo, hi = _span(job, r)
        with self._meta.connect() as con:
            con.execute(
                "UPDATE reparse_jobs SET state = ?, finished_at = ?, rows_rewritten = ?,"
                " files_rewritten = ?, time_min = ?, time_max = ?, error = ? WHERE job_id = ?",
                (
                    state,
                    self._clock().isoformat(),
                    r.rows,
                    r.files,
                    lo,
                    hi,
                    error,
                    job.job_id,
                ),
            )
        self._audit.write(
            "source.reparse",
            "success" if state == "done" else "failure",
            job.user_id,  # the admin who started it: the job is their action
            None,
            {
                "step": "end",
                "job_id": job.job_id,
                "source_id": job.source_id,
                "template_id": job.template_id,
                "state": state,
                "rows_rewritten": r.rows,
                "files_rewritten": r.files,
                "files_skipped": r.skipped_files,
                "time_min": lo,
                "time_max": hi,
            },
        )


def latest_jobs_query(source_ids: list[str]) -> tuple[str, list[str]]:
    """Driven by the listed sources: each one's job to show, read through the
    `reparse_jobs_source (source_id, started_at)` index, so the table is never scanned. A
    job whose rule re-run is partial is shown before newer jobs, so "Run the remaining
    rules" stays offered until it is done (a newer reparse does not take its ids over)."""
    values = ", ".join("(?)" for _ in source_ids)
    sql = (
        f"SELECT {_READ_COLUMNS} FROM reparse_jobs WHERE rowid IN ("  # noqa: S608
        " SELECT (SELECT j.rowid FROM reparse_jobs j WHERE j.source_id = s.column1"
        " ORDER BY (j.rules_state IS 'partial') DESC, j.started_at DESC, j.rowid DESC"
        " LIMIT 1)"
        f" FROM (VALUES {values}) s)"
    )
    return sql, list(source_ids)


def latest_jobs(meta: MetaDB, source_ids: list[str]) -> dict[str, ReparseJob]:
    if not source_ids:
        return {}
    sql, args = latest_jobs_query(source_ids)
    with meta.connect() as con:
        rows = con.execute(sql, args).fetchall()
    return {r["source_id"]: ReparseJob(*r) for r in rows}


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _earliest(a: datetime | None, b: datetime | None) -> datetime | None:
    return b if a is None else a if b is None else min(a, b)


def _latest(a: datetime | None, b: datetime | None) -> datetime | None:
    return b if a is None else a if b is None else max(a, b)


def _span(job: ReparseJob, r: ReparseResult) -> tuple[str | None, str | None]:
    """The job's range: its own rewritten rows' and the range it took over at the start."""
    return (
        _iso(_earliest(_parse(job.time_min), r.time_min)),
        _iso(_latest(_parse(job.time_max), r.time_max)),
    )
