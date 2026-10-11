"""Windows events via NXLog JSON, Winlogbeat JSON, and Snare (tab-delimited in syslog).

Slice 1 only promises generic parsing: raw intact, time and message where present.
EventID to OCSF mapping arrives with templates in Slice 3. All values are synthetic.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.sources import SourceConfig, SourceStore
from app.ingest.watcher import IngestService
from app.meta.db import MetaDB

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

NXLOG = json.dumps(
    {
        "EventTime": "2026-10-09T20:41:01-07:00",
        "Hostname": "WS-0042.corp.example",
        "Keywords": "0x8010000000000000",
        "EventType": "AUDIT_FAILURE",
        "SeverityValue": 4,
        "Severity": "ERROR",
        "EventID": 4625,
        "SourceName": "Microsoft-Windows-Security-Auditing",
        "Channel": "Security",
        "Message": "An account failed to log on.\r\n\r\nSubject:\r\n\tSecurity ID:\t\tS-1-0-0",
        "TargetUserName": "svc_backup",
        "IpAddress": "203.0.113.9",
        "LogonType": "3",
    }
)

WINLOGBEAT = json.dumps(
    {
        "@timestamp": "2026-10-10T03:41:02.123Z",
        "event": {
            "code": "4624",
            "provider": "Microsoft-Windows-Security-Auditing",
            "outcome": "success",
        },
        "winlog": {
            "channel": "Security",
            "computer_name": "DC-01.corp.example",
            "event_id": "4624",
            "event_data": {"TargetUserName": "alice", "IpAddress": "192.0.2.44", "LogonType": "10"},
        },
        "message": "An account was successfully logged on.",
        "host": {"name": "DC-01"},
    }
)

SNARE = (
    "<14>Oct  9 20:41:03 WS-0042 MSWinEventLog\t1\tSecurity\t5126\tFri Oct 09 20:41:03 2026"
    "\t4625\tMicrosoft-Windows-Security-Auditing\tN/A\tN/A\tFailure Audit\tWS-0042.corp.example"
    "\tLogon\t\tAn account failed to log on.  Account Name: oracle  Source Network Address: 203.0.113.77\t1234"
)


@pytest.mark.parametrize(
    ("fmt", "line", "expected_time"),
    [
        ("json", NXLOG, "2026-10-10T03:41:01+00:00"),
        ("json", WINLOGBEAT, "2026-10-10T03:41:02.123000+00:00"),
        ("syslog", SNARE, "2026-10-10T03:41:03+00:00"),
    ],
    ids=["nxlog_json", "winlogbeat_json", "snare_syslog"],
)
def test_windows_events_land_with_raw_intact(
    tmp_path: Path, fmt: str, line: str, expected_time: str
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "win.log").write_text(line + "\n", encoding="utf-8")
    meta = MetaDB(tmp_path / "meta.sqlite")
    store = SourceStore(meta, [logs])
    # Snare's syslog header has no zone; the collector is in Pacific time.
    store.add(
        SourceConfig(
            source_id="windows",
            format=fmt,  # type: ignore[arg-type]  # parametrized literal
            path=str(logs / "win.log"),
            timezone="America/Los_Angeles",
        )
    )
    assert IngestService(store, meta, tmp_path / "lake", clock=lambda: NOW).run_once() == 1

    res = QueryEngine(tmp_path / "lake").run(
        "SELECT raw, time, parse_status FROM events", QueryScope(None)
    )
    raw, time, status = res.rows[0]
    assert raw == line  # byte for byte, tabs and \r\n escapes included
    assert time == expected_time
    assert status != "failed"
