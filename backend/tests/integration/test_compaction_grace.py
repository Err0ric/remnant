"""D183 (owner, 2026-11-03): AI Watch failed every hour with "IO Error: Cannot open file
... part-....parquet: No such file or directory". Compaction deleted part files a running
7-day DNS read had already listed. Merged files are now retired: left in place for reads
already running, hidden from new ones, deleted after a grace period."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog

from app.core import lake_files
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.compaction import Compactor
from app.ingest.writer import LakeWriter
from tests.integration.test_lake_maintenance import TODAY, rows

DAY = TODAY - timedelta(days=1)
FILES, PER_FILE = 6, 50
SQL = "SELECT count(*), count(DISTINCT event_id) FROM events"


def _lake(tmp_path: Path) -> Path:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    for i in range(FILES):
        writer.write(rows("dns_named", DAY, PER_FILE, start=i * PER_FILE))
    return lake


def _compact_during_read(
    monkeypatch: pytest.MonkeyPatch, engine: QueryEngine, comp: Compactor, runs: int
) -> None:
    """Run compaction right after the read listed its files and before DuckDB opens them:
    the moment a long read and compaction overlap."""
    real = QueryEngine._missing_columns
    done = {"n": 0}

    def listed_then_compact(self: QueryEngine, files: list[str]) -> list[str]:
        out = real(self, files)
        if done["n"] == 0:
            done["n"] = 1
            for _ in range(runs):
                comp.run()
        return out

    monkeypatch.setattr(QueryEngine, "_missing_columns", listed_then_compact)


def test_a_read_that_listed_files_survives_compaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = _lake(tmp_path)
    folder = lake / "source=dns_named" / f"day={DAY.isoformat()}"
    engine = QueryEngine(lake)
    comp = Compactor(lake, today=lambda: TODAY)
    _compact_during_read(monkeypatch, engine, comp, runs=2)
    with structlog.testing.capture_logs() as logs:
        res = engine.run(SQL, QueryScope(None))
    total = FILES * PER_FILE
    assert tuple(res.rows[0]) == (total, total)  # every row once, from the files it listed
    assert not [e for e in logs if e["event"] == "query.retry_vanished_file"]  # no retry needed
    # Compaction did merge: one file for new reads, the six inputs still on disk.
    assert len(lake_files.visible(folder)) == 1
    assert len(list(folder.glob("part-*.parquet"))) == FILES + 1
    res = QueryEngine(lake).run(SQL, QueryScope(None))
    assert tuple(res.rows[0]) == (total, total)  # a new read: no row twice


def test_a_file_gone_after_the_grace_period_is_replanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no grace period (the files really go), the read lists again once and still
    answers right: the engine's retry covers lake reads, not only rollups."""
    lake = _lake(tmp_path)
    engine = QueryEngine(lake)
    comp = Compactor(lake, today=lambda: TODAY, grace_s=0)
    _compact_during_read(monkeypatch, engine, comp, runs=2)  # merge, then delete the inputs
    with structlog.testing.capture_logs() as logs:
        res = engine.run(SQL, QueryScope(None))
    total = FILES * PER_FILE
    assert tuple(res.rows[0]) == (total, total)
    assert [e for e in logs if e["event"] == "query.retry_vanished_file"]


def test_retired_files_go_after_the_grace_period(tmp_path: Path) -> None:
    lake = _lake(tmp_path)
    folder = lake / "source=dns_named" / f"day={DAY.isoformat()}"
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    clock = {"t": now}
    comp = Compactor(lake, today=lambda: TODAY, clock=lambda: clock["t"])
    comp.run()
    assert len(list(folder.glob("part-*.parquet"))) == FILES + 1
    clock["t"] = now + timedelta(seconds=lake_files.RETIRE_GRACE_S - 1)
    assert comp.run().deleted == 0  # still inside the grace period
    clock["t"] = now + timedelta(seconds=lake_files.RETIRE_GRACE_S)
    assert comp.run().deleted == FILES
    assert len(list(folder.glob("part-*.parquet"))) == 1
    assert not (folder / lake_files.RETIRED).exists()


def test_reads_running_alongside_compaction_never_fail(tmp_path: Path) -> None:
    """Many reads of the day while compaction merges new files in, over and over."""
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    comp = Compactor(lake, today=lambda: TODAY)
    engine = QueryEngine(lake)
    errors: list[BaseException] = []
    counts: list[tuple[Any, ...]] = []
    stop = threading.Event()

    def read() -> None:
        while not stop.is_set():
            try:
                counts.append(tuple(engine.run(SQL, QueryScope(None)).rows[0]))
            except BaseException as exc:  # collected for the assertion
                errors.append(exc)

    t = threading.Thread(target=read)
    t.start()
    try:
        for i in range(20):
            writer.write(rows("dns_named", DAY, PER_FILE, start=i * PER_FILE))
            writer.write(rows("dns_named", DAY, PER_FILE, start=(i + 1000) * PER_FILE))
            comp.run()
    finally:
        stop.set()
        t.join()
    assert not errors, errors[:1]
    assert counts and all(n == distinct for n, distinct in counts)  # never a row twice
