"""OTLP receiver end to end (ADR-0015 rows 3 to 5): token, content dropping, spool, ingest."""

import gzip
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import make_lab

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "fixtures"))
from ai_telemetry import logs_payload, metrics_payload

T0 = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
BASE = {"user.email": "alice@example.com", "session.id": "s-1", "organization.id": "org-1"}
PROMPT = "summarise the incident notes for INC-4471"


def payload() -> dict[str, Any]:
    params = json.dumps(
        {"mcp_server_name": "github", "mcp_tool_name": "search_issues", "arguments": {"q": "x"}}
    )
    return logs_payload(
        [
            (
                T0,
                {
                    **BASE,
                    "event.name": "user_prompt",
                    "prompt_length": len(PROMPT),
                    "prompt": PROMPT,
                },
            ),
            (
                T0 + timedelta(seconds=2),
                {
                    **BASE,
                    "event.name": "tool_result",
                    "tool_name": "mcp_tool",
                    "success": "true",
                    "tool_parameters": params,
                    "tool_input": '{"q":"secret-ish"}',
                },
            ),
        ],
        "ws-0042",
    )


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    res = out["admin"].post(
        "/api/sources",
        json={"source_id": "claude", "kind": "otlp", "format": "json", "template_id": "auto"},
        headers=out["h"],
    )
    assert res.status_code == 201, res.text
    out["token"] = res.json()["otlp_token"]
    out["spool"] = tmp_path / "data" / "spool" / "claude"
    return out


def send(
    lab: dict[str, Any], body: Any, token: str | None = None, path: str = "logs", **kw: Any
) -> Any:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token or lab['token']}",
    }
    headers |= kw.pop("headers", {})
    data = kw.pop("content", None) or json.dumps(body).encode()
    return lab["admin"].post(f"/api/otlp/v1/{path}", content=data, headers=headers)


def spooled(lab: dict[str, Any]) -> str:
    return "".join(p.read_text() for p in sorted(lab["spool"].glob("*.jsonl")))


def events(lab: dict[str, Any]) -> list[list[Any]]:
    lab["app"].state.ingest.run_once()
    res = lab["admin"].post(
        "/api/query",
        json={
            "sql": "SELECT message, actor_user_name, device_hostname, status_id, template_id, raw"
            " FROM events WHERE source_id = 'claude' ORDER BY time"
        },
        headers=lab["h"],
    )
    rows: list[list[Any]] = res.json()["rows"]
    return rows


def test_token_once_then_records_land_parsed_with_content_dropped(lab: dict[str, Any]) -> None:
    assert lab["token"].startswith("rmt_")
    res = send(lab, payload())
    assert res.status_code == 200 and res.json() == {}
    text = spooled(lab)
    assert PROMPT not in text and "secret-ish" not in text and "arguments" not in text
    assert '"mcp_server_name":"github"' in text and '"prompt_length":' in text
    rows = events(lab)
    assert [r[0] for r in rows] == ["claude_code.user_prompt", "claude_code.tool_result"]
    assert rows[1][1:5] == ["alice@example.com", "ws-0042", 1, "claude_code_otel"]
    # The token is never in the lake, the audit log, or the source list.
    with lab["app"].state.meta.connect() as con:
        audit = " ".join(r[0] for r in con.execute("SELECT detail FROM audit_log"))
    assert lab["token"] not in audit
    assert lab["token"] not in json.dumps(lab["admin"].get("/api/sources").json())


def test_metrics_and_gzip(lab: dict[str, Any]) -> None:
    body = metrics_payload(
        [
            (
                T0,
                "claude_code.cost.usage",
                "USD",
                0.25,
                {"user.email": "bob@example.com", "model": "m"},
            )
        ]
    )
    res = send(
        lab, None, path="metrics",
        content=gzip.compress(json.dumps(body).encode()), headers={"Content-Encoding": "gzip"},
    )  # fmt: skip
    assert res.status_code == 200, res.text
    rows = events(lab)
    assert [(r[0], r[1]) for r in rows] == [("claude_code.cost.usage", "bob@example.com")]
    assert json.loads(rows[0][5])["value"] == 0.25


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"Authorization": "Bearer rmt_wrong"}, 401),
        ({"Authorization": ""}, 401),
        ({"Content-Type": "application/x-protobuf"}, 415),
        ({"Content-Type": "text/plain"}, 415),
    ],
)
def test_refusals(lab: dict[str, Any], headers: dict[str, str], code: int) -> None:
    assert send(lab, payload(), headers=headers).status_code == code
    assert spooled(lab) == ""


