"""Field counts over the newest days that hold matches, when counting all of a range took
too long (owner item P6, 2026-11-17: on 30 days the Fields panel said "Counting fields took
too long" and showed nothing).

The lake files of the newest whole day folders are read a batch at a time, newest first,
each batch at most `max_rows` rows (at least one day). A batch is first checked for
matches with the same search (how many, and on how many days); a batch with none is passed
over and the next older one checked, in the time left. The first batch with matches is
counted with the same search, scope, guard, and time filter, narrowed to its files
(`QueryScope.files`, a narrower read, never a wider one); its days without matches add
nothing to the counts. Every newer day was checked and holds none, so the counts are those
of the newest days with matches, and the panel says how many days and how many items.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.core.errors import QueryTimeoutError
from app.engine.duckdb import QueryEngine, QueryResult, QueryScope
from app.search.simple import compile_search

SAMPLE_ROWS = 2_000_000
# Time kept for the count once a check finds matches, so a found batch is counted, never
# reported as having none.
COUNT_S = 1.5
DAY = "CAST(coalesce(time, time_observed) AS DATE)"


@dataclass(frozen=True, slots=True)
class Newest:
    """What was counted. `result` None: no day with matches was reached in time, or
    (`whole`) every day was checked and none holds a match, which is the whole answer."""

    result: QueryResult | None
    days: int  # days with matches counted
    items: int  # matches counted
    skipped: bool  # some newer day in range was checked and held none
    whole: bool = False


def day_batches(
    engine: QueryEngine, sql: str, scope: QueryScope, params: Mapping[str, Any] | None,
    max_rows: int,
) -> list[tuple[frozenset[str], int]]:  # fmt: skip
    """The scope's lake files by day folder, newest first, in batches of whole days of at
    most `max_rows` rows each (at least one day), each with its number of days. Lists and
    footers only."""
    days: dict[str, list[str]] = {}
    for f, _ in engine.newest_files(sql, scope, params):
        days.setdefault(Path(f).parent.name, []).append(f)
    out: list[tuple[frozenset[str], int]] = []
    batch: list[str] = []
    rows = count = 0
    for day in sorted(days, reverse=True):  # day=YYYY-MM-DD sorts by date
        n = sum(engine.file_rows(f) or 0 for f in days[day])
        if batch and rows + n > max_rows:
            out.append((frozenset(batch), count))
            batch, rows, count = [], 0, 0
        batch += days[day]
        rows += n
        count += 1
    if batch:
        out.append((frozenset(batch), count))
    return out


def newest_with_matches(
    engine: QueryEngine,
    text: str,
    sql: str,
    scope: QueryScope,
    params: Mapping[str, Any] | None,
    deadline: float,
    max_rows: int = SAMPLE_ROWS,
) -> Newest | None:
    """Counts (`sql`, the facet query of the Filters search `text`) over the newest days
    with matches, before `deadline` (time.monotonic). None when one batch is the whole
    range (the whole count is what took too long). Each check leaves `COUNT_S` for the
    count. Raises QueryTimeoutError when time runs out before anything was settled: no
    check finished, or a batch with matches could not be counted (the panel then says
    counting took too long, with Retry). A result of no days (`days == 0`) means every
    check that finished found no match, and time ran out before an older batch."""
    batches = day_batches(engine, sql, scope, params, max_rows)
    if len(batches) <= 1:
        return None
    probe = compile_search(text, select=f"count(DISTINCT {DAY}) AS days, count(*) AS n",
                           ordered=False)  # fmt: skip
    checked = 0
    for i, (files, count) in enumerate(batches):
        narrowed = replace(scope, files=files)
        left = deadline - time.monotonic() - COUNT_S
        if left <= 0:
            break
        try:
            found = engine.run(probe.sql, narrowed, probe.params or None, timeout_s=left)
        except QueryTimeoutError:
            break
        checked += 1
        days, n = (int(v or 0) for v in found.rows[0])
        if not n:
            continue
        # At least COUNT_S left; a count that still runs out raises: not "no matches".
        left = max(COUNT_S, deadline - time.monotonic())
        result = engine.run(sql, narrowed, params, timeout_s=left)
        return Newest(result, days, n, i > 0 or days < count)
    else:  # every day checked: no match anywhere in range, the whole (empty) answer
        return Newest(None, 0, 0, False, whole=True)
    if not checked:
        raise QueryTimeoutError("Counting fields took too long for this range")
    return Newest(None, 0, 0, True)
