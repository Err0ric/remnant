"""A failed lake write leaves nothing behind, so the retry does not store the batch again
(audit 2026-11 H6).

The checkpoint moves only after the write. When the write failed after a file was already
published (the integrity ledger could not record it, or a second day's file could not be
written), that file stayed in the lake and the next pass, two seconds later, wrote the
same lines again, on every pass for as long as the fault lasted.
"""

import sqlite3
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pytest

from app.core.config import load_config
from app.ingest import durable
from app.ingest import maintenance as maintenance_module
from app.ingest import writer as writer_module
from app.ingest.compaction import Compactor
from app.ingest.integrity import NoEvents
from app.ingest.lakelock import lake_lock
from app.ingest.sources import SourceConfig
from app.ingest.writer import LakeWriter
from app.main import create_app
from tests.integration.test_lake_maintenance import TODAY, rows
from tests.integration.test_sources import LINE, count, env, service, write  # noqa: F401


class FailingLedger(NoEvents):
    """The integrity ledger while meta.sqlite cannot be written (disk full, locked)."""

    def __init__(self) -> None:
        self.fail = True

    def added(self, paths: Sequence[Path], reason: str = "") -> None:
        if self.fail:
            raise OSError("database or disk is full")


def _parts(lake: Path) -> list[Path]:
    return sorted(lake.rglob("part-*.parquet"))