def test_size_and_bombs(lab: dict[str, Any]) -> None:
    big = b'{"resourceLogs":[' + b" " * (5 * 1024 * 1024) + b"]}"
    assert send(lab, None, content=big).status_code == 413
    bomb = gzip.compress(b'{"resourceLogs":[' + b" " * (20 * 1024 * 1024) + b"]}")
    assert send(lab, None, content=bomb, headers={"Content-Encoding": "gzip"}).status_code == 400
    assert send(lab, None, content=b"not json").status_code == 400


def test_rotate_keep_content_and_admin_only(lab: dict[str, Any]) -> None:
    assert lab["ana"].post("/api/sources/claude/otlp-token").status_code == 403
    new = lab["admin"].post("/api/sources/claude/otlp-token", headers=lab["h"]).json()["token"]
    assert send(lab, payload()).status_code == 401  # the old token stopped working
    res = lab["admin"].patch(
        "/api/sources/claude", json={"otlp_keep_content": True}, headers=lab["h"]
    )
    assert res.status_code == 200 and res.json()["otlp_keep_content"] is True
    assert send(lab, payload(), token=new).status_code == 200
    assert PROMPT in spooled(lab)
    with lab["app"].state.meta.connect() as con:
        actions = [
            r[0]
            for r in con.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'source.otlp%' ORDER BY audit_id"
            )
        ]
    assert actions == ["source.otlp_token", "source.otlp_content"]
    other = lab["admin"].patch(
        "/api/sources/lin_auth", json={"otlp_keep_content": True}, headers=lab["h"]
    )
    assert other.status_code == 400


def test_read_spool_files_are_pruned_and_delete_removes_the_rest(lab: dict[str, Any]) -> None:
    send(lab, payload())
    (old,) = list(lab["spool"].glob("*.jsonl"))
    lab["app"].state.ingest._clock = lambda: datetime.now(UTC) + timedelta(hours=2)
    lab["app"].state.ingest.run_once()  # reads it
    lab["app"].state.ingest.run_once()  # an older hour, fully read: removed
    assert not old.exists()
    send(lab, payload())
    assert list(lab["spool"].glob("*.jsonl"))
    assert lab["admin"].delete("/api/sources/claude", headers=lab["h"]).status_code == 204
    assert not lab["spool"].exists()
    assert send(lab, payload()).status_code == 401


def _agent_logs(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [{"key": "host.name", "value": {"stringValue": "ws-0042"}}]
                },
                "scopeLogs": [{"logRecords": records}],
            }
        ]
    }


WIN_XML = (
    '<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System>'
    '<Provider Name="Microsoft-Windows-Security-Auditing" Guid="{54849625-5478-4994-a5ba-3e3b0328c30d}"/>'
    "<EventID>4625</EventID><Version>0</Version><Level>0</Level><Task>12544</Task><Opcode>0</Opcode>"
    "<Keywords>0x8010000000000000</Keywords>"
    '<TimeCreated SystemTime="2026-10-14T17:00:00.1234567Z"/><EventRecordID>99</EventRecordID>'
    "<Channel>Security</Channel><Computer>DC01.corp.example</Computer></System><EventData>"
    '<Data Name="SubjectUserName">-</Data><Data Name="TargetUserName">bob</Data>'
    '<Data Name="LogonType">3</Data><Data Name="IpAddress">203.0.113.9</Data>'
    '<Data Name="IpPort">51234</Data></EventData></Event>'
)


