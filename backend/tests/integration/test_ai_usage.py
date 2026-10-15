"""AI usage page and AI watch end to end (ADR-0015 rows 1, 2, 6 to 9, 13)."""

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import NOW, make_lab

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "fixtures"))
from ai_telemetry import logs_payload, metrics_payload

DNS = [
    ("10.20.1.5", "chatgpt.com"),
    ("10.20.1.5", "chatgpt.com"),
    ("10.20.1.6", "api.openai.com"),
    ("10.20.1.6", "claude.ai"),
    ("10.20.1.7", "chat.deepseek.com."),
    ("10.20.1.7", "www.example.com"),
    ("10.20.1.8", "notchatgpt.com"),
]


def dns_line(i: int, client: str, name: str) -> str:
    return (
        f"<30>Oct 10 11:{i:02d}:00 ns1 named[800]: client 10.0.0.1#53 ({name}): "
        f"query: {name} IN A +E(0)K (10.20.0.53)"
    ).replace("client 10.0.0.1", f"client {client}")


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    a, h = out["admin"], out["h"]
    dns = tmp_path / "logs" / "dns"
    dns.mkdir()
    (dns / "q.log").write_text("\n".join(dns_line(i, c, n) for i, (c, n) in enumerate(DNS)) + "\n")
    body = {"source_id": "dns", "format": "syslog", "path": str(dns), "template_id": "dns_bind"}
    assert a.post("/api/sources", json=body, headers=h).status_code == 201
    res = a.post(
        "/api/sources",
        json={"source_id": "claude", "kind": "otlp", "format": "json", "template_id": "auto"},
        headers=h,
    )
    token = res.json()["otlp_token"]
    base = {"user.email": "alice@example.com", "session.id": "s-1"}
    params = json.dumps({"mcp_server_name": "paste-share", "mcp_tool_name": "upload"})
    t0 = NOW - timedelta(minutes=30)
    logs = logs_payload(
        [
            (
                t0,
                {
                    **base,
                    "event.name": "tool_result",
                    "tool_name": "mcp_tool",
                    "success": "true",
                    "tool_parameters": params,
                },
            ),
            (
                t0,
                {**base, "event.name": "user_prompt", "prompt": "deploy with AKIAABCDEFGHIJKLMNOP"},
            ),
        ],
        "ws-0042",
    )
    metrics = metrics_payload([(t0, "claude_code.cost.usage", "USD", 1.25, {**base, "model": "m"})])
    inventory = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "remnant-mcp-inventory"}}
                    ]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": str(int(t0.timestamp() * 1e9)),
                                "attributes": [
                                    {"key": k, "value": {"stringValue": v}}
                                    for k, v in {
                                        "event.name": "mcp_inventory",
                                        "host": "ws-0042",
                                        "os_user": "alice",
                                        "client": "cursor",
                                        "server": "github",
                                        "transport": "stdio",
                                        "command": "npx",
                                    }.items()
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for path, payload in (("logs", logs), ("metrics", metrics), ("logs", inventory)):
        r = a.post(f"/api/otlp/v1/{path}", content=json.dumps(payload).encode(), headers=hdr)
        assert r.status_code == 200, r.text
    out["app"].state.ingest.run_once()
    return out


def usage(client: Any) -> dict[str, Any]:
    res = client.get("/api/ai/usage")
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def test_services_from_dns_longest_domain_wins(lab: dict[str, Any]) -> None:
    got = {u["service"]["id"]: u for u in usage(lab["admin"])["services"]}
    assert set(got) == {
        "chatgpt",
        "openai_api",
        "claude",
        "deepseek",
    }  # not example.com or notchatgpt.com
    assert got["chatgpt"]["events"] == 2 and got["chatgpt"]["machines"] == 1
    assert got["openai_api"]["service"]["name"] == "OpenAI API"
    assert got["chatgpt"]["service"]["status"] == "unreviewed"


def test_mcp_and_people(lab: dict[str, Any]) -> None:
    body = usage(lab["admin"])
    mcp = {m["name"]: m for m in body["mcp"]}
    assert mcp["paste-share"]["calls"] == 1 and mcp["paste-share"]["sources"] == ["telemetry"]
    assert mcp["github"]["installs"] == 1 and mcp["github"]["clients"] == ["cursor"]
    (alice,) = body["people"]
    assert alice["person"] == "alice@example.com"
    assert alice["cost_usd"] == 1.25 and alice["sensitive"] == 1 and alice["tool_calls"] == 1


def test_review_is_admin_only_audited_and_applied(lab: dict[str, Any]) -> None:
    a, h = lab["admin"], lab["h"]
    assert (
        lab["ana"].put("/api/ai/services/chatgpt/status", json={"status": "approved"}).status_code
        == 403
    )
    res = a.put("/api/ai/services/chatgpt/status", json={"status": "not_approved"}, headers=h)
    assert res.status_code == 200 and res.json()["status"] == "not_approved"
    rules = a.put(
        "/api/ai/mcp-rules", json={"pattern": "git*", "status": "approved"}, headers=h
    ).json()
    assert rules[0]["pattern"] == "git*"
    body = usage(a)
    assert {u["service"]["id"]: u["service"]["status"] for u in body["services"]}[
        "chatgpt"
    ] == "not_approved"
    assert {m["name"]: m["status"] for m in body["mcp"]} == {
        "github": "approved",
        "paste-share": "unreviewed",
    }
    added = a.post(
        "/api/ai/services",
        json={
            "id": "internal_llm",
            "name": "Internal LLM",
            "kind": "chat",
            "domains": ["example.com"],
        },
        headers=h,
    )
    assert added.status_code == 201 and added.json()["custom"] is True
    assert "internal_llm" in {u["service"]["id"] for u in usage(a)["services"]}
    bad = a.post(
        "/api/ai/services",
        json={"id": "x1", "name": "X", "kind": "chat", "domains": ["a' OR 1=1 --"]},
        headers=h,
    )
    assert bad.status_code == 422
    with lab["app"].state.meta.connect() as con:
        actions = [
            r[0]
            for r in con.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'ai.%' ORDER BY audit_id"
            )
        ]
    assert (
        actions.count("ai.service_change") == 2
        and "ai.mcp_change" in actions
        and "ai.view" in actions
    )


