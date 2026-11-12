"""Lake maintenance keeps going past one bad day folder or one failed job, and says so
(audit 2026-11 H7; D236: a stop is never silent).

Before: a file whose footer reads but whose data does not stopped compaction for every
folder sorted after it, and a failed retention delete skipped compaction, the rollups, and
the integrity check in the same tick, with one log line a minute as the only sign.
"""

import errno
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest import maintenance as maintenance_module
from app.ingest.compaction import Compactor
from app.ingest.durable import readable
from app.ingest.maintenance import RETRY_UNDONE_S, LakeMaintenance
from app.ingest.sources import SourceStore
from app.ingest.writer import LakeWriter
from app.main import create_app
from app.meta.db import MetaDB
from tests.integration.test_lake_maintenance import TODAY, count, parts, rows

DAY = TODAY - timedelta(days=1)
NOON = datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=UTC)


def _damage_data(path: Path) -> None:
    """Overwrite the data pages; the footer at the end still reads."""
    footer = pq.read_metadata(path).serialized_size
    blob = bytearray(path.read_bytes())
    for i in range(8, len(blob) - footer - 16):  # the footer and its length stay intact
        blob[i] = 0xFF
    path.write_bytes(bytes(blob))
    assert readable(path) is None  # so the start-up sweep and compaction's check pass it


def _two_sources(lake: Path) -> None:
    writer = LakeWriter(lake)
    for source in ("aaa_first", "zzz_later"):
        for i in range(3):
            writer.write(rows(source, DAY, 10, start=i * 10))