def test_agent_records_reuse_the_windows_and_linux_templates(lab: dict[str, Any]) -> None:
    ns = str(int(T0.timestamp() * 1e9))
    body = _agent_logs(
        [
            {"timeUnixNano": ns, "body": {"stringValue": WIN_XML}},
            {
                "timeUnixNano": ns,
                "body": {
                    "kvlistValue": {
                        "values": [
                            {
                                "key": "MESSAGE",
                                "value": {
                                    "stringValue": "Failed password for invalid user oracle from 198.51.100.7 port 40022 ssh2"
                                },
                            },
                            {"key": "_HOSTNAME", "value": {"stringValue": "bastion"}},
                            {"key": "SYSLOG_IDENTIFIER", "value": {"stringValue": "sshd"}},
                            {"key": "_PID", "value": {"stringValue": "812"}},
                            {"key": "PRIORITY", "value": {"stringValue": "6"}},
                            {"key": "SYSLOG_FACILITY", "value": {"stringValue": "10"}},
                            {
                                "key": "__REALTIME_TIMESTAMP",
                                "value": {"stringValue": "1760461200000000"},
                            },
                        ]
                    }
                },
            },
            {
                "timeUnixNano": ns,
                "attributes": [{"key": "log.file.name", "value": {"stringValue": "auth.log"}}],
                "body": {
                    "stringValue": "Oct 14 17:00:01 web-01 sshd[99]: Accepted publickey for deploy from 10.20.1.5 port 50000 ssh2\n"
                },
            },
        ]
    )
    assert send(lab, body).status_code == 200
    text = spooled(lab).splitlines()
    assert text[0].startswith('{"Event":{"System":{"Provider"')
    assert text[1].startswith(
        "<86>1 2025-10-14T17:00:00+00:00 bastion sshd 812 - - Failed password"
    )
    assert (
        text[2]
        == "Oct 14 17:00:01 web-01 sshd[99]: Accepted publickey for deploy from 10.20.1.5 port 50000 ssh2"
    )
    rows = {r[4]: r for r in events(lab)}
    assert set(rows) == {"windows_evtx", "linux_sshd"}
    win = rows["windows_evtx"]
    assert (win[1], win[2], win[3]) == ("bob", "DC01.corp.example", 2)


def test_sensitive_signals_without_the_text(lab: dict[str, Any]) -> None:
    key = "AKIA" + "ABCDEFGHIJKLMNOP"
    body = logs_payload(
        [(T0, {**BASE, "event.name": "user_prompt", "prompt": f"use {key} and 123-45-6789"})],
        "ws-0042",
    )
    assert send(lab, body).status_code == 200
    text = spooled(lab)
    assert key not in text and "123-45-6789" not in text
    rec = json.loads(text.splitlines()[0])
    assert rec["attr"]["sensitive"] == {"aws_access_key": 1, "us_ssn": 1}
    assert rec["attr"]["sensitive_total"] == 2


@pytest.mark.parametrize("target", ["windows", "linux"])
def test_agent_config_has_no_secret_and_parses(lab: dict[str, Any], target: str) -> None:
    import yaml

    res = lab["admin"].get(f"/api/sources/claude/agent-config?os={target}")
    assert res.status_code == 200, res.text
    assert lab["token"] not in res.text
    doc = yaml.safe_load(res.text)
    exporter = doc["exporters"]["otlphttp/remnant"]
    assert exporter["endpoint"] == "https://siem.example.internal:8080/api/otlp"
    assert exporter["encoding"] == "json" and exporter["headers"]["Authorization"].startswith(
        "Bearer ${file:"
    )
    receivers = doc["service"]["pipelines"]["logs"]["receivers"]
    if target == "windows":
        assert len(receivers) == 6
        assert all(doc["receivers"][r]["raw"] is True for r in receivers)
    else:
        assert receivers == ["journald"]
    assert lab["ana"].get("/api/sources/claude/agent-config").status_code == 403
    assert lab["admin"].get("/api/sources/lin_auth/agent-config").status_code == 400
    # Offline laptops keep their events: a disk queue that is retried without a deadline.
    assert exporter["sending_queue"]["storage"] == "file_storage"
    assert exporter["retry_on_failure"]["max_elapsed_time"] == 0
    assert "server_name_override" not in exporter["tls"]
    if target == "windows":
        assert all(doc["receivers"][r]["storage"] == "file_storage" for r in receivers)


