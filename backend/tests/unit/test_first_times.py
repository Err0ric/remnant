"""D135, owner 2026-10-31: when a source's data starts comes from file statistics; a file
without them is read (that one day), never reported as no start."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def _write(lake: Path, when: str) -> None:
    norm = Normalizer(SourceSpec(source_id="fw", format="json"), clock=lambda: NOW)
    row = norm.normalize(DecodedLine(f'{{"time": "{when}"}}', False, False))
    assert row is not None
    LakeWriter(lake).write([row])


def test_from_statistics_and_by_reading_a_file_without_them(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _write(lake, "2026-10-08T09:30:00Z")
    engine = QueryEngine(lake)
    scope = QueryScope(None, NOW - timedelta(days=7), NOW)
    assert engine.first_times(scope)["fw"] == datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
    # Rewrite the day's file without statistics.
    (f,) = list((lake / "source=fw" / "day=2026-10-08").glob("part-*.parquet"))
    table = pq.read_table(f)
    pq.write_table(table, f, write_statistics=False)
    engine = QueryEngine(lake)
    assert engine._time_min(f) is None
    assert engine.first_times(scope)["fw"] == datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
