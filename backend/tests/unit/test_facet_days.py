"""Field counts over the newest days with matches when the whole range took too long (owner
item P6, 2026-11-17; designer finding on PR 662: all matches on an older day gave no
counts): which days are read, that their counts are exactly the counts of those days, that
days without matches are passed over, the time limit, and the caller's scope. The
endpoint: `test_facets.py`."""

import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from app.api.query import text_facet_sql
from app.core.errors import QueryTimeoutError
from app.core.schema import COLUMN_NAMES
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import rows_table
from app.search.facet_days import COUNT_S, day_batches, newest_with_matches

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
DAY0 = datetime(2026, 11, 14, tzinfo=UTC)


def row(source: str, at: datetime, i: int, rare: bool = False) -> dict[str, Any]:
    word = " rareword" if rare else ""
    r: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
    r.update(
        event_id=str(uuid.uuid4()), source_id=source, template_id="t", template_version="1",
        time=at, time_observed=at, raw=f"conn from 192.0.2.{i % 7} id {i}{word}",
        raw_bytes_invalid=False, parse_status="ok", classification="internal",
        owner_id="system", message=None, src_endpoint_ip=f"192.0.2.{i % 7}",
        actor_user_name=["alice", "bob", "carol"][i % 3],
    )  # fmt: skip
    return r


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ten days of two sources, 20 rows a day each (two files on the newest day); the word
    "rareword" only on day 6 back, in three rows of fw."""
    root: Path = tmp_path_factory.mktemp("facetdays") / "lake"
    for d in range(10):
        for source in ("fw", "dns"):
            folder = root / f"source={source}" / f"day={(DAY0 - timedelta(days=d)).date()}"
            folder.mkdir(parents=True)
            rows = [row(source, DAY0 - timedelta(days=d) + timedelta(minutes=30 * i), i,
                        rare=d == 6 and source == "fw" and i < 3) for i in range(20)]  # fmt: skip
            halves = (rows[:8], rows[8:]) if d == 0 else (rows,)
            for k, part in enumerate(halves):
                pq.write_table(rows_table(part), folder / f"part-{k}.parquet")
    return root


SCOPE = QueryScope(None, NOW - timedelta(days=30))
LATER = 10**9  # a deadline that never comes


def until(seconds: float) -> float:
    return time.monotonic() + seconds


def days_of(files: frozenset[str]) -> set[str]:
    return {Path(f).parent.name for f in files}


def test_batches_are_whole_days_newest_first_within_the_rows(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("")
    # 40 rows a day over both sources: 100 rows is two whole days, never part of a third.
    got = day_batches(engine, sql, SCOPE, params, max_rows=100)
    assert [n for _, n in got] == [2, 2, 2, 2, 2]
    assert days_of(got[0][0]) == {"day=2026-11-14", "day=2026-11-13"}
    assert len(got[0][0]) == 6  # every file of those days, both sources
    assert [n for _, n in day_batches(engine, sql, SCOPE, params, max_rows=1)] == [1] * 10


def test_matches_in_the_newest_days_are_counted_exactly(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("192.0.2.3")
    got = newest_with_matches(engine, "192.0.2.3", sql, SCOPE, params, until(LATER), 100)
    assert got is not None and got.result is not None
    days = QueryScope(None, DAY0 - timedelta(days=1), SCOPE.end)
    assert got.result.rows == engine.run(sql, days, params).rows
    assert got.result.rows != engine.run(sql, SCOPE, params).rows  # fewer days
    assert (got.days, got.skipped) == (2, False)
    count = engine.run("SELECT count(*) FROM events WHERE raw LIKE '%192.0.2.3 %'", days)
    assert got.items == count.rows[0][0] > 0


def test_days_without_matches_are_passed_over(lake: Path) -> None:
    """Every match is on one older day: the counts are that day's, which here are the
    whole range's, never an empty panel."""
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("rareword")
    got = newest_with_matches(engine, "rareword", sql, SCOPE, params, until(LATER), 100)
    assert got is not None and got.result is not None
    assert (got.days, got.items, got.skipped) == (1, 3, True)
    assert got.result.rows == engine.run(sql, SCOPE, params).rows
    assert ["source_id", "fw", 3] in got.result.rows