def test_agent_config_can_name_the_server_for_its_certificate(lab: dict[str, Any]) -> None:
    import yaml

    url = "/api/sources/claude/agent-config?os=windows&server_name=siem.example.internal"
    doc = yaml.safe_load(lab["admin"].get(url).text)
    tls = doc["exporters"]["otlphttp/remnant"]["tls"]
    assert tls["server_name_override"] == "siem.example.internal"
    bad = "/api/sources/claude/agent-config?server_name=" + "a%22%0Ab: c"
    assert lab["admin"].get(bad).status_code == 422


def test_sensitive_signals_are_searchable(lab: dict[str, Any]) -> None:
    body = logs_payload(
        [
            (T0, {**BASE, "event.name": "user_prompt", "prompt": "key AKIAABCDEFGHIJKLMNOP"}),
            (T0, {**BASE, "event.name": "user_prompt", "prompt": "nothing to see"}),
        ],
        "ws-0042",
    )
    assert send(lab, body).status_code == 200
    lab["app"].state.ingest.run_once()
    c = (
        lab["admin"]
        .post(
            "/api/search/compile",
            json={"text": "source:claude attr.sensitive_total:>0"},
            headers=lab["h"],
        )
        .json()
    )
    res = (
        lab["admin"]
        .post("/api/query", json={"sql": c["sql"], "params": c["params"]}, headers=lab["h"])
        .json()
    )
    assert res["row_count"] == 1


def test_refusals_become_events_and_the_built_in_detection_raises_one_item(
    lab: dict[str, Any],
) -> None:
    """ADR-0040: refused ingest tokens, sign-ins, and API tokens land in server_events; ten
    from one address in ten minutes raise one item, on by default; never the token."""
    for _ in range(8):
        assert send(lab, {"resourceLogs": []}, token="rmt_guessing-a-token").status_code == 401
    bad = lab["admin"].get("/api/users", headers={"Authorization": "Bearer cli_not-a-token"})
    assert bad.status_code == 401
    anon = lab["ana"].__class__(lab["app"], base_url=str(lab["admin"].base_url))
    for _ in range(2):
        anon.post("/api/auth/login", json={"username": "admin", "password": "wrong-password-1"})
    lab["app"].state.ingest.run_once()
    rows = (
        lab["admin"]
        .post(
            "/api/query",
            json={
                "sql": "SELECT message, actor_user_name, status_id, raw FROM events"
                " WHERE source_id = 'server_events' ORDER BY time"
            },
            headers=lab["h"],
        )
        .json()["rows"]
    )
    kinds = [r[0] for r in rows]
    assert kinds.count("server.refused.otlp_token") == 8
    assert "server.refused.api_token" in kinds and "server.refused.sign_in" in kinds
    assert all(r[2] == 2 for r in rows)
    assert not any("rmt_guessing-a-token" in r[3] or "wrong-password" in r[3] for r in rows)
    assert any('"token_prefix":"rmt_gues"' in r[3] for r in rows)
    watch = lab["app"].state.refusal_watch
    assert watch.tick() >= 1
    items = lab["admin"].get("/api/alerts", params={"state": "open"}).json()["items"]
    mine = [i for i in items if i["subject"].startswith("refusals:")]
    assert len(mine) == 1 and mine[0]["severity"] == "high" and mine[0]["count"] >= 10
    assert lab["admin"].get("/api/rules/builtin/refusals").json()["enabled"] is True
    off = lab["admin"].put(
        "/api/rules/builtin/refusals", json={"enabled": False, "threshold": 10}, headers=lab["h"]
    )
    assert off.status_code == 200 and off.json()["enabled"] is False
