"""Files to Parquet lake to DuckDB, end to end (no watcher yet)."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from app.core.schema import COLUMN_NAMES
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

SYSLOG_FIXTURE = (
    b"<38>Oct  9 20:41:12 bastion sshd[2231]: Accepted publickey for jordan from 10.20.1.5 port 51234 ssh2\n"
    b"<38>Oct  9 20:41:15 bastion sshd[2240]: Failed password for invalid user admin from 203.0.113.9 port 40022 ssh2\r\n"
    b"\n"
    b"<13>1 2026-10-09T23:59:59Z relay01 rsyslogd - - - <38>Oct  9 23:59:58 bastion sshd[9]: relayed\n"
    b"<14>1 2026-10-10T00:00:01Z pa-fw01 PAN-OS - TRAFFIC - 1,2026/10/10 00:00:01,TRAFFIC,deny\n"
    b"garbled \xff\xfe line without a header\n"
    b"<38>Oct 10 01:00:00 bastion sshd[3]: " + b"x" * 300 + b"\n"
)


def ingest(data: bytes, spec: SourceSpec, lake: Path, max_len: int = 256) -> list[Path]:
    normalizer = Normalizer(spec, clock=lambda: NOW)
    rows = []
    for frame in Framer(max_len=max_len).frames([data]):
        out = normalizer.normalize(decode_frame(frame))
        if out is not None:
            rows.append(out)
    return LakeWriter(lake).write(rows)


def query(lake: Path, sql: str) -> list[tuple[object, ...]]:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    glob = str(lake / "**" / "*.parquet").replace("'", "''")  # test-only literal, tmp path
    con.execute(
        f"CREATE VIEW events AS SELECT * FROM read_parquet('{glob}', hive_partitioning = false)"
    )
    return con.execute(sql).fetchall()


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    return tmp_path / "lake"


def test_syslog_file_lands_partitioned_by_source_and_day(lake: Path) -> None:
    files = ingest(SYSLOG_FIXTURE, SourceSpec(source_id="linux_auth", format="syslog"), lake)
    days = sorted({f.parent.name for f in files})
    assert days == ["day=2026-10-09", "day=2026-10-10"]
    assert all(f.parent.parent.name == "source=linux_auth" for f in files)
    assert query(lake, "SELECT count(*) FROM events") == [(6,)]


def test_raw_lines_round_trip_exactly(lake: Path) -> None:
    ingest(SYSLOG_FIXTURE, SourceSpec(source_id="linux_auth", format="syslog"), lake)
    raws = {r[0] for r in query(lake, "SELECT raw FROM events")}
    assert (
        "<38>Oct  9 20:41:15 bastion sshd[2240]: Failed password for invalid user admin "
        "from 203.0.113.9 port 40022 ssh2"
    ) in raws
    assert "garbled �� line without a header" in raws


def test_flags_and_statuses_queryable(lake: Path) -> None:
    ingest(SYSLOG_FIXTURE, SourceSpec(source_id="linux_auth", format="syslog"), lake)
    rows = dict(query(lake, "SELECT parse_status, count(*) FROM events GROUP BY 1 ORDER BY 1"))
    assert rows == {"envelope_only": 5, "partial": 1}
    assert query(lake, "SELECT count(*) FROM events WHERE raw_bytes_invalid") == [(1,)]
    hops = query(
        lake, "SELECT device_hostname FROM events WHERE json_extract(envelope, '$.relay_hops') = 1"
    )
    assert hops == [("bastion",)]


def test_column_order_and_types_follow_schema(lake: Path) -> None:
    ingest(SYSLOG_FIXTURE, SourceSpec(source_id="linux_auth", format="syslog"), lake)
    con = duckdb.connect()
    desc = con.execute(
        "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning = false)",
        [str(lake / "**" / "*.parquet")],
    ).fetchall()
    assert tuple(d[0] for d in desc) == COLUMN_NAMES
    types = {d[0]: d[1] for d in desc}
    assert types["time"] == "TIMESTAMP WITH TIME ZONE"
    assert types["actor_process_pid"] == "BIGINT"
    assert types["raw_bytes_invalid"] == "BOOLEAN"


def test_json_and_csv_sources(lake: Path) -> None:
    ingest(
        b'{"@timestamp":"2026-10-09T20:41:12Z","message":"4625 logon failure","EventID":4625}\nnot json\n',
        SourceSpec(source_id="winlogbeat", format="json"),
        lake,
    )
    ingest(
        b"time,user,action\n2026-10-09T21:00:00Z,jordan,vpn_login\n",
        SourceSpec(source_id="vpn_csv", format="csv"),
        lake,
    )
    got = query(
        lake,
        "SELECT source_id, parse_status, message, json_extract_string(unmapped, '$.user') "
        "FROM events ORDER BY source_id, parse_status",
    )
    assert got == [
        ("vpn_csv", "ok", "user=jordan action=vpn_login", "jordan"),  # summary, no message column
        ("winlogbeat", "failed", None, None),
        ("winlogbeat", "ok", "4625 logon failure", None),
    ]


def test_events_without_time_partition_by_ingest_day(lake: Path) -> None:
    files = ingest(b"no header here\n", SourceSpec(source_id="misc", format="syslog"), lake)
    assert [f.parent.name for f in files] == ["day=2026-10-10"]


def test_empty_batch_writes_nothing(lake: Path) -> None:
    assert LakeWriter(lake).write([]) == []
    assert not lake.exists() or not any(lake.rglob("*.parquet"))


@pytest.mark.parametrize("bad", ["../escape", "Upper", "a/b", "", "x" * 65])
def test_unsafe_source_ids_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        SourceSpec(source_id=bad, format="syslog")
