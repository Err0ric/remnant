"""Read-only query engine over the Parquet lake (SPEC 5.1, CLAUDE.md rules 7 and 13).

Every query gets a fresh in-memory DuckDB connection whose `events` view covers
only the sources in scope and the requested time range. The connection is then
sandboxed: file access limited to those sources' folders, external access off,
configuration locked. The guard runs before any of this.
"""

import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from app.core.errors import QueryBusyError, QueryFailedError, QueryTimeoutError
from app.core.schema import duckdb_create_table_sql
from app.engine.guard import DEFAULT_LIMIT, MAX_LIMIT, guard
from app.engine.narrow import pinned_sources

ALLOWED_TABLES = frozenset({"events"})
LAKE_FILES = "day=*/part-*.parquet"  # under each source=<id> folder
# Threat intel lists (ADR-0023 row 7) are readable in SQL, but never by a model: Ask's
# previews and the MCP server run with intel=False, so feed text cannot reach a prompt.
INTEL_TABLES = ALLOWED_TABLES | {"threat_intel"}
INTEL_COLUMNS = (
    "indicator VARCHAR, type VARCHAR, feed VARCHAR, threat VARCHAR,"
    " first_seen VARCHAR, last_seen VARCHAR"
)


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
    ) -> None:
        self._lake = lake_dir
        self._intel = intel_file
        # Per query: DuckDB spills or fails past this, instead of growing without bound.
        self._memory_mb = memory_mb
        self._threads = threads
        # At most this many DuckDB connections at once, each with `threads` threads, so a
        # burst of page loads cannot multiply threads past a container's pids limit (D79).
        # Others wait for a slot, up to the query timeout. 0: no limit.
        self._slots = threading.BoundedSemaphore(max_concurrent) if max_concurrent else None
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._timeout_s = timeout_s

    def run(
        self,
        sql: str,
        scope: QueryScope,
        params: Mapping[str, Any] | None = None,
        row_cap: int | None = None,
        timeout_s: float | None = None,
        intel: bool = True,
    ) -> QueryResult:
        """Run guarded SQL. `params` are bound by the driver ($name), never formatted in.
        `row_cap` lowers both the implicit and the maximum LIMIT (Ask previews use 5), and
        `timeout_s` can only shorten the configured timeout."""
        limit_s = min(self._timeout_s, timeout_s) if timeout_s else self._timeout_s
        default = min(self._default_limit, row_cap) if row_cap else self._default_limit
        cap = min(self._max_limit, row_cap) if row_cap else self._max_limit
        # Ask for one extra row so truncation is detectable, then trim it.
        guarded = guard(sql, INTEL_TABLES if intel else ALLOWED_TABLES, default + 1, cap + 1)
        pinned = pinned_sources(guarded.sql, params)
        if pinned is not None:  # read only the sources the query can use; never widen
            keep = pinned if scope.sources is None else pinned & set(scope.sources)
            scope = replace(scope, sources=sorted(keep))
        with self._slot(limit_s):
            return self._execute(guarded, scope, params, intel, limit_s, cap)

    def _execute(
        self,
        guarded: Any,
        scope: QueryScope,
        params: Mapping[str, Any] | None,
        intel: bool,
        limit_s: float,
        cap: int,
    ) -> QueryResult:
        con = self._connect(scope, intel=intel)
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
            raise QueryFailedError(
                "The query needs more memory than this server allows. Narrow the time range "
                "or the sources, or aggregate before returning rows"
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

    def _connect(self, scope: QueryScope, intel: bool = False) -> duckdb.DuckDBPyConnection:
        dirs = self._source_dirs(scope)
        # Threads and memory at creation: connecting with the defaults first starts one
        # thread per core the host reports (inside a container, the host's cores), then
        # SET threads starts more (D79).
        config: dict[str, str | bool | int | float | list[str]] = {}
        if self._threads:
            config["threads"] = int(self._threads)
        if self._memory_mb:
            config["memory_limit"] = f"{int(self._memory_mb)}MB"
        con = duckdb.connect(":memory:", config=config)
        con.execute("SET TimeZone = 'UTC'")
        if dirs:
            globs = ", ".join(_sql_str(str(d / LAKE_FILES)) for d in dirs)
            base = f"read_parquet([{globs}], hive_partitioning = false, union_by_name = true)"
        else:
            con.execute(duckdb_create_table_sql("_empty_events"))
            base = "_empty_events"
        con.execute(f"CREATE VIEW events AS SELECT * FROM {base}{_time_filter(scope)}")  # noqa: S608  # built from escaped server paths and datetime literals only
        readable = [d.resolve() for d in dirs]
        if intel:
            if self._intel is not None and self._intel.is_file():
                con.execute(
                    "CREATE VIEW threat_intel AS SELECT indicator, type, feed, threat,"  # noqa: S608  # escaped server path only
                    f" first_seen, last_seen FROM read_parquet({_sql_str(str(self._intel))})"
                )
                readable.append(self._intel.parent.resolve())
            else:
                con.execute(f"CREATE TABLE threat_intel ({INTEL_COLUMNS})")
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
