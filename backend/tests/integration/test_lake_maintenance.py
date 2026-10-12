"""Compaction and retention over the Parquet lake (SPEC 3.3)."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.compaction import MANIFEST_SUFFIX, Compactor
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import DecodedLine
from app.ingest.retention import RetentionJob
from app.ingest.writer import LakeWriter

TODAY = date(2026, 10, 10)


def rows(source_id: str, day: date, n: int, start: int = 0) -> list[dict[str, Any]]:
    clock = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    norm = Normalizer(SourceSpec(source_id=source_id, format="json"), clock=lambda: clock)
    out = []
    for i in range(start, start + n):
        line = json.dumps({"time": f"{day.isoformat()}T10:{i % 60:02d}:00Z", "n": i})
        row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
        assert row is not None
        out.append(row)
    return out


def parts(lake: Path, source_id: str, day: date) -> list[Path]:
    return sorted((lake / f"source={source_id}" / f"day={day.isoformat()}").glob("*.parquet"))


def count(lake: Path, where: str = "TRUE") -> int:
    res = QueryEngine(lake).run(f"SELECT count(*) FROM events WHERE {where}", QueryScope(None))
    return int(res.rows[0][0])


# --- compaction ---------------------------------------------------------------------


def test_small_files_in_closed_day_merge_into_one(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    day = TODAY - timedelta(days=1)
    for i in range(5):
        writer.write(rows("app", day, 10, start=i * 10))
    assert len(parts(lake, "app", day)) == 5

    report = Compactor(lake, today=lambda: TODAY).run()

    assert len(parts(lake, "app", day)) == 1
    assert report.files_merged == 5
    assert report.files_written == 1
    assert count(lake) == 50
    assert count(lake, "json_extract(unmapped, '$.n')::INT = 37") == 1


def test_raw_and_event_ids_preserved(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    day = TODAY - timedelta(days=2)
    batches = [rows("app", day, 3, start=i * 3) for i in range(3)]
    for b in batches:
        writer.write(b)
    before = {(r["event_id"], r["raw"]) for b in batches for r in b}
    Compactor(lake, today=lambda: TODAY).run()
    res = QueryEngine(lake).run("SELECT event_id, raw FROM events", QueryScope(None))
    assert {(str(e), r) for e, r in res.rows} == {(str(e), r) for e, r in before}


def test_single_file_partition_untouched(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    day = TODAY - timedelta(days=1)
    LakeWriter(lake).write(rows("app", day, 5))
    original = parts(lake, "app", day)
    report = Compactor(lake, today=lambda: TODAY).run()
    assert parts(lake, "app", day) == original
    assert report.files_merged == 0


def test_today_waits_for_enough_small_files(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    for i in range(3):
        writer.write(rows("app", TODAY, 2, start=i * 2))
    Compactor(lake, today=lambda: TODAY, min_files_open_day=4).run()
    assert len(parts(lake, "app", TODAY)) == 3
    writer.write(rows("app", TODAY, 2, start=6))
    Compactor(lake, today=lambda: TODAY, min_files_open_day=4).run()
    assert len(parts(lake, "app", TODAY)) == 1
    assert count(lake) == 8


def test_large_files_left_alone(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    day = TODAY - timedelta(days=1)
    for i in range(3):
        writer.write(rows("app", day, 5, start=i * 5))
    # Every file counts as "large" when the threshold is 1 byte.
    Compactor(lake, today=lambda: TODAY, small_bytes=1).run()
    assert len(parts(lake, "app", day)) == 3


def test_output_split_at_target_size(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    day = TODAY - timedelta(days=1)
    for i in range(6):
        writer.write(rows("app", day, 20, start=i * 20))
    one = parts(lake, "app", day)[0].stat().st_size
    Compactor(lake, today=lambda: TODAY, target_bytes=one * 2 + one // 2).run()
    assert len(parts(lake, "app", day)) == 3
    assert count(lake) == 120


def test_interrupted_compaction_recovers_without_duplicates(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    day = TODAY - timedelta(days=1)
    for i in range(3):
        writer.write(rows("app", day, 4, start=i * 4))
    inputs = parts(lake, "app", day)
    # Simulate a crash after the merged file was published but before inputs were removed.
    comp = Compactor(lake, today=lambda: TODAY)
    folder = inputs[0].parent
    output = comp._merge(folder, inputs)  # writes manifest + output, stops before cleanup
    assert output.exists()
    assert list(folder.glob(f"*{MANIFEST_SUFFIX}"))
    assert count(lake) == 24  # duplicated until recovery runs

    comp.run()
    assert count(lake) == 12
    assert not list(folder.glob(f"*{MANIFEST_SUFFIX}"))


def test_manifest_without_output_is_discarded(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    day = TODAY - timedelta(days=1)
    writer.write(rows("app", day, 4))
    folder = parts(lake, "app", day)[0].parent
    (folder / f"part-x{MANIFEST_SUFFIX}").write_text(
        json.dumps(
            {"output": "part-missing.parquet", "inputs": [p.name for p in parts(lake, "app", day)]}
        )
    )
    Compactor(lake, today=lambda: TODAY).run()
    assert count(lake) == 4  # inputs kept because the output never landed


# --- retention ----------------------------------------------------------------------


def test_retention_deletes_old_day_partitions(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    for age in (0, 29, 30, 31, 90):
        writer.write(rows("app", TODAY - timedelta(days=age), 1))
    report = RetentionJob(lake, retention_days={"app": 30}, today=lambda: TODAY).run()
    kept = sorted(p.name for p in (lake / "source=app").iterdir())
    assert kept == [f"day={(TODAY - timedelta(days=a)).isoformat()}" for a in (30, 29, 0)]
    assert report.partitions_deleted == 2


def test_retention_per_source_and_default_for_unknown(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    writer = LakeWriter(lake)
    old = TODAY - timedelta(days=10)
    writer.write(rows("short", old, 1) + rows("long", old, 1) + rows("removed", old, 1))
    RetentionJob(
        lake, retention_days={"short": 7, "long": 365}, default_days=5, today=lambda: TODAY
    ).run()
    assert sorted(p.name for p in lake.iterdir() if not p.name.startswith(".")) == ["source=long"]


def test_retention_ignores_unexpected_names_and_symlinks(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    LakeWriter(lake).write(rows("app", TODAY - timedelta(days=100), 1))
    outside = tmp_path / "outside" / "day=2000-01-01"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("not lake data")
    (lake / "source=app" / "day=2000-01-02").symlink_to(outside, target_is_directory=True)
    (lake / "source=app" / "notes").mkdir()
    (lake / "source=app" / "day=garbage").mkdir()

    RetentionJob(lake, retention_days={"app": 30}, today=lambda: TODAY).run()

    assert (outside / "keep.txt").exists()
    assert (lake / "source=app" / "notes").exists()
    assert (lake / "source=app" / "day=garbage").exists()
    assert not (lake / "source=app" / f"day={(TODAY - timedelta(days=100)).isoformat()}").exists()


def test_retention_on_missing_lake_is_noop(tmp_path: Path) -> None:
    report = RetentionJob(tmp_path / "nope", retention_days={}, today=lambda: TODAY).run()
    assert report.partitions_deleted == 0


# --- scheduling ---------------------------------------------------------------------


def test_maintenance_uses_source_retention_and_schedules(tmp_path: Path) -> None:
    from app.ingest.maintenance import LakeMaintenance
    from app.ingest.sources import SourceConfig, SourceStore
    from app.meta.db import MetaDB

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "a.log").touch()
    store = SourceStore(MetaDB(tmp_path / "meta.sqlite"), [logs])
    store.add(
        SourceConfig(source_id="app", format="json", path=str(logs / "a.log"), retention_days=3650)
    )
    lake = tmp_path / "lake"
    real_today = datetime.now(UTC).date()
    LakeWriter(lake).write(rows("app", real_today - timedelta(days=400), 1))
    LakeWriter(lake).write(rows("gone", real_today - timedelta(days=400), 1))

    clock = [1000.0]
    m = LakeMaintenance(
        lake,
        store,
        orphan_retention_days=30,
        compaction_interval_s=3600,
        retention_interval_s=86400,
        monotonic=lambda: clock[0],
    )
    m.tick()
    assert sorted(p.name for p in lake.iterdir() if not p.name.startswith(".")) == ["source=app"]

    LakeWriter(lake).write(rows("gone", real_today - timedelta(days=400), 1))
    clock[0] += 3600
    m.tick()  # compaction due, retention not yet
    assert (lake / "source=gone").exists()
    clock[0] += 86400
    m.tick()
    assert not (lake / "source=gone").exists()
