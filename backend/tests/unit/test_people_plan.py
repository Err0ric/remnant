"""People and devices reads `unmapped` only from hook rows (owner item 2, 2026-11-08).

A Windows sign-in carries about 1.5 KB of `unmapped`. The page took 18 s on a real week
(1.9M sign-ins, 5.7M DNS queries) because its sign-in queries read that column for every
sign-in: the test-record check in the people split and the hook fields in the signals
pass. The cost grows with every sign-in, so the plan is checked, not a timing: every scan
of the page's queries that reads `unmapped` is limited to hook rows."""

import json
from typing import Any

import duckdb
import pytest

from app.core.schema import duckdb_create_table_sql
from app.search import entity_signals, targeted


def _scans(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node] if "SCAN" in str(node.get("name", "")) else []
    for child in node.get("children", []):
        found += _scans(child)
    return found


def _plan_scans(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    con = duckdb.connect()
    con.execute(duckdb_create_table_sql("events"))
    con.execute("CREATE MACRO is_internal(x) AS false")
    # One failed sign-in, so the optimizer keeps the scans an empty table would fold away.
    con.execute(
        "INSERT INTO events (event_id, source_id, template_id, template_version,"
        " time_observed, class_uid, status_id, actor_user_name, src_endpoint_ip, unmapped,"
        " raw, raw_bytes_invalid, parse_status, classification, owner_id) VALUES ('e1',"
        " 'win', 'windows_nxlog_json', '1', now(), 3002, 2, 'alice', '192.0.2.7', '{}',"
        " 'x', false, 'ok', 'local_only', 'system')"
    )
    row = con.execute(f"EXPLAIN (FORMAT JSON) {sql}", params).fetchone()
    assert row is not None
    return [s for n in json.loads(row[1]) for s in _scans(n)]


@pytest.mark.parametrize(
    ("name", "sql", "params"),
    [
        ("signals", entity_signals.seen_sql("false"), {"org": ["example.com"]}),
        ("evidence", targeted.EVIDENCE_SQL, {}),
        ("attackers", targeted.ATTACKERS_SQL, {"names": ["alice", "root"]}),
    ],
)
def test_unmapped_is_read_from_hook_rows_only(name: str, sql: str, params: dict[str, Any]) -> None:
    scans = _plan_scans(sql, params)
    assert scans, name
    for scan in scans:
        info = scan.get("extra_info", {})
        reads = json.dumps(info.get("Projections", [])) + json.dumps(info.get("Filters", ""))
        if "unmapped" in reads:
            assert "template_id='claude_hooks'" in json.dumps(info.get("Filters", "")), (
                f"{name}: a scan reads unmapped beyond hook rows"
            )