def test_scope_follows_source_groups(lab: dict[str, Any]) -> None:
    body = usage(lab["ana"])  # ana reads only the Linux group
    assert body["services"] == [] and body["mcp"] == [] and body["people"] == []


def test_watch_alerts_once_per_first_sighting_and_on_sensitive_data(lab: dict[str, Any]) -> None:
    app, a, h = lab["app"], lab["admin"], lab["h"]
    app.state.ai_watch._clock = lambda: NOW - timedelta(days=1)  # cursor before the data
    res = a.put("/api/ai/watch", json={"enabled": True, "include_unreviewed": True}, headers=h)
    assert res.status_code == 200 and res.json()["enabled"] is True
    assert app.state.ai_watch.tick() == 2  # new AI use, and sensitive data
    assert app.state.ai_watch.tick() == 0  # nothing new
    with app.state.meta.connect() as con:
        rows = {
            r[0]: json.loads(r[1])
            for r in con.execute(
                "SELECT action, detail FROM audit_log WHERE action IN ('ai.sighting', 'ai.sensitive')"
            )
        }
    items = " ".join(rows["ai.sighting"]["items"])
    assert "ChatGPT by 10.20.1.5" in items and "MCP paste-share by alice@example.com" in items
    assert rows["ai.sensitive"]["items"] == ["alice@example.com: aws_access_key x1"]
    assert "AKIA" not in json.dumps(rows)
    assert lab["ana"].get("/api/ai/watch").status_code == 403