def stopping(engine: QueryEngine, stop: Any) -> list[dict[str, Any]]:
    """engine.run raising QueryTimeoutError for the calls `stop(sql, nth probe)` picks;
    returns what each call was given."""
    real = engine.run
    seen: list[dict[str, Any]] = []

    def run(sql: str, scope: QueryScope, *a: Any, **k: Any) -> Any:
        probe = "count(DISTINCT" in sql
        seen.append({"probe": probe, "timeout_s": k.get("timeout_s")})
        if stop(sql, sum(c["probe"] for c in seen) if probe else None):
            raise QueryTimeoutError("Query exceeded the time and was stopped")
        return real(sql, scope, *a, **k)

    engine.run = run  # type: ignore[method-assign]
    return seen


def test_out_of_time_before_any_check_says_counting_took_too_long(lake: Path) -> None:
    """Nothing was checked: not "no matches", but the timeout the panel shows with Retry."""
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("rareword")
    with pytest.raises(QueryTimeoutError):
        newest_with_matches(engine, "rareword", sql, SCOPE, params, until(-1), 100)
    stopping(engine, lambda sql, nth: nth == 1)  # the first check runs out of time
    with pytest.raises(QueryTimeoutError):
        newest_with_matches(engine, "rareword", sql, SCOPE, params, until(LATER), 100)


def test_a_batch_with_matches_that_cannot_be_counted_is_a_timeout(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("192.0.2.3")
    seen = stopping(engine, lambda sql, nth: "GROUPING SETS" in sql)
    with pytest.raises(QueryTimeoutError):
        newest_with_matches(engine, "192.0.2.3", sql, SCOPE, params, until(LATER), 100)
    assert [c["probe"] for c in seen] == [True, False]  # it found matches, then the count


def test_days_checked_without_matches_before_time_ran_out(lake: Path) -> None:
    """The first batch was checked and holds no match; the next check ran out of time."""
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("rareword")
    stopping(engine, lambda sql, nth: nth == 2)
    got = newest_with_matches(engine, "rareword", sql, SCOPE, params, until(LATER), 100)
    assert got is not None and got.result is None
    assert (got.days, got.items, got.skipped, got.whole) == (0, 0, True, False)


def test_a_found_batch_keeps_time_for_its_count(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("192.0.2.3")
    seen = stopping(engine, lambda sql, nth: False)
    got = newest_with_matches(engine, "192.0.2.3", sql, SCOPE, params, until(COUNT_S + 3), 100)
    assert got is not None and got.result is not None
    probe, count = seen
    assert probe["timeout_s"] <= 3.0 and count["timeout_s"] >= COUNT_S


def test_no_match_anywhere_is_the_whole_answer(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("nothing-has-this")
    got = newest_with_matches(engine, "nothing-has-this", sql, SCOPE, params, until(LATER), 100)
    assert got is not None and got.whole and got.result is None


def test_none_when_one_batch_is_the_whole_range(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("")
    assert newest_with_matches(engine, "", sql, SCOPE, params, until(LATER), 10_000) is None
    assert (
        newest_with_matches(engine, "", sql, QueryScope(None, DAY0), params, until(LATER), 1)
        is None
    )


def test_the_callers_sources_still_apply(lake: Path) -> None:
    engine = QueryEngine(lake)
    sql, params = text_facet_sql("192.0.2")
    scope = QueryScope(["dns"], SCOPE.start)
    assert all("source=dns" in f for files, _ in day_batches(engine, sql, scope, params, 20)
               for f in files)  # fmt: skip
    got = newest_with_matches(engine, "192.0.2", sql, scope, params, until(LATER), 20)
    assert got is not None and got.result is not None
    assert {r[1] for r in got.result.rows if r[0] == "source_id"} == {"dns"}
