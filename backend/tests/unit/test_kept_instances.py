"""Kept DuckDB instances for page sections (D146, proposed): reused across queries with
Parquet footers cached, each query seeing only its own scope's `events`, and an instance
that was stopped for time is closed rather than reused."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.errors import QueryFailedError, QueryTimeoutError
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_schedules import _lake_rows

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _engine(tmp_path: Path) -> QueryEngine:
    lake = tmp_path / "lake"
    w = LakeWriter(lake)
    w.write(_lake_rows("alpha", "dns_bind", NOW - timedelta(hours=2), 3))
    w.write(_lake_rows("beta", "dns_bind", NOW - timedelta(hours=2), 5))
    engine = QueryEngine(lake, max_concurrent=2, memory_mb=256)
    engine.pool = True
    return engine


def test_instances_are_reused_and_each_query_sees_only_its_scope(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    count = "SELECT count(*), list(DISTINCT source_id) FROM events"
    assert engine.run(count, QueryScope(["alpha"]), page=True).rows == [[3, ["alpha"]]]
    first = engine._idle[0][1]
    assert engine.run(count, QueryScope(["beta"]), page=True).rows == [[5, ["beta"]]]
    assert engine._idle[0][1] is first  # the same instance, its views replaced
    on = first.execute("SELECT current_setting('parquet_metadata_cache')").fetchone()
    assert on == (True,)
    assert engine.run(count, QueryScope([]), page=True).rows == [
        [0, None]
    ]  # no sources: empty events


def test_a_failed_query_keeps_the_instance_and_a_timeout_drops_it(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.run("SELECT 1", QueryScope(None), page=True)
    first = engine._idle[0][1]
    with pytest.raises(QueryFailedError):
        engine.run("SELECT no_such_column FROM events", QueryScope(None), page=True)
    assert engine._idle[0][1] is first
    joined = ", ".join(f"events {t}" for t in "abcdefghij")
    slow = f"SELECT sum(hash(a.raw || j.raw || e.raw)) FROM {joined}"  # 8^10 rows
    with pytest.raises(QueryTimeoutError):
        engine.run(slow, QueryScope(None), timeout_s=0.2, page=True)
    assert all(con is not first for _k, con, _r in engine._idle)


def test_kept_instances_read_only_the_data_folders(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.csv").write_text("a\n1\n")
    engine.run("SELECT 1", QueryScope(None), page=True)
    con = engine._idle[0][1]
    with pytest.raises(Exception, match="Permission"):
        con.execute(f"SELECT * FROM read_csv('{outside / 'x.csv'}')").fetchall()
    with pytest.raises(Exception, match="lock"):
        con.execute("SET enable_external_access = true")
    engine.close_kept()
    assert engine._idle == []


def test_only_page_queries_use_a_kept_instance(tmp_path: Path) -> None:
    """D146: without `page` (user, saved, scheduled, exported, or model-written SQL), and
    for large queries even with it, a new instance opens each time."""
    engine = _engine(tmp_path)
    engine.run("SELECT 1", QueryScope(None))
    engine.run("SELECT 1", QueryScope(None), large=True, page=True)
    assert engine._idle == []
