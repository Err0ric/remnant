"""The newest events of a Simple search, newest day first (owner order 2026-11-14).

The Logs page asks for the newest page of a search: `ORDER BY coalesce(time, time_observed)
DESC` with the guard's LIMIT. Over a long window DuckDB used to read every file to find
them. Here the files are listed once, each with the latest `coalesce(time, time_observed)`
its Parquet statistics allow (`QueryEngine.newest_files`), and read newest first, a few
days' worth at a time, until no unread file can hold a row that belongs on the page.

Why the answer is the whole-window answer, row for row:
- Each step runs the same search on the caller's `events` view with the same scope, guard,
  and time filter, narrowed to some of the listed files (`QueryScope.files`). The pages
  of the steps are merged by the same order. The top rows of a union are the top rows of
  the parts' tops.
- The bound is taken from the statistics, not from the folder a file is in, so a file
  whose rows are on another day than its folder's (or without statistics) is still read
  when it may matter. NULL `time` sorts by `time_observed`, which the bound covers.
- It stops once it holds one row past the page (which also settles "only the newest
  rows") whose sort time is later than every unread file's bound. A tie on the sort time
  is broken by `event_id`, in the steps and in the merge, so ties across files and days
  come out the same however the files are grouped (the plain query leaves ties in no set
  order; this is one of its orders).
- The file list is read once: a file compaction retires meanwhile is still read; one that
  is gone fails the step, and the plain whole-window query runs instead, as it does for
  any other failed read or fault in the stepping (a timeout or memory error surfaces).
The whole search shares one timeout. Only server-built Simple search SQL comes here
(`api/query.py`); SQL a person typed runs as written.
"""

import time
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import structlog

from app.core import clock
from app.core.errors import AppError, QueryFailedError, QueryTimeoutError
from app.core.times import utc
from app.engine.duckdb import NO_TIME, QueryEngine, QueryResult, QueryScope
from app.search.simple import RESULT_COLUMNS, compile_search

log = structlog.get_logger()

KEY = "coalesce(time, time_observed)"
# The first read covers the newest day. A later one covers twice the days the matches so far
# say the page needs, and the rest when there were none: a search with few or no matches
# costs two reads (each file once), not one per day. At most MAX_READS before the rest.
FIRST_S = 86_400.0
MAX_READS = 3


def keyed_sql(text: str, limit: int) -> tuple[str, dict[str, Any]]:
    """The search with its sort time as a last column, ties broken by event_id."""
    c = compile_search(text, select=f"{RESULT_COLUMNS}, {KEY} AS newest_key", ordered=False)
    order = f"\nORDER BY {KEY} DESC NULLS LAST, event_id DESC NULLS LAST\nLIMIT {limit}"
    return c.sql + order, c.params


def _rank(row: list[Any], at: int) -> tuple[bool, datetime, bool, str]:
    key = datetime.fromisoformat(row[-1]) if row[-1] is not None else None
    return (key is not None, key or NO_TIME, row[at] is not None, str(row[at] or ""))


def newest_first(
    engine: QueryEngine, text: str, scope: QueryScope, name: str = "query", large: bool = True
) -> QueryResult:
    deadline = time.monotonic() + engine.timeout_s
    try:
        return _stepped(engine, text, scope, name, large, deadline)
    except AppError as exc:
        if not isinstance(exc, QueryFailedError):
            raise  # a timeout, memory, or busy error surfaces as on the plain path
        reason = str(exc)[:120]  # a listed file deleted meanwhile, or a failed read
    except Exception as exc:  # a fault here must not fail the search
        reason = type(exc).__name__
    # The whole window, as before this change, in what is left of the one timeout.
    log.warning("search.newest_first_fallback", query=name, reason=reason)
    plain = compile_search(text)
    left = max(0.001, deadline - time.monotonic())
    return engine.run(plain.sql, scope, plain.params or None, timeout_s=left, name=name,
                      large=large)  # fmt: skip


def _stepped(
    engine: QueryEngine, text: str, scope: QueryScope, name: str, large: bool, deadline: float
) -> QueryResult:
    plain = compile_search(text)
    page = engine.default_limit
    sql, params = keyed_sql(text, page + 1)
    started = time.perf_counter()
    listed = engine.newest_files(sql, scope, params)
    # A start or end without a zone means UTC, as on the plain path (`utc`).
    if scope.start is not None:  # every row of such a file is before the window
        lo = utc(scope.start)
        listed = [f for f in listed if f[1] is None or f[1] >= lo]
    if scope.end is not None:  # a row after the window is not read, so not ranked
        hi = utc(scope.end)
        listed = [(f, t if t is None else min(t, hi)) for f, t in listed]
    unread = sorted(listed, key=lambda f: (f[1] is not None, f[1] or NO_TIME), reverse=True)
    known = [t for _, t in unread if t is not None]
    # Steps count back from the newest bound, or from now when a file holds future times
    # (those files still come first: their bound is later). Bounds only order the reads.
    anchor = min(known[0], clock.now()) if known else None
    reach = (anchor - known[-1]).total_seconds() if anchor is not None else 0.0
    rows: list[list[Any]] = []
    first: QueryResult | None = None
    steps, span = 0, FIRST_S
    while first is None or unread:
        last = rows[page][-1] if len(rows) > page else None
        if last is not None:  # a full page: only files that may hold a later row remain
            edge = datetime.fromisoformat(last)
            unread = [f for f in unread if f[1] is None or f[1] >= edge]
            if not unread:
                break
            batch = unread
        elif anchor is not None and (steps == 0 or (rows and steps < MAX_READS)):
            if steps:  # grow by what the matches so far say the page needs, twice over
                span *= 2 * (page + 1) / len(rows)
            if span >= reach:  # as far back as the oldest file: read the rest
                batch = unread
            else:  # span < reach, so the date stays within the files' own range
                since = anchor - timedelta(seconds=span)
                batch = [f for f in unread if f[1] is None or f[1] >= since] or unread[:1]
        else:
            batch = unread
        left = deadline - time.monotonic()
        if left <= 0:
            raise QueryTimeoutError(f"Query exceeded {engine.timeout_s:g}s and was stopped")
        files = frozenset(f for f, _ in batch)
        unread = [f for f in unread if f[0] not in files]
        res = engine.run(sql, replace(scope, files=files), params or None, timeout_s=left,
                         name=name, large=large)  # fmt: skip
        steps += 1
        first = first or res
        at = res.columns.index("event_id")
        if rows:  # the first read comes in this order from DuckDB; later ones are merged
            rows = sorted(rows + res.rows, key=lambda r: _rank(r, at), reverse=True)[: page + 1]
        else:
            rows = res.rows
    assert first is not None
    return QueryResult(
        columns=first.columns[:-1],
        rows=[r[:-1] for r in rows[:page]],
        truncated=len(rows) > page,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        executed_sql=engine.shown_sql(plain.sql),
        sources=first.sources,
        rows_read=None,
    )
