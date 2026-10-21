"""Damaged lake files (SPEC D51): empty or unreadable part files are moved to
quarantine instead of breaking queries and maintenance; writes are flushed first."""

from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.compaction import Compactor
from app.ingest.durable import quarantine_dir, quarantined_count, readable, sweep
from app.ingest.writer import LakeWriter
from tests.integration.test_lake_maintenance import rows


def row(i: int) -> dict[str, Any]:
    (r,) = rows("demo", date(2026, 10, 14), 1, start=i)
    return r


def test_writer_leaves_no_temp_files_and_files_read(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    (path,) = LakeWriter(lake).write([row(1), row(2)])
    assert readable(path) is None and pq.read_table(path).num_rows == 2
    assert not list(path.parent.glob(".*.tmp"))


def test_empty_files_are_quarantined_and_queries_work(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    w = LakeWriter(lake)
    good = w.write([row(1)])[0]
    for n in range(3):
        (good.parent / f"part-empty{n}.parquet").write_bytes(b"")
    (good.parent / "part-garbage.parquet").write_bytes(b"not parquet at all")
    assert sweep(lake) == 3  # the quick pass takes only empty files
    assert sweep(lake, full=True) == 1  # the start-up pass reads every footer
    assert quarantined_count(lake) == 4
    moved = quarantine_dir(lake) / "source=demo" / "day=2026-10-14" / "part-garbage.parquet"
    assert moved.read_bytes() == b"not parquet at all"  # kept, never deleted
    engine = QueryEngine(lake)
    res = engine.run("SELECT count(*) FROM events", QueryScope(None))
    assert res.rows == [[1]]


def test_compaction_skips_a_damaged_input(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    w = LakeWriter(lake)
    a = w.write([row(1)])[0]
    w.write([row(2)])
    w.write([row(3)])
    (a.parent / "part-zz-broken.parquet").write_bytes(b"PAR1 broken")
    report = Compactor(lake, today=lambda: date(2026, 10, 20)).run()
    assert report.files_merged == 3 and report.files_written == 1
    files = list(a.parent.glob("part-*.parquet"))
    assert len(files) == 1 and pq.read_table(files[0]).num_rows == 3
    assert quarantined_count(lake) == 1
