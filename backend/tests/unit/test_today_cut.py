"""A read whose earlier rows today are in a partial rollup build (`after`) keeps only the
rows observed after the cutoff, and does so with a filter DuckDB pushes into the Parquet
scan, so today's files are not read whole (owner re-time, 2026-11-01)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_schedules import _lake_rows

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
CUT = NOW - timedelta(minutes=30)


def _lake(tmp_path: Path) -> QueryEngine:
    lake = tmp_path / "lake"
    w = LakeWriter(lake)
    w.write(_lake_rows("m365", "m365_signin", NOW - timedelta(hours=3), 10))  # before cut
    w.write(_lake_rows("m365", "m365_signin", NOW - timedelta(minutes=10), 5))  # after
    w.write(_lake_rows("m365", "m365_signin", NOW - timedelta(days=1), 4))  # yesterday
    w.write(_lake_rows("dns", "dns_bind", NOW - timedelta(hours=3), 3))  # not in `after`
    return QueryEngine(lake)


def test_today_rows_before_the_cutoff_are_left_out(tmp_path: Path) -> None:
    engine = _lake(tmp_path)
    scope = QueryScope(None, NOW - timedelta(days=2), NOW + timedelta(hours=1))
    rows = engine.run(
        "SELECT source_id, count(*) FROM events GROUP BY 1 ORDER BY 1",
        scope,
        after=(["m365"], CUT),
    ).rows
    # m365: 5 today after the cut plus 4 yesterday; dns untouched.
    assert rows == [["dns", 3], ["m365", 9]]


def test_the_cutoff_is_pushed_into_the_scan(tmp_path: Path) -> None:
    engine = _lake(tmp_path)
    scope = QueryScope(None, NOW - timedelta(days=2), NOW + timedelta(hours=1))
    con: duckdb.DuckDBPyConnection = engine._connect(scope, after=(["m365"], CUT))
    try:
        plan = "\n".join(
            str(r[1]) for r in con.execute("EXPLAIN SELECT count(*) FROM events").fetchall()
        )
    finally:
        con.close()
    scans = plan.split("READ_PARQUET")
    assert len(scans) >= 3  # today's folder is read apart from the rest
    assert any("time_observed>" in s.replace(" ", "") for s in scans[1:])
