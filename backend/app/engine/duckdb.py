"""Read-only query engine over the Parquet lake (SPEC 5.1, CLAUDE.md rules 7 and 13).

Every query gets a fresh in-memory DuckDB connection whose `events` view covers
only the sources in scope and the requested time range. The connection is then
sandboxed: file access limited to those sources' folders, external access off,
configuration locked. The guard runs before any of this.
"""

import glob
import os
import threading
import time
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from app.core.errors import (
    QueryBusyError,
    QueryFailedError,
    QueryMemoryError,
    QueryTimeoutError,
)
from app.core.schema import COLUMN_NAMES, COLUMNS_BY_NAME, duckdb_create_table_sql
from app.engine.guard import DEFAULT_LIMIT, MAX_LIMIT, guard
from app.engine.lookups import Lookups, register
from app.engine.narrow import pinned_sources, pinned_templates

ALLOWED_TABLES = frozenset({"events"})
LAKE_FILES = "day=*/part-*.parquet"  # under each source=<id> folder
DAY_FILES = "part-*.parquet"  # under each day=<date> folder
# Threat intel lists (ADR-0023 row 7) are readable in SQL, but never by a model: Ask's
# previews and the MCP server run with intel=False, so feed text cannot reach a prompt.
INTEL_TABLES = ALLOWED_TABLES | {"threat_intel"}
# The daily AI rollup (ADR-0035 Part 1): server-built queries only. Users, saved searches,
# Ask, and MCP never see this table; `run(..., rollup=True)` is not reachable from them.
ROLLUP_TABLES = ALLOWED_TABLES | {
    "ai_rollup", "ai_ident", "ai_today", "m365_rollup", "auth_rollup"
}  # fmt: skip
# The AI rollup's today so far (D136): rollup/ai/today/source=<id>/part-<n>.parquet and
# ident-<n>.parquet, one pair per build, each row labeled with its build.
TODAY_DIR = "today"
TODAY_FILES = "part-*.parquet"
TODAY_IDENT_FILES = "ident-*.parquet"
ROLLUP_FILES = "day=*/part-*.parquet"  # under rollup/ai/source=<id> and rollup/m365/source=<id>
# Who or which machine had an address, per closed day (`app.search.addresses.IDENT_RAW`,
# reduced): the address lookup reads closed days from here, never from events.
IDENT_FILE = "ident.parquet"
IDENT_COLUMNS = (
    "kind VARCHAR, ip VARCHAR, t TIMESTAMPTZ, who VARCHAR, host VARCHAR, mac VARCHAR,"
    " fin BOOLEAN, src VARCHAR, dev VARCHAR, day VARCHAR"
)
ROLLUP_COLUMNS = (
    "source_id VARCHAR, classification VARCHAR, service_id VARCHAR, who0 VARCHAR,"
    " shost VARCHAR, ip VARCHAR, dev VARCHAR, t TIMESTAMPTZ, n BIGINT,"
    " first_t TIMESTAMPTZ, last_t TIMESTAMPTZ"
)
# The daily Microsoft 365 rollup (ADR-0041): the Overview's facts per closed day.
M365_ROLLUP_COLUMNS = (
    "kind VARCHAR, source_id VARCHAR, t TIMESTAMPTZ, outcome VARCHAR, risky BOOLEAN,"
    " who VARCHAR, app VARCHAR, ip VARCHAR, reason VARCHAR, code INTEGER, op VARCHAR,"
    " k VARCHAR, sub VARCHAR, status INTEGER, n BIGINT, last_t TIMESTAMPTZ, day VARCHAR"
)
AUTH_ROLLUP_COLUMNS = (
    "kind VARCHAR, source_id VARCHAR, t TIMESTAMPTZ, ip VARCHAR, host VARCHAR, n BIGINT,"
    " day VARCHAR"
)
INTEL_COLUMNS = (
    "indicator VARCHAR, type VARCHAR, feed VARCHAR, threat VARCHAR,"
    " first_seen VARCHAR, last_seen VARCHAR"
)


