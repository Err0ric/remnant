"""Queries are sized from usable CPUs and capped in number (D79)."""

import threading
from pathlib import Path

import pytest

from app.core.errors import QueryBusyError
from app.core.threads import WORKER_POOL, cap_allocator_arenas, query_threads, usable_cpus
from app.engine.duckdb import QueryEngine, QueryScope


def _cgroup(root: Path, cpu_max: str) -> Path:
    path = root / "sys/fs/cgroup"
    path.mkdir(parents=True)
    (path / "cpu.max").write_text(cpu_max)
    return root


def test_cgroup_quota_limits_usable_cpus(tmp_path: Path) -> None:
    assert usable_cpus(_cgroup(tmp_path, "150000 100000\n")) == min(2, usable_cpus(Path("/x")))


def test_no_quota_keeps_affinity(tmp_path: Path) -> None:
    assert usable_cpus(_cgroup(tmp_path, "max 100000\n")) == usable_cpus(tmp_path / "none")


def test_cgroup_v1_quota(tmp_path: Path) -> None:
    cpu = tmp_path / "sys/fs/cgroup/cpu"
    cpu.mkdir(parents=True)
    (cpu / "cpu.cfs_quota_us").write_text("100000\n")
    (cpu / "cpu.cfs_period_us").write_text("100000\n")
    assert usable_cpus(tmp_path) == 1


def test_automatic_and_configured_values() -> None:
    # Automatic: queries at once up to the cores (2 to 4), threads so all of them use
    # about twice the cores, not four times (owner, 2026-10-31).
    auto = query_threads(0, 0, cpus=2)
    assert (auto.per_query, auto.at_once) == (2, 2)
    four = query_threads(0, 0, cpus=4)
    assert (four.per_query, four.at_once) == (2, 4)
    assert query_threads(0, 0, cpus=1).per_query == 1
    assert query_threads(0, 0, cpus=32).per_query == 4
    set_ = query_threads(1, 2, cpus=32)
    assert (set_.per_query, set_.at_once) == (1, 2)
    assert set_.peak == WORKER_POOL + 2
    assert set_.headroom_mb > 0


def test_connection_starts_with_the_configured_threads(tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake", threads=2, memory_mb=300)
    con = engine._connect(QueryScope(None))
    try:
        assert con.execute("SELECT current_setting('threads')").fetchone() == (2,)
        limit = con.execute("SELECT current_setting('memory_limit')").fetchone()
        assert limit is not None and "MiB" in str(limit[0])
    finally:
        con.close()


def test_query_waits_for_a_slot_then_reports_busy(tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake", timeout_s=0.2, max_concurrent=1)
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with engine._slot(1):
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    try:
        with pytest.raises(QueryBusyError):
            engine.run("SELECT 1", QueryScope(None))
    finally:
        release.set()
        t.join()
    assert engine.run("SELECT 1 AS n", QueryScope(None)).rows == [[1]]


def test_slots_are_released_after_a_failed_query(tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake", max_concurrent=1)
    for _ in range(3):
        with pytest.raises(Exception):  # noqa: B017  # any failure must free the slot
            engine.run("SELECT * FROM no_such_table", QueryScope(None))
    assert engine.run("SELECT 1 AS n", QueryScope(None)).rows == [[1]]


def test_operator_arena_setting_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    assert cap_allocator_arenas() == "2 (MALLOC_ARENA_MAX)"
