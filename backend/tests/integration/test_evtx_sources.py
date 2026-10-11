"""Native .evtx ingestion end to end: file -> evtx reader -> template -> lake (SPEC 4.4, D4)."""

import io
import os
import shutil
import struct
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.ingest.evtx import EvtxReader
from app.main import create_app

FIXTURES = Path(__file__).parent.parent / "fixtures" / "logs" / "windows_evtx"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs" / "dc01"
    logs.mkdir(parents=True)
    shutil.copy(FIXTURES / "sample.evtx", logs / "Security.evtx")
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(tmp_path / "logs"),
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    client = TestClient(app)
    body = {
        "source_id": "dc01_evtx",
        "format": "json",
        "path": str(logs),
        "glob": "*.evtx",
        "template_id": "windows_evtx",
    }
    assert client.post("/api/sources", json=body).status_code == 201
    return {"app": app, "c": client, "logs": logs}


def query(lab: dict[str, Any], sql: str) -> list[list[Any]]:
    res = lab["c"].post("/api/query", json={"sql": sql})
    assert res.status_code == 200, res.text
    rows: list[list[Any]] = res.json()["rows"]
    return rows


def test_evtx_file_lands_with_raw_record_json(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    assert ingest.run_once() == 60
    expected = (FIXTURES / "sample.log").read_text("utf-8").splitlines()
    raws = [r[0] for r in query(lab, "SELECT raw FROM events ORDER BY time")]
    assert raws == expected  # raw is exactly the record JSON the reader framed
    classes = dict(
        (c, n) for c, n in query(lab, "SELECT class_uid, count(*) FROM events GROUP BY 1")
    )
    assert set(classes) <= {0, 1007, 3001, 3002, 3006, 4001} and sum(classes.values()) == 60
    (ok,) = query(lab, "SELECT count(*) FROM events WHERE parse_status = 'ok'")[0]
    assert ok == 60
    # Unchanged file: skipped by its signature, nothing written twice.
    assert ingest.run_once() == 0
    assert query(lab, "SELECT count(*) FROM events") == [[60]]


def test_new_records_are_read_after_the_checkpoint(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    ingest._evtx = EvtxReader(max_records=25, max_len=65_536)
    assert [ingest.run_once() for _ in range(4)] == [25, 25, 10, 0]
    ids = query(
        lab,
        "SELECT count(DISTINCT json_extract(raw, '$.Event.System.EventRecordID')) FROM events",
    )
    assert ids == [[60]]


def _swap(path: Path, data: bytes) -> None:
    """Replace a file the way rsync and robocopy do: write elsewhere, rename over it."""
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _recrc(data: bytes) -> bytes:
    """Recompute chunk checksums after editing records, as Windows would have written them."""
    out = bytearray(data)
    for start in range(4096, len(out), 65_536):
        if out[start : start + 8] != b"ElfChnk\x00":
            continue
        (free,) = struct.unpack_from("<I", out, start + 48)
        struct.pack_into("<I", out, start + 52, zlib.crc32(out[start + 512 : start + free]))
        head = bytes(out[start : start + 120]) + bytes(out[start + 128 : start + 512])
        struct.pack_into("<I", out, start + 124, zlib.crc32(head))
    return bytes(out)


def test_same_log_copied_again_is_not_ingested_twice(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    assert ingest.run_once() == 60
    target = lab["logs"] / "Security.evtx"
    _swap(target, (FIXTURES / "sample.evtx").read_bytes())  # new inode, new mtime
    assert ingest.run_once() == 0
    # The damaged copy is still the same log (record 60 unchanged): nothing new to read.
    _swap(target, (FIXTURES / "pathological.evtx").read_bytes())
    assert ingest.run_once() == 0
    assert query(lab, "SELECT count(*) FROM events") == [[60]]


def test_a_different_log_with_the_same_ids_is_read_from_the_start(
    lab: dict[str, Any],
) -> None:
    ingest = lab["app"].state.ingest
    assert ingest.run_once() == 60
    target = lab["logs"] / "Security.evtx"
    other = (FIXTURES / "sample.evtx").read_bytes()
    # Every record names its computer, so a log from another domain differs in all of them.
    old, new = ("corp.example".encode("utf-16-le"), "labs.example".encode("utf-16-le"))
    assert other.count(old) >= 60
    with target.open("r+b") as fh:  # in place: same inode, as `cp` over a file does
        fh.write(_recrc(other.replace(old, new)))
    assert ingest.run_once() == 60
    assert query(lab, "SELECT count(*) FROM events WHERE raw LIKE '%labs.example%'") == [[60]]


def test_damaged_records_are_skipped_and_the_rest_land(lab: dict[str, Any]) -> None:
    (lab["logs"] / "Security.evtx").unlink()
    shutil.copy(FIXTURES / "pathological.evtx", lab["logs"] / "Old.evtx")
    damaged = EvtxReader().read(io.BytesIO((FIXTURES / "pathological.evtx").read_bytes()), 0)
    assert 0 < len(damaged.frames) < 60
    assert lab["app"].state.ingest.run_once() == len(damaged.frames)
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["state"] != "error"
    assert damaged.unreadable == 1
    assert src["status"]["records_skipped"] == 1
    # Later passes skip the finished file unparsed; the count stays, it does not grow.
    lab["app"].state.ingest.run_once()
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["records_skipped"] == 1


def test_garbage_named_evtx_is_not_fatal(lab: dict[str, Any]) -> None:
    (lab["logs"] / "notes.evtx").write_bytes(b"this is not an event log\n" * 100)
    assert lab["app"].state.ingest.run_once() == 60


def _writer() -> Any:
    import sys

    sys.path.insert(0, str(Path(__file__).parents[3] / "scripts" / "fixtures"))
    import evtx_writer

    return evtx_writer


def _log(count: int) -> bytes:
    w = _writer()
    records = []
    for i in range(1, count + 1):
        t = datetime(2026, 10, 9, 20, 0, i, tzinfo=UTC)
        records.append(
            (
                i,
                t,
                w.event(
                    provider="Microsoft-Windows-Security-Auditing",
                    provider_guid=None,
                    event_id=4624,
                    qualifiers=None,
                    level=0,
                    task=12544,
                    keywords=0x8020000000000000,
                    created=t,
                    record_id=i,
                    channel="Security",
                    computer="DC01.corp.example",
                    data={"SubjectUserName": "DC01$", "TargetUserName": "bob"},
                ),
            )
        )
    data: bytes = w.write_evtx(records)
    return data


def test_grown_log_with_the_same_size_and_mtime_is_read(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    target = lab["logs"] / "Security.evtx"
    first, grown = _log(30), _log(45)
    assert len(first) == len(grown)  # a full log does not change size
    target.write_bytes(first)
    os.utime(target, ns=(10**18, 10**18))
    assert ingest.run_once() == 30
    _swap(target, grown)
    os.utime(target, ns=(10**18, 10**18))  # copy tools keep the source mtime
    assert ingest.run_once() == 15


def test_copy_in_progress_is_left_for_later(lab: dict[str, Any]) -> None:
    ingest = lab["app"].state.ingest
    assert ingest.run_once() == 60
    target = lab["logs"] / "Security.evtx"
    whole = target.read_bytes()
    with target.open("r+b") as fh:  # in place, partway through
        fh.truncate(4096 + 65_536)
    assert ingest.run_once() == 0
    target.write_bytes(whole)
    assert ingest.run_once() == 0
    assert query(lab, "SELECT count(*) FROM events") == [[60]]


def test_a_truncated_copy_is_shown_waiting_then_read_once_it_stops_changing(
    lab: dict[str, Any],
) -> None:
    from datetime import timedelta

    from app.ingest.watcher import SHORT_EVTX_GRACE

    ingest = lab["app"].state.ingest
    target = lab["logs"] / "Security.evtx"
    with target.open("r+b") as fh:  # a transfer that stopped after the first chunk
        fh.truncate(4096 + 65_536)
    assert ingest.run_once() == 0
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["files_waiting"] == 1 and src["status"]["state"] != "error"
    now = NOW
    ingest._clock = lambda: now + SHORT_EVTX_GRACE - timedelta(seconds=1)
    assert ingest.run_once() == 0  # same size, but not long enough yet
    ingest._clock = lambda: now + SHORT_EVTX_GRACE
    assert ingest.run_once() == 37  # the records it has, once it has stopped changing
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["files_waiting"] == 0
    assert ingest.run_once() == 0  # not read again


def test_a_lagging_chunk_holds_the_checkpoint_until_its_records_appear(
    lab: dict[str, Any],
) -> None:
    """A copy taken mid-write: the first chunk's header lists ids 1 to 30 but holds 1 to 37.
    Moving the checkpoint to 60 would lose 31 to 37 for good."""
    import struct

    ingest = lab["app"].state.ingest
    target = lab["logs"] / "Security.evtx"
    whole = target.read_bytes()
    lagging = bytearray(whole)
    struct.pack_into("<Q", lagging, 4096 + 32, 30)
    target.write_bytes(bytes(lagging))
    assert ingest.run_once() == 30  # up to the gap, and no further
    target.write_bytes(whole)  # the next copy has the header written
    assert ingest.run_once() == 30  # 31 to 60, nothing twice
    assert query(lab, "SELECT count(DISTINCT raw), count(*) FROM events") == [[60, 60]]


def test_a_gap_that_never_fills_is_passed_after_the_grace_and_counted(
    lab: dict[str, Any],
) -> None:
    import struct

    from app.ingest.watcher import SHORT_EVTX_GRACE

    ingest = lab["app"].state.ingest
    target = lab["logs"] / "Security.evtx"
    lagging = bytearray(target.read_bytes())
    struct.pack_into("<Q", lagging, 4096 + 32, 30)
    target.write_bytes(bytes(lagging))
    assert ingest.run_once() == 30
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["files_waiting"] == 1
    ingest._clock = lambda: NOW + SHORT_EVTX_GRACE
    assert ingest.run_once() == 23  # 38 to 60
    (src,) = lab["c"].get("/api/sources").json()
    assert src["status"]["records_skipped"] == 7 and src["status"]["files_waiting"] == 0
    assert ingest.run_once() == 0