def test_one_unreadable_day_folder_does_not_stop_the_folders_after_it(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _two_sources(lake)
    _damage_data(parts(lake, "aaa_first", DAY)[0])

    report = Compactor(lake, today=lambda: TODAY).run()

    assert len(parts(lake, "zzz_later", DAY)) == 1  # the later folder was still compacted
    assert [name for name, _ in report.failed] == [f"source=aaa_first/day={DAY.isoformat()}"]
    assert count(lake, "source_id = 'zzz_later'") == 30


class Stops:
    """Stands in for alerts.stops.DetectionStops: what was reported, in order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def failing(self, key: str, title: str, reason: str, path: str = "health", **_: Any) -> None:
        self.calls.append(("failing", key))
        self.last = (title, reason, path)

    def working(self, key: str, path: str = "health", **_: Any) -> None:
        self.calls.append(("working", key))


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests compact files they have just written; the wait for new files
    (maintenance.SETTLE_S, tested with the write undo) is not what they are about."""
    monkeypatch.setattr(maintenance_module, "SETTLE_S", 0.0)


clock = {"t": 1000.0}  # the maintenance timer (monotonic seconds), moved by the tests


def _maintenance(tmp_path: Path) -> tuple[LakeMaintenance, Stops]:
    meta = MetaDB(tmp_path / "meta.sqlite")
    clock["t"] = 1000.0
    m = LakeMaintenance(
        tmp_path / "lake", SourceStore(meta, allowed_roots=[tmp_path]), 3650, 3600.0, 86_400.0,
        monotonic=lambda: clock["t"],
    )  # fmt: skip
    m.stops = stops = Stops()  # type: ignore[assignment]  # a stand-in with the same calls
    return m, stops


def test_a_failed_retention_run_does_not_skip_compaction_and_is_reported(
    tmp_path: Path, monkeypatch: Any, pin_now: Any
) -> None:
    pin_now(NOON)
    m, stops = _maintenance(tmp_path)
    _two_sources(tmp_path / "lake")
    ran: list[str] = []

    def denied() -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(m, "apply_retention", denied)
    monkeypatch.setattr(m, "compact", lambda: ran.append("compact") or Compactor(m._lake).run())
    m.after_compaction = lambda: ran.append("rollup")

    m.tick()

    assert ran == ["compact", "rollup"]  # the tick went on past the failed job
    assert [f.job for f in m.jobs.failing()] == ["maintenance.retention"]
    assert ("failing", "maintenance:retention") in stops.calls
    title, reason, path = stops.last
    assert title == "Lake maintenance: retention" and "PermissionError" in reason
    assert path == "health"

    monkeypatch.setattr(m, "apply_retention", lambda: None)
    m.tick()  # a failed job is tried again on the next tick, not a day later
    assert m.jobs.failing() == []
    assert stops.calls[-1] == ("working", "maintenance:retention")


def test_a_day_folder_that_cannot_be_compacted_is_reported_until_it_can(
    tmp_path: Path, pin_now: Any
) -> None:
    pin_now(NOON)
    m, stops = _maintenance(tmp_path)
    lake = tmp_path / "lake"
    _two_sources(lake)
    bad = parts(lake, "aaa_first", DAY)[0]
    _damage_data(bad)

    m.tick()

    assert [f.job for f in m.jobs.failing()] == ["maintenance.compaction"]
    assert ("failing", "maintenance:compaction") in stops.calls
    assert "source=aaa_first" in stops.last[1] and "1 day folder" in stops.last[1]
    # The file whose data does not read was moved aside, so searches over that day work
    # again and the next compaction run finishes the folder and clears the report.
    assert not bad.exists() and count(lake, "source_id = 'aaa_first'") == 20
    # Until the next run the report is repeated every tick, so the grace counts from the
    # first failure; the next run comes after a few minutes, not an hour.
    told = len([c for c in stops.calls if c == ("failing", "maintenance:compaction")])
    m.tick()
    assert len([c for c in stops.calls if c == ("failing", "maintenance:compaction")]) == told + 1
    assert len(parts(lake, "aaa_first", DAY)) == 2  # not compacted again yet
    clock["t"] += RETRY_UNDONE_S
    m.tick()
    assert m.jobs.failing() == []
    assert stops.calls[-1] == ("working", "maintenance:compaction")
    assert len(parts(lake, "aaa_first", DAY)) == 1


# --- review of #531 -------------------------------------------------------------------------


def test_an_error_of_the_system_never_quarantines_a_healthy_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    lake = tmp_path / "lake"
    _two_sources(lake)
    real = pq.read_table

    def no_memory(path: Any, *a: Any, **kw: Any) -> Any:
        if "aaa_first" in str(path):
            raise MemoryError()
        return real(path, *a, **kw)

    monkeypatch.setattr(pq, "read_table", no_memory)
    report = Compactor(lake, today=lambda: TODAY).run()
    assert [name for name, _ in report.failed] == [f"source=aaa_first/day={DAY.isoformat()}"]
    monkeypatch.setattr(pq, "read_table", real)
    assert len(parts(lake, "aaa_first", DAY)) == 3 and count(lake) == 60  # nothing moved


def test_a_disk_error_while_reading_never_quarantines_a_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The guard itself: an I/O error with an errno is the system's (EIO, too many open
    files), not the file's content, so nothing is moved; pyarrow's own error for content
    it cannot read has no errno and does move the file (the test with a damaged file)."""
    lake = tmp_path / "lake"
    _two_sources(lake)
    real = pq.read_table

    def io_error(path: Any, *a: Any, **kw: Any) -> Any:
        if "aaa_first" in str(path):
            raise OSError(errno.EIO, "Input/output error")
        return real(path, *a, **kw)

    monkeypatch.setattr(pq, "read_table", io_error)
    report = Compactor(lake, today=lambda: TODAY).run()
    assert report.failed == [(f"source=aaa_first/day={DAY.isoformat()}", "OSError")]
    monkeypatch.setattr(pq, "read_table", real)
    assert len(parts(lake, "aaa_first", DAY)) == 3 and count(lake) == 60
    assert not (tmp_path / "quarantine").exists()


def test_a_failed_integrity_run_is_tried_again_on_the_next_tick(
    tmp_path: Path, monkeypatch: Any, pin_now: Any
) -> None:
    pin_now(NOON)
    m, stops = _maintenance(tmp_path)
    m._integrity = object()  # type: ignore[assignment]  # only its presence is read here
    calls: list[int] = []

    def verify() -> None:
        calls.append(1)
        if len(calls) < 3:
            raise OSError(5, "Input/output error")

    monkeypatch.setattr(m, "verify", verify)
    for _ in range(4):
        m.tick()
    assert len(calls) == 3  # twice failing, once working, then not again for a day
    assert ("failing", "maintenance:integrity") in stops.calls
    assert stops.calls[-1][0] == "working" and m.jobs.failing() == []


def test_a_report_that_cannot_be_written_does_not_stop_the_later_jobs(
    tmp_path: Path, monkeypatch: Any, pin_now: Any
) -> None:
    pin_now(NOON)
    m, stops = _maintenance(tmp_path)
    ran: list[str] = []

    def locked(*a: Any, **kw: Any) -> None:
        raise OSError("database is locked")

    monkeypatch.setattr(stops, "failing", locked)
    monkeypatch.setattr(stops, "working", locked)
    monkeypatch.setattr(m, "apply_retention", locked)
    monkeypatch.setattr(m, "compact", lambda: ran.append("compact") or Compactor(m._lake).run())
    m.tick()
    assert ran == ["compact"] and [f.job for f in m.jobs.failing()] == ["maintenance.retention"]


def test_the_rollup_build_does_not_run_every_tick_while_compaction_fails(
    tmp_path: Path, monkeypatch: Any, pin_now: Any
) -> None:
    pin_now(NOON)
    m, _ = _maintenance(tmp_path)
    built: list[int] = []
    state = {"fail": True}

    def compact() -> Any:
        if state["fail"]:
            raise OSError(24, "Too many open files")
        return Compactor(m._lake).run()

    monkeypatch.setattr(m, "compact", compact)
    m.after_compaction = lambda: built.append(1)
    for _ in range(3):
        m.tick()
    assert built == [] and [f.job for f in m.jobs.failing()] == ["maintenance.compaction"]
    state["fail"] = False
    m.tick()  # tried again on the next tick, and the rollups follow a run that got through
    assert built == [1] and m.jobs.failing() == []


def test_health_lists_a_failing_maintenance_job(tmp_path: Path) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "data")})
    with TestClient(create_app(config), base_url="http://127.0.0.1") as client:
        app: Any = client.app
        assert app.state.maintenance.stops is app.state.detection_stops
        # A name the running maintenance loop never clears.
        app.state.maintenance.jobs.failed("maintenance.probe", PermissionError(13, "denied"))
        failing = client.get("/api/health-checks").json()["background_failures"]
        assert [f["job"] for f in failing] == ["maintenance.probe"]