def spill_dir(data_dir: Path) -> Path:
    """The folder queries spill to, under the data folder (always writable), emptied at
    start: spill files from a stopped server are never read again (F46)."""
    path = data_dir / "tmp" / "duckdb"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for leftover in path.iterdir():
        if leftover.is_file():
            leftover.unlink(missing_ok=True)
    return path


@dataclass(frozen=True, slots=True)
class QueryScope:
    """Computed server-side. `sources=None` means every source in the lake."""

    sources: list[str] | None
    start: datetime | None = None
    end: datetime | None = None


@dataclass(slots=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: int
    executed_sql: str
    sources: list[str] = field(default_factory=list)


class QueryEngine:
    def __init__(
        self,
        lake_dir: Path,
        default_limit: int = DEFAULT_LIMIT,
        max_limit: int = MAX_LIMIT,
        timeout_s: float = 30.0,
        memory_mb: int | None = None,
        threads: int | None = None,
        intel_file: Path | None = None,
        max_concurrent: int = 0,
        temp_dir: Path | None = None,
        rollup_dir: Path | None = None,
        m365_rollup_dir: Path | None = None,
    ) -> None:
        self._lake = lake_dir
        self._rollup = rollup_dir
        # Fact rollups by table (ADR-0041): folder and columns, server-built queries only.
        self._facts: dict[str, tuple[Path | None, str]] = {
            "m365_rollup": (m365_rollup_dir, M365_ROLLUP_COLUMNS)
        }
        self._columns_cache: dict[tuple[str, int], frozenset[str]] = {}
        # Per lake file: its version and template_id ranges per row group (None: unknown).
        self._tpl_cache: dict[Path, tuple[int, list[tuple[str, str]] | None]] = {}
        self._time_cache: dict[Path, tuple[int, datetime | None]] = {}
        # Where a query spills when it needs more than its memory share (F46). DuckDB's
        # default is ".tmp" in the working directory, which a read-only container or a
        # sandboxed service cannot write: the query then fails instead of spilling.
        self._temp_dir = temp_dir
        self._intel = intel_file
        # Per query: DuckDB spills or fails past this, instead of growing without bound.
        self._memory_mb = memory_mb
        self._threads = threads
        # At most this many DuckDB connections at once, each with `threads` threads, so a
        # burst of page loads cannot multiply threads past a container's pids limit (D79).
        # Others wait for a slot, up to the query timeout. 0: no limit.
        self._slots = threading.BoundedSemaphore(max_concurrent) if max_concurrent else None
        self._bg = threading.BoundedSemaphore(1)  # rollup builds, apart from page queries
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._timeout_s = timeout_s
        self._lookups: Lookups | None = None

    def set_lookups(self, lookups: Lookups) -> None:
        """The local lookups behind ip_country, ip_asn, ip_org, and is_internal (ADR-0039)."""
        self._lookups = lookups

    def run(
        self,
        sql: str,
        scope: QueryScope,
        params: Mapping[str, Any] | None = None,
        row_cap: int | None = None,
        timeout_s: float | None = None,
        intel: bool = True,
        rollup: bool = False,
        skip_days: Collection[str] = (),
        name: str = "query",
        after: tuple[Collection[str], datetime] | None = None,
        upto: datetime | None = None,
        background: bool = False,
    ) -> QueryResult:
        """Run guarded SQL. `params` are bound by the driver ($name), never formatted in.
        `row_cap` lowers both the implicit and the maximum LIMIT (Ask previews use 5), and
        `timeout_s` can only shorten the configured timeout. `skip_days` ("source|day")
        leaves those day folders out of `events` (the AI rollup has them, F63); `name` is
        what a memory error reports, for the log. `after` (sources, cutoff): of those
        sources, `events` keeps only rows observed after the cutoff (today's earlier rows are
        in a fact rollup's partial day, D135); `upto`: only rows observed by then (building
        that partial day). `background` (rollup builds): one DuckDB thread, half a memory
        share, and its own single slot, so a build never takes a page query's slot."""
        limit_s = min(self._timeout_s, timeout_s) if timeout_s else self._timeout_s
        default = min(self._default_limit, row_cap) if row_cap else self._default_limit
        cap = min(self._max_limit, row_cap) if row_cap else self._max_limit
        # Ask for one extra row so truncation is detectable, then trim it.
        tables = INTEL_TABLES if intel else ALLOWED_TABLES
        if rollup:
            tables = tables | ROLLUP_TABLES
        guarded = guard(sql, tables, default + 1, cap + 1)
        pinned = pinned_sources(guarded.sql, params)
        if pinned is not None:  # read only the sources the query can use; never widen
            keep = pinned if scope.sources is None else pinned & set(scope.sources)
            scope = replace(scope, sources=sorted(keep))
        templates = pinned_templates(guarded.sql, params)
        if templates is not None:  # and only sources whose files can hold those templates
            scope = replace(scope, sources=self._holding(scope, templates, skip_days))
        with self._background_slot(limit_s) if background else self._slot(limit_s):
            return self._execute(
                guarded, scope, params, intel, limit_s, cap, rollup, frozenset(skip_days), name,
                after, upto, background,
            )  # fmt: skip

    def _execute(
        self,
        guarded: Any,
        scope: QueryScope,
        params: Mapping[str, Any] | None,
        intel: bool,
        limit_s: float,
        cap: int,
        rollup: bool = False,
        skip: frozenset[str] = frozenset(),
        name: str = "query",
        after: tuple[Collection[str], datetime] | None = None,
        upto: datetime | None = None,
        background: bool = False,
    ) -> QueryResult:
        con = self._connect(
            scope, intel=intel, rollup=rollup, skip=skip, after=after, upto=upto,
            background=background,
        )  # fmt: skip
        timer = threading.Timer(limit_s, con.interrupt)
        started = time.perf_counter()
        try:
            # Inside the try: if no thread can start, the connection is still closed.
            timer.start()
            cursor = con.execute(guarded.sql, dict(params)) if params else con.execute(guarded.sql)
            rows = cursor.fetchall()
            columns = [d[0] for d in cursor.description or []]
        except duckdb.InterruptException as exc:
            raise QueryTimeoutError(f"Query exceeded {limit_s:g}s and was stopped") from exc
        except (duckdb.OutOfMemoryException, MemoryError) as exc:
            raise QueryMemoryError(
                "The query needs more memory than this server allows. Narrow the time range "
                "or the sources, or aggregate before returning rows",
                query=name,
            ) from exc
        except duckdb.Error as exc:
            raise QueryFailedError(self._scrub(str(exc).splitlines()[0])[:300]) from exc
        finally:
            timer.cancel()
            con.close()

        truncated = False
        if guarded.applied_limit is not None and len(rows) >= guarded.applied_limit:
            rows = rows[: guarded.applied_limit - 1]
            truncated = True
        if len(rows) > cap:  # a literal LIMIT just above the cap is left alone by the guard
            rows = rows[:cap]
            truncated = True
        shown_sql = guarded.sql
        if guarded.applied_limit is not None:
            shown_sql = shown_sql.rsplit("LIMIT", 1)[0] + f"LIMIT {guarded.applied_limit - 1}"
        return QueryResult(
            columns=columns,
            rows=[[_json_safe(v) for v in row] for row in rows],
            truncated=truncated,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            executed_sql=shown_sql,
            sources=[d.name.removeprefix("source=") for d in self._source_dirs(scope)],
        )

    @contextmanager
    def _slot(self, wait_s: float) -> Iterator[None]:
        if self._slots is None:
            yield
            return
        if not self._slots.acquire(timeout=wait_s):
            raise QueryBusyError(
                "The server is running as many queries as it allows; try again in a moment"
            )
        try:
            yield
        finally:
            self._slots.release()

    @contextmanager
    def _background_slot(self, wait_s: float) -> Iterator[None]:
        """One rollup build at a time, apart from the page queries' slots."""
        if not self._bg.acquire(timeout=wait_s):
            raise QueryBusyError("A rollup build is already running")
        try:
            yield
        finally:
            self._bg.release()

    def _scrub(self, message: str) -> str:
        """Server paths stay out of error text shown to analysts and models."""
        for path in {str(self._lake.resolve()), str(self._lake)}:
            message = message.replace(path, "<lake>")
        return message

    def sources_in(self, scope: QueryScope) -> list[str]:
        """Sources with data that a query in this scope would read. Lake truth, so a
        source removed from configuration but still holding data is included."""
        return [d.name.removeprefix("source=") for d in self._source_dirs(scope)]

    def local_only_sources(self, scope: QueryScope) -> list[str]:
        """Sources in scope holding any event not stamped cloud_allowed at ingest.

        Server-built SQL with no caller input, so it does not pass through the guard.
        """
        if not self._source_dirs(scope):
            return []
        with self._slot(self._timeout_s):
            return self._local_only(scope)

    def _local_only(self, scope: QueryScope) -> list[str]:
        con = self._connect(scope)
        try:
            rows = con.execute(
                "SELECT DISTINCT source_id FROM events"
                " WHERE classification IS DISTINCT FROM 'cloud_allowed' ORDER BY 1"
            ).fetchall()
        finally:
            con.close()
        return [str(r[0]) for r in rows]

    def _source_dirs(self, scope: QueryScope) -> list[Path]:
        if not self._lake.is_dir():
            return []
        dirs = sorted(d for d in self._lake.glob("source=*") if d.is_dir())
        if scope.sources is not None:
            wanted = set(scope.sources)
            dirs = [d for d in dirs if d.name.removeprefix("source=") in wanted]
        # Only files where the writer puts them: anything else under the lake is not read,
        # so a file dropped in another folder cannot add events (security review, D64).
        return [d for d in dirs if any(d.glob(LAKE_FILES))]

    def _holding(self, scope: QueryScope, templates: set[str], skip: Collection[str]) -> list[str]:
        """Sources in scope with a file in range whose template_id statistics allow one of
        `templates`. Read from Parquet footers, cached per file version; a file without
        statistics counts as holding them."""
        out = []
        for d in self._source_dirs(scope):
            for pattern in self._lake_globs([d], scope, frozenset(skip)):
                if any(self._may_hold(Path(f), templates) for f in glob.glob(pattern)):
                    out.append(d.name.removeprefix("source="))
                    break
        return out

    def _may_hold(self, path: Path, templates: set[str]) -> bool:
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return False
        hit = self._tpl_cache.get(path)
        if hit is None or hit[0] != stamp:
            ranges: list[tuple[str, str]] | None = None
            try:
                meta = pq.read_metadata(path)
                col = meta.schema.names.index("template_id")
                stats = [
                    meta.row_group(i).column(col).statistics for i in range(meta.num_row_groups)
                ]
                if all(st is not None and st.has_min_max for st in stats):
                    ranges = [(str(st.min), str(st.max)) for st in stats if st is not None]
            except (OSError, ValueError, pa.ArrowException):
                ranges = None
            if len(self._tpl_cache) > 50_000:
                self._tpl_cache.clear()
            self._tpl_cache[path] = hit = (stamp, ranges)
        if hit[1] is None:
            return True
        return any(lo <= t <= hi for lo, hi in hit[1] for t in templates)

    def first_times(self, scope: QueryScope) -> dict[str, datetime]:
        """Each source in scope -> when its data starts, from the Parquet statistics of its
        earliest day folder in range (no rows read), never before the scope's start. The
        lower of `time` and `time_observed` per row group, so it is never later than the
        first event."""
        out: dict[str, datetime] = {}
        for source, day in self.first_days(scope).items():
            folder = self._lake / f"source={source}" / f"day={day}"
            lows = [self._time_min(f) for f in sorted(folder.glob(DAY_FILES))]
            if lows and all(t is not None for t in lows):
                first = min(t for t in lows if t is not None)
            else:
                # A file without min and max statistics: read that one day of that source
                # (owner, 2026-10-31), never report no start.
                found = self._first_by_scan(source, day, scope)
                if found is None:
                    continue
                first = found
            if scope.start is not None:
                first = max(first, scope.start.astimezone(UTC))
            out[source] = first
        return out

    def _first_by_scan(self, source: str, day: str, scope: QueryScope) -> datetime | None:
        begins = datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC)
        lo = max(begins, scope.start.astimezone(UTC)) if scope.start else begins
        hi = begins + timedelta(days=1)
        if scope.end is not None:
            hi = min(hi, scope.end.astimezone(UTC))
        res = self.run(
            "SELECT min(coalesce(time, time_observed)) FROM events",
            QueryScope([source], lo, hi),
            name="first_event",
        )
        v = res.rows[0][0] if res.rows else None
        if v is None:
            return None
        t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
        return t if t.tzinfo else t.replace(tzinfo=UTC)

    def _time_min(self, path: Path) -> datetime | None:
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return None
        hit = self._time_cache.get(path)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        low: datetime | None = None
        try:
            meta = pq.read_metadata(path)
            names = meta.schema.names
            for col in ("time", "time_observed"):
                if col not in names:
                    continue
                i = names.index(col)
                for g in range(meta.num_row_groups):
                    st = meta.row_group(g).column(i).statistics
                    if st is not None and st.has_min_max and isinstance(st.min, datetime):
                        v = st.min if st.min.tzinfo else st.min.replace(tzinfo=UTC)
                        low = v if low is None or v < low else low
        except (OSError, ValueError, pa.ArrowException):
            low = None
        if len(self._time_cache) > 50_000:
            self._time_cache.clear()
        self._time_cache[path] = (stamp, low)
        return low

    def first_days(self, scope: QueryScope) -> dict[str, str]:
        """Each source in scope -> its earliest day folder with files, inside the range."""
        first = scope.start.astimezone(UTC).date().isoformat() if scope.start else ""
        last = scope.end.astimezone(UTC).date().isoformat() if scope.end else "9999-12-31"
        out: dict[str, str] = {}
        for d in self._source_dirs(scope):
            days = sorted(
                x.name.removeprefix("day=")
                for x in d.glob("day=*")
                if first <= x.name.removeprefix("day=") <= last and any(x.glob(DAY_FILES))
            )
            if days:
                out[d.name.removeprefix("source=")] = days[0]
        return out

    def _today_dirs(self, scope: QueryScope) -> list[Path]:
        """The AI rollup's today-so-far folders of the sources in scope (rule 13)."""
        if self._rollup is None:
            return []
        root = self._rollup / TODAY_DIR
        if not root.is_dir():
            return []
        dirs = sorted(d for d in root.glob("source=*") if d.is_dir())
        if scope.sources is not None:
            wanted = set(scope.sources)
            dirs = [d for d in dirs if d.name.removeprefix("source=") in wanted]
        return dirs

    def add_rollup(self, table: str, folder: Path, columns: str) -> None:
        """A fact rollup readable as `table` by server-built queries (rollup=True)."""
        if table not in ROLLUP_TABLES:
            raise ValueError(f"not a rollup table: {table}")
        self._facts[table] = (folder, columns)

    def rollup_dirs(
        self, scope: QueryScope, m365: bool = False, table: str | None = None
    ) -> list[Path]:
        """Rollup folders of the sources in scope: the same scope as `events`, so the rollup
        never shows a source the caller may not read (ADR-0035 row 4). `table`: a fact
        rollup's (`m365`: the Microsoft 365 one) instead of the AI rollup's."""
        if m365:
            table = "m365_rollup"
        root = self._facts.get(table, (None, ""))[0] if table else self._rollup
        if root is None or not root.is_dir():
            return []
        dirs = sorted(d for d in root.glob("source=*") if d.is_dir())
        if scope.sources is not None:
            wanted = set(scope.sources)
            dirs = [d for d in dirs if d.name.removeprefix("source=") in wanted]
        return [d for d in dirs if any(d.glob(ROLLUP_FILES))]

    def _lake_globs(self, dirs: list[Path], scope: QueryScope, skip: frozenset[str]) -> list[str]:
        """File patterns for `events`. With a time range, only the day folders it touches
        (the writer files events by their UTC day), so a 7-day query never opens the other
        days' files; `skip` leaves out days the caller reads from the AI rollup (F63)."""
        if scope.start is None and scope.end is None and not skip:
            return [str(d / LAKE_FILES) for d in dirs]
        first = scope.start.astimezone(UTC).date().isoformat() if scope.start else ""
        last = scope.end.astimezone(UTC).date().isoformat() if scope.end else "9999-12-31"
        out = []
        for d in dirs:
            source = d.name.removeprefix("source=")
            for day_dir in d.glob("day=*"):
                day = day_dir.name.removeprefix("day=")
                if (
                    first <= day <= last
                    and f"{source}|{day}" not in skip
                    and any(day_dir.glob(DAY_FILES))
                ):
                    out.append(str(day_dir / DAY_FILES))
        return sorted(out)

    def _missing_columns(self, patterns: list[str]) -> list[str]:
        """Schema columns no file in scope has. The writer always writes every current
        column, so the newest file shows what all of them have; its footer is read once per
        file version and cached."""
        newest: Path | None = None
        newest_t = -1
        for pattern in patterns:
            for name in glob.glob(pattern):
                t = os.stat(name).st_mtime_ns
                if t > newest_t:
                    newest, newest_t = Path(name), t
        if newest is None:
            return []
        key = (str(newest), newest_t)
        cols = self._columns_cache.get(key)
        if cols is None:
            cols = frozenset(pq.read_schema(newest).names)
            self._columns_cache = {key: cols}  # one entry: the newest file changes as data comes
        return [c for c in COLUMN_NAMES if c not in cols]

    def _connect(
        self,
        scope: QueryScope,
        intel: bool = False,
        rollup: bool = False,
        skip: frozenset[str] = frozenset(),
        after: tuple[Collection[str], datetime] | None = None,
        upto: datetime | None = None,
        background: bool = False,
    ) -> duckdb.DuckDBPyConnection:
        dirs = self._source_dirs(scope)
        # Threads and memory at creation: connecting with the defaults first starts one
        # thread per core the host reports (inside a container, the host's cores), then
        # SET threads starts more (D79).
        config: dict[str, str | bool | int | float | list[str]] = {}
        if background:
            config["threads"] = 1
        elif self._threads:
            config["threads"] = int(self._threads)
        if self._memory_mb:
            share = max(128, self._memory_mb // 2) if background else self._memory_mb
            config["memory_limit"] = f"{int(share)}MB"
        if self._temp_dir is not None:
            config["temp_directory"] = str(self._temp_dir)
        con = duckdb.connect(":memory:", config=config)
        con.execute("SET TimeZone = 'UTC'")
        files = self._lake_globs(dirs, scope, skip)
        if files:
            globs = ", ".join(_sql_str(f) for f in files)
            # Every schema column exists in `events`, typed, even when no file in scope has
            # it yet: a column added later (additive migrations, CLAUDE.md rule 9) reads as
            # NULL in files written before it.
            missing = self._missing_columns(files)
            extra = "".join(
                f", CAST(NULL AS {COLUMNS_BY_NAME[c].duckdb_type}) AS {c}" for c in missing
            )
            base = (
                f"(SELECT *{extra} FROM "  # noqa: S608  # schema names and escaped server paths only
                f"read_parquet([{globs}], hive_partitioning = false, union_by_name = true))"
            )
        else:
            con.execute(duckdb_create_table_sql("_empty_events"))
            base = "_empty_events"
        where = _time_filter(scope)
        if after is not None and after[0]:
            listed = ", ".join(_sql_str(x) for x in sorted(after[0]))
            # Only the cutoff's own day (its folder) is in the partial build.
            day0 = after[1].astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            cut = (
                f"(NOT (list_contains([{listed}], source_id)"
                f" AND coalesce(time, time_observed) >= {_ts(day0)}"
                f" AND coalesce(time, time_observed) < {_ts(day0 + timedelta(days=1))})"
                f" OR time_observed > {_ts(after[1])})"
            )
            where = f"{where} AND {cut}" if where else f" WHERE {cut}"
        if upto is not None:
            cut = f"time_observed <= {_ts(upto)}"
            where = f"{where} AND {cut}" if where else f" WHERE {cut}"
        con.execute(f"CREATE VIEW events AS SELECT * FROM {base}{where}")  # noqa: S608  # built from escaped server paths and datetime literals only
        readable = [d.resolve() for d in dirs]
        if rollup:
            rdirs = self.rollup_dirs(scope)
            if rdirs:
                globs = ", ".join(_sql_str(str(d / ROLLUP_FILES)) for d in rdirs)
                hours = []
                if scope.start is not None:
                    hours.append(f"t >= date_trunc('hour', {_ts(scope.start)})")
                if scope.end is not None:
                    hours.append(f"t <= {_ts(scope.end)}")
                where = (" WHERE " + " AND ".join(hours)) if hours else ""
                con.execute(
                    "CREATE VIEW ai_rollup AS SELECT * FROM"  # noqa: S608  # escaped server paths and datetime literals only
                    f" read_parquet([{globs}], hive_partitioning = false){where}"
                )
                readable += [d.resolve() for d in rdirs]
            else:
                con.execute(f"CREATE TABLE ai_rollup ({ROLLUP_COLUMNS})")
            # Days in the range, and the one before (a span may start the day before).
            lo = (
                (scope.start - timedelta(days=1)).astimezone(UTC).date().isoformat()
                if scope.start is not None
                else ""
            )
            hi = scope.end.astimezone(UTC).date().isoformat() if scope.end is not None else "~"
            idents = [
                str(f)
                for d in rdirs
                for f in sorted(d.glob(f"day=*/{IDENT_FILE}"))
                if lo <= f.parent.name.removeprefix("day=") <= hi
            ]
            # Today so far (D136): use rows and identities per build, labeled by cutoff.
            tdirs = self._today_dirs(scope)
            idents += [str(f) for d in tdirs for f in sorted(d.glob(TODAY_IDENT_FILES))]
            today = [str(f) for d in tdirs for f in sorted(d.glob(TODAY_FILES))]
            if today:
                listed = ", ".join(_sql_str(f) for f in today)
                con.execute(
                    "CREATE VIEW ai_today AS SELECT * FROM"  # noqa: S608  # escaped server paths only
                    f" read_parquet([{listed}], hive_partitioning = false, union_by_name = true)"
                )
                readable += [d.resolve() for d in tdirs]
            else:
                con.execute(f"CREATE TABLE ai_today ({ROLLUP_COLUMNS}, label VARCHAR)")
            if idents:
                listed = ", ".join(_sql_str(f) for f in idents)
                con.execute(
                    "CREATE VIEW ai_ident AS SELECT * FROM"  # noqa: S608  # escaped server paths only
                    f" read_parquet([{listed}], hive_partitioning = false)"
                )
            else:
                con.execute(f"CREATE TABLE ai_ident ({IDENT_COLUMNS})")
            for table, (_folder, columns) in self._facts.items():
                mdirs = self.rollup_dirs(scope, table=table)
                if mdirs:
                    globs = ", ".join(_sql_str(str(d / ROLLUP_FILES)) for d in mdirs)
                    con.execute(
                        f"CREATE VIEW {table} AS SELECT * FROM"  # noqa: S608  # fixed table names, escaped server paths
                        f" read_parquet([{globs}], hive_partitioning = false)"
                    )
                    readable += [d.resolve() for d in mdirs]
                else:
                    con.execute(f"CREATE TABLE {table} ({columns})")
        if intel:
            if self._intel is not None and self._intel.is_file():
                con.execute(
                    "CREATE VIEW threat_intel AS SELECT indicator, type, feed, threat,"  # noqa: S608  # escaped server path only
                    f" first_seen, last_seen FROM read_parquet({_sql_str(str(self._intel))})"
                )
                readable.append(self._intel.parent.resolve())
            else:
                con.execute(f"CREATE TABLE threat_intel ({INTEL_COLUMNS})")
        if self._lookups is not None:
            register(con, self._lookups)
        allowed = ", ".join(_sql_str(str(d)) for d in readable)
        con.execute(f"SET allowed_directories = [{allowed}]")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
        return con


def _time_filter(scope: QueryScope) -> str:
    clauses = []
    if scope.start is not None:
        clauses.append(f"coalesce(time, time_observed) >= {_ts(scope.start)}")
    if scope.end is not None:
        clauses.append(f"coalesce(time, time_observed) <= {_ts(scope.end)}")
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _ts(value: datetime) -> str:
    # Formatted from a datetime object, never from user text.
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return f"TIMESTAMPTZ '{aware.astimezone(UTC).isoformat()}'"


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes | bytearray):
        return value.hex()
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return value
