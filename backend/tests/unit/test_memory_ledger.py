"""Query memory as a shared budget (D58, D80 updated 2026-11-01): page sections get a
share, searches get what is free less two shares, the sum never passes the budget, and
the journal shows fallbacks, disk overflow, and failures."""

import threading
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.core.errors import QueryBusyError, QueryMemoryError
from app.engine import memory as memory_mod
from app.engine.duckdb import QueryEngine, QueryScope, UnsafeSpillDirError, spill_dir
from app.engine.memory import MemoryLedger


@pytest.mark.parametrize(
    ("budget", "share", "large"), [(4096, 819, 1639), (8192, 1638, 3278), (16384, 3276, 6556)]
)
def test_shares_grow_with_the_budget(budget: int, share: int, large: int) -> None:
    ledger = MemoryLedger(budget, 4)
    assert (ledger.share, ledger.large_max) == (share, large)
    alone = ledger.take(large=True, wait_s=0)
    assert (alone.mb, alone.fell_back) == (large, False)


def test_limits_never_pass_the_budget() -> None:
    ledger = MemoryLedger(4096, 4)
    search = ledger.take(large=True, wait_s=0)
    pages = [ledger.take(large=False, wait_s=0) for _ in range(2)]
    assert ledger.used == search.mb + 2 * 819 <= 4096 - 819
    with pytest.raises(QueryBusyError):  # a third page section waits, then gets "busy"
        ledger.take(large=False, wait_s=0.05)
    ledger.give(search)
    late = ledger.take(large=True, wait_s=0)  # two pages running: one share, logged
    assert (late.mb, late.fell_back) == (819, True)
    for g in [*pages, late]:
        ledger.give(g)
    assert ledger.used == 0


def test_a_waiting_page_section_starts_when_a_search_ends() -> None:
    ledger = MemoryLedger(4096, 4)
    search = ledger.take(large=True, wait_s=0)
    held = [ledger.take(large=False, wait_s=0) for _ in range(2)]
    got: list[int] = []
    t = threading.Thread(target=lambda: got.append(ledger.take(large=False, wait_s=5).mb))
    t.start()
    ledger.give(search)
    t.join(5)
    assert got == [819] and len(held) == 2


def _engine(tmp_path: Path, budget: int, spill_mb: int | None = None) -> QueryEngine:
    return QueryEngine(
        tmp_path / "lake", threads=1, max_concurrent=4, memory_budget_mb=budget,
        spill_limit_mb=spill_mb, temp_dir=spill_dir(tmp_path),
    )  # fmt: skip


SPILLS = (
    "SELECT count(*) FROM (SELECT i % 2000000 AS g, sum(i) AS s"
    " FROM (SELECT unnest(range(4000000)) AS i) GROUP BY 1)"
)


@pytest.fixture
def small(monkeypatch: pytest.MonkeyPatch) -> None:
    """40 MB shares from a 200 MB budget, so a few million rows overflow to disk."""
    monkeypatch.setattr(memory_mod, "MIN_SHARE_MB", 16)


@pytest.mark.usefixtures("small")
def test_disk_overflow_is_logged_with_peak_memory(tmp_path: Path) -> None:
    engine = _engine(tmp_path, 200)
    with capture_logs() as logs:
        engine.run(SPILLS, QueryScope(None), name="query.run", large=False)
    rows = [e for e in logs if e["event"] == "query.memory"]
    assert rows and rows[0]["outcome"] == "spilled" and rows[0]["disk_mb"] > 0
    assert rows[0]["kind"] == "page" and rows[0]["limit_mb"] == 40 and rows[0]["peak_mb"] > 0


@pytest.mark.usefixtures("small")
def test_a_full_disk_overflow_fails_plainly(tmp_path: Path) -> None:
    engine = _engine(tmp_path, 200, spill_mb=5)
    with capture_logs() as logs, pytest.raises(QueryMemoryError, match="shorter time range"):
        engine.run(SPILLS, QueryScope(None), name="query.export", large=False)
    failed = [e for e in logs if e["event"] == "query.memory"]
    assert failed[0]["outcome"] == "failed" and failed[0]["reason"] == "disk"


def test_overflow_limit_is_split_by_memory(tmp_path: Path) -> None:
    engine = _engine(tmp_path, 4096, spill_mb=10_240)
    assert engine._spill_for(819) == 2047 and engine._spill_for(1638) == 4095


def test_the_overflow_folder_is_emptied_at_start_and_logged(tmp_path: Path) -> None:
    folder = spill_dir(tmp_path)
    (folder / "duckdb_temp_storage.tmp").write_bytes(b"x" * 2048)
    (folder / "leftover").mkdir()
    (folder / "leftover" / "block").write_bytes(b"x" * 1024)
    keep = tmp_path / "tmp" / "keep.txt"  # beside the folder, in the folder above
    keep.write_text("kept")
    with capture_logs() as logs:
        assert spill_dir(tmp_path) == folder.resolve()
    assert list(folder.iterdir()) == [] and keep.read_text() == "kept"
    cleared = [e for e in logs if e["event"] == "spill.cleared"]
    assert cleared and cleared[0]["files"] == 2 and cleared[0]["mb"] == 0.0


def test_a_link_inside_is_removed_without_following_it(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious").write_text("kept")
    folder = spill_dir(tmp_path / "data")
    (folder / "link").symlink_to(outside, target_is_directory=True)
    spill_dir(tmp_path / "data")
    assert (outside / "precious").read_text() == "kept" and list(folder.iterdir()) == []


@pytest.mark.parametrize("target", ["elsewhere", "data", "data/tmp"])
def test_a_folder_that_resolves_elsewhere_is_refused(tmp_path: Path, target: str) -> None:
    data = tmp_path / "data"
    (data / "tmp").mkdir(parents=True)
    dest = tmp_path / target
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "precious").write_text("kept")
    (data / "tmp" / "duckdb").symlink_to(dest, target_is_directory=True)
    with capture_logs() as logs, pytest.raises(UnsafeSpillDirError, match="Nothing was deleted"):
        spill_dir(data)
    assert (dest / "precious").read_text() == "kept"
    assert any(e["event"] == "spill.refused" for e in logs)


def test_a_linked_data_folder_still_works(tmp_path: Path) -> None:
    real = tmp_path / "real-data"
    real.mkdir()
    (tmp_path / "data").symlink_to(real, target_is_directory=True)
    assert spill_dir(tmp_path / "data") == real / "tmp" / "duckdb"


def test_an_empty_overflow_folder_still_logs_the_check(tmp_path: Path) -> None:
    spill_dir(tmp_path)
    with capture_logs() as logs:
        spill_dir(tmp_path)
    cleared = [e for e in logs if e["event"] == "spill.cleared"]
    assert cleared and cleared[0]["files"] == 0 and cleared[0]["mb"] == 0.0