def test_a_ledger_failure_does_not_multiply_events(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    ledger = FailingLedger()
    svc._writer._events = ledger
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    for _ in range(3):  # three passes while the fault lasts
        svc.run_once()
    assert _parts(env["data"] / "lake") == []  # nothing half-stored
    assert "Cannot read 1 of 1 files" in (svc.status()["linux_auth"].error or "")
    ledger.fail = False
    assert svc.run_once() == 2
    assert count(env) == 2
    assert svc.status()["linux_auth"].error is None


def test_a_failure_on_a_later_day_removes_the_earlier_days_file(
    env: dict[str, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, store = service(env)
    real, calls = writer_module.publish, []

    def flaky(table, final, *a, **kw):  # type: ignore[no-untyped-def]  # test double
        calls.append(final)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return real(table, final, *a, **kw)

    monkeypatch.setattr(writer_module, "publish", flaky)
    f = env["logs"] / "auth.log"
    two_days = LINE.format(1, 1) + LINE.format(2, 2).replace("Oct  9", "Oct 10")
    write(f, two_days)
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    svc.run_once()
    assert len(calls) == 2 and _parts(env["data"] / "lake") == []
    assert svc.run_once() == 2  # the fault has passed
    assert count(env) == 2


def test_a_position_that_cannot_be_saved_does_not_multiply_events(env: dict[str, Path]) -> None:  # noqa: F811
    """The write and its ledger entry succeed, then the position cannot be saved (the
    database is locked): the files are taken back, so each pass does not add a copy."""
    svc, store = service(env)
    real, state = svc._save_checkpoint, {"fail": True}

    def locked(*a: object, **kw: object) -> None:
        if state["fail"]:
            raise sqlite3.OperationalError("database is locked")
        real(*a, **kw)  # type: ignore[arg-type]  # passed through unchanged

    svc._save_checkpoint = locked  # type: ignore[method-assign]  # test double
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    for _ in range(3):
        svc.run_once()
    assert _parts(env["data"] / "lake") == []
    assert svc.status()["linux_auth"].error
    state["fail"] = False
    assert svc.run_once() == 2
    assert count(env) == 2


def test_a_failed_publish_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(*a: object, **kw: object) -> None:
        Path(str(a[1])).write_bytes(b"partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(durable.pq, "write_table", full)
    with pytest.raises(OSError):
        durable.publish(pa.table({"a": [1]}), tmp_path / "part-x.parquet")
    assert list(tmp_path.iterdir()) == []


def test_compaction_leaves_files_ingest_may_still_take_back(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    for i in range(3):
        LakeWriter(lake).write(rows("app", TODAY - timedelta(days=1), 5, start=i * 5))
    assert Compactor(lake, today=lambda: TODAY, settle_s=60).run().files_merged == 0
    assert Compactor(lake, today=lambda: TODAY).run().files_merged == 3


def test_a_failed_folder_sync_leaves_no_published_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_sync(folder: Path) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(durable, "_fsync_dir", no_sync)
    with pytest.raises(OSError):
        durable.publish(pa.table({"a": [1]}), tmp_path / "part-x.parquet")
    assert list(tmp_path.iterdir()) == []


class StuckLedger(NoEvents):
    """A ledger that records additions but, for a while, cannot record a removal."""

    def __init__(self) -> None:
        self.fail = True

    def removed(self, paths: Sequence[Path], reason: str) -> list[Path]:
        if self.fail:
            raise sqlite3.OperationalError("database is locked")
        return list(paths)


def test_an_undo_that_cannot_be_recorded_stops_new_writes_until_it_can(
    env: dict[str, Path],  # noqa: F811
) -> None:
    svc, store = service(env)
    ledger = StuckLedger()
    svc._writer._events = ledger
    real, state = svc._save_checkpoint, {"fail": True}

    def locked(*a: object, **kw: object) -> None:
        if state["fail"]:
            raise sqlite3.OperationalError("database is locked")
        real(*a, **kw)  # type: ignore[arg-type]  # passed through unchanged

    svc._save_checkpoint = locked  # type: ignore[method-assign]  # test double
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1) + LINE.format(2, 2))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    lake = env["data"] / "lake"
    for _ in range(3):
        svc.run_once()
    owed = _parts(lake)
    assert len(owed) == 1 and svc.held() == set(owed)  # one file, and no copies of it
    # Compaction is told to leave it alone, however old it is.
    for i in range(2):
        LakeWriter(lake).write(rows("linux_auth", date(2026, 10, 9), 3, start=i * 3))
    report = Compactor(lake, today=lambda: TODAY, hold=svc.held).run()
    assert report.files_merged == 2 and owed[0].exists()
    ledger.fail = False  # the removal can be recorded: the next pass takes the file back
    state["fail"] = False
    assert svc.run_once() == 2
    assert not owed[0].exists() and svc.held() == set()
    assert count(env, "source_id = 'linux_auth' AND message LIKE 'Accepted%'") == 2


def test_an_owed_undo_is_retried_on_every_pass_without_a_new_write(env: dict[str, Path]) -> None:  # noqa: F811
    svc, store = service(env)
    ledger = StuckLedger()
    svc._writer._events = ledger
    real = svc._save_checkpoint
    svc._save_checkpoint = _raise_locked  # type: ignore[method-assign]  # test double
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    svc.run_once()
    assert len(svc.held()) == 1
    store.delete("linux_auth")  # no source left to write for: only the pass itself retries
    svc._save_checkpoint = real  # type: ignore[method-assign]
    ledger.fail = False
    svc.run_once()
    assert svc.held() == set() and _parts(env["data"] / "lake") == []


def _raise_locked(*a: object, **kw: object) -> None:
    raise sqlite3.OperationalError("database is locked")


def test_a_take_back_waits_while_the_lake_is_locked(env: dict[str, Path]) -> None:  # noqa: F811
    """Maintenance (the integrity check) or a backup holds the lake lock: the file stays,
    owed, until the next pass, so a check never sees a recorded file vanish under it."""
    svc, store = service(env)
    svc._save_checkpoint = _raise_locked  # type: ignore[method-assign]  # test double
    f = env["logs"] / "auth.log"
    write(f, LINE.format(1, 1))
    store.add(SourceConfig(source_id="linux_auth", format="syslog", path=str(f)))
    lake = env["data"] / "lake"
    lake.mkdir(parents=True, exist_ok=True)
    with lake_lock(lake, wait=False) as held:
        assert held
        svc.run_once()
        assert len(_parts(lake)) == 1 and len(svc.held()) == 1
    svc.run_once()
    assert _parts(lake) == [] and svc.held() == set()


def test_the_server_tells_compaction_which_files_ingest_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "data")})
    app = create_app(config)
    seen: dict[str, object] = {}

    class Recorder:
        def __init__(self, lake: Path, **kw: object) -> None:
            seen.update(kw)

        def run(self) -> None:
            return None

    monkeypatch.setattr(maintenance_module, "Compactor", Recorder)
    app.state.maintenance.compact()
    assert seen["settle_s"] == maintenance_module.SETTLE_S > 5
    assert seen["hold"] == app.state.ingest.held  # the same bound method
