#!/usr/bin/env python3
"""Fixtures for the AI usage templates (ADR-0015): claude_code_otel and mcp_inventory.

Claude Code lines are made the way the server makes them: OTLP JSON payloads shaped like
Claude Code's (documented event and metric names and attributes) are run through the
receiver's own conversion, so the fixtures are exactly what lands in a spool file.

    cd backend && uv run python ../scripts/fixtures/ai_telemetry.py

Synthetic only: example.com addresses, invented hosts, RFC 5737 networks.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.ingest.otlp import log_records, metric_records  # noqa: E402

FIX = ROOT / "backend" / "tests" / "fixtures" / "logs"
START = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
USERS = [("alice@example.com", "ws-0042"), ("bob@example.com", "lt-0107"), ("carol@example.com", "ws-0311")]
MCP = [("github", "search_issues"), ("filesystem", "read_file"), ("jira", "get_issue"), ("paste-share", "upload")]
BUILTIN = ["Bash", "Edit", "Read", "Grep", "WebFetch"]
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


def s(v: object) -> dict[str, object]:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def attrs(d: dict[str, object]) -> list[dict[str, object]]:
    return [{"key": k, "value": s(v)} for k, v in d.items() if v is not None]


def nanos(t: datetime) -> str:
    return str(int(t.timestamp() * 1e9))


def logs_payload(records: list[tuple[datetime, dict[str, object]]], host: str) -> dict[str, object]:
    resource = attrs({"service.name": "claude-code", "service.version": "2.1.0", "host.name": host})
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": resource},
                "scopeLogs": [
                    {
                        "scope": {"name": "com.anthropic.claude_code.events", "version": "2.1.0"},
                        "logRecords": [
                            {
                                "timeUnixNano": nanos(t),
                                "body": {"stringValue": f"claude_code.{a['event.name']}"},
                                "attributes": attrs(a),
                            }
                            for t, a in records
                        ],
                    }
                ],
            }
        ]
    }


def metrics_payload(points: list[tuple[datetime, str, str, float, dict[str, object]]]) -> dict[str, object]:
    resource = attrs({"service.name": "claude-code", "service.version": "2.1.0"})
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": resource},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": name,
                                "unit": unit,
                                "sum": {
                                    "aggregationTemporality": 1,
                                    "isMonotonic": True,
                                    "dataPoints": [
                                        {"timeUnixNano": nanos(t), "asDouble": value, "attributes": attrs(a)}
                                    ],
                                },
                            }
                            for t, name, unit, value, a in points
                        ]
                    }
                ],
            }
        ]
    }


def claude_code(rng: random.Random) -> tuple[list[str], list[dict[str, object]]]:
    out: list[str] = []
    expected: list[dict[str, object]] = []
    t = START
    for n in range(14):
        email, host = USERS[n % len(USERS)]
        base = {"user.email": email, "user.account_uuid": f"acct-{n % 3:04d}", "organization.id": "org-0001", "session.id": f"sess-{n:03d}", "terminal.type": rng.choice(["vscode", "iTerm.app", "WindowsTerminal"])}
        recs: list[tuple[datetime, dict[str, object]]] = []
        t += timedelta(minutes=rng.randint(1, 9))
        recs.append((t, {**base, "event.name": "user_prompt", "prompt_length": rng.randint(20, 900), "prompt": "list the open tickets assigned to me"}))
        model = rng.choice(MODELS)
        t += timedelta(seconds=3)
        recs.append((t, {**base, "event.name": "api_request", "model": model, "cost_usd": round(rng.uniform(0.001, 0.2), 4), "duration_ms": rng.randint(800, 9000), "input_tokens": rng.randint(500, 40000), "output_tokens": rng.randint(50, 4000), "cache_read_tokens": rng.randint(0, 30000), "cache_creation_tokens": 0}))
        server, tool = MCP[n % len(MCP)] if n % 2 == 0 else (None, rng.choice(BUILTIN))
        t += timedelta(seconds=2)
        if server:
            params = json.dumps({"mcp_server_name": server, "mcp_tool_name": tool, "arguments": {"query": "assignee = me"}})
            recs.append((t, {**base, "event.name": "tool_decision", "tool_name": "mcp_tool", "decision": "accept", "source": "config", "tool_source": "mcp", "tool_parameters": params}))
            ok = server != "paste-share"
            recs.append((t + timedelta(seconds=1), {**base, "event.name": "tool_result", "tool_name": "mcp_tool", "success": "true" if ok else "false", "duration_ms": rng.randint(50, 3000), "tool_parameters": params, "tool_input": '{"query":"assignee = me"}', "mcp_server_scope": "user"}))
        else:
            recs.append((t, {**base, "event.name": "tool_decision", "tool_name": tool, "decision": rng.choice(["accept", "accept", "reject"]), "source": "user_temporary", "tool_source": "builtin"}))
            recs.append((t + timedelta(seconds=1), {**base, "event.name": "tool_result", "tool_name": tool, "success": "true", "duration_ms": rng.randint(5, 900)}))
        if n % 5 == 4:
            recs.append((t + timedelta(seconds=2), {**base, "event.name": "api_error", "model": model, "error": "Overloaded", "status_code": 529, "attempt": 2, "duration_ms": 1200}))
        for rec in log_records(logs_payload(recs, host), keep_content=False):
            out.append(json.dumps(rec, separators=(",", ":"), ensure_ascii=False))
            a = rec["attr"]
            status = {"true": 1, "false": 2}.get(str(a.get("success")))
            status = {"accept": 1, "reject": 2}.get(str(a.get("decision")), status)
            if rec["event"] == "claude_code.api_error":
                status = 2
            row: dict[str, object] = {"parse_status": "ok", "class_uid": 6003, "message": rec["event"], "actor_user_name": a["user_email"], "device_hostname": host, "time": rec["time"]}
            if status is not None:
                row["status_id"] = status
            expected.append(row)
        points = [
            (t, "claude_code.cost.usage", "USD", round(rng.uniform(0.01, 0.5), 4), {"user.email": email, "model": model, "session.id": base["session.id"]}),
            (t, "claude_code.token.usage", "tokens", float(rng.randint(1000, 60000)), {"user.email": email, "model": model, "type": "input"}),
        ]
        for rec in metric_records(metrics_payload(points)):
            out.append(json.dumps(rec, separators=(",", ":"), ensure_ascii=False))
            expected.append({"parse_status": "ok", "class_uid": 6003, "message": rec["metric"], "actor_user_name": email})
    return out, expected


def inventory(rng: random.Random) -> tuple[list[str], list[dict[str, object]]]:
    clients = {
        "claude_desktop": "C:/Users/{u}/AppData/Roaming/Claude/claude_desktop_config.json",
        "claude_code": "/home/{u}/.claude.json",
        "cursor": "/home/{u}/.cursor/mcp.json",
        "vscode": "/home/{u}/.config/Code/User/mcp.json",
    }
    servers = [
        ("github", "stdio", "npx", None),
        ("filesystem", "stdio", "npx", None),
        ("jira", "http", None, "mcp.atlassian.example"),
        ("slack", "stdio", "uvx", None),
        ("paste-share", "http", None, "mcp.paste-share.example"),
        ("postgres", "stdio", "docker", None),
    ]
    out, expected = [], []
    t = START
    hosts = [("ws-0042", "alice"), ("lt-0107", "bob"), ("ws-0311", "carol"), ("lt-0220", "dave"), ("ws-0418", "erin")]
    for i in range(55):
        host, user = hosts[i % len(hosts)]
        client = list(clients)[i % len(clients)]
        server, transport, command, url_host = servers[(i * 7) % len(servers)]
        t += timedelta(seconds=rng.randint(1, 40))
        rec = {"event": "mcp_inventory", "time": t.isoformat(), "host": host, "os_user": user, "client": client, "server": server, "transport": transport, "command": command, "url_host": url_host, "scope": "user", "config": clients[client].format(u=user)}
        out.append(json.dumps(rec, separators=(",", ":")))
        row: dict[str, object] = {"parse_status": "ok", "class_uid": 5020, "device_hostname": host, "actor_user_name": user, "message": server, "time": t.isoformat()}
        if url_host:
            row["dst_endpoint_hostname"] = url_host
        if command:
            row["actor_process_name"] = command
        expected.append(row)
    return out, expected


PATHOLOGICAL_CC = [
    '{"signal":"log","time":"not a time","service":"claude-code","event":"claude_code.tool_result","attr":{"user_email":"x@example.com"}}',
    '{"signal":"log","time":null,"service":"claude-code","event":"claude_code.api_request","attr":"not an object"}',
    '{"signal":"metric","time":"2026-10-14T18:00:00+00:00","metric":"claude_code.cost.usage","value":"NaN","attr":{"user_email":["a","b"]}}',
    '{"signal":"log","event":"claude_code.tool_result","attr":{"success":{"nested":true},"user_email":12345}}',
    '{"signal":"log","event":"claude_code.' + "x" * 9000 + '"}',
    '{"signal":"log","time":"2026-10-14T18:00:00+00:00","event":"claude_code.user_prompt","attr":{"user_email":"' + "a" * 70000 + '"}}',
    '{"signal":"log","truncated',
    "not json at all",
    "",
    '[1,2,3]',
]
PATHOLOGICAL_INV = [
    '{"event":"mcp_inventory","time":"yesterday","host":null,"server":{"name":"x"}}',
    '{"event":"mcp_inventory","server":"' + "s" * 70000 + '"}',
    '{"event":"mcp_inventory","host":["a"],"os_user":42,"command":true}',
    '{"event":"mcp_inventory"',
    "garbage line with no braces",
    "",
    '{"event":"something_else","server":"github"}',
]


def write(name: str, sample: list[str], expected: list[dict[str, object]], patho: list[str], readme: str) -> None:
    folder = FIX / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sample.log").write_text("\n".join(sample) + "\n", encoding="utf-8")
    (folder / "expected.jsonl").write_text("\n".join(json.dumps(e, sort_keys=True) for e in expected[:10]) + "\n", encoding="utf-8")
    (folder / "pathological.log").write_text("\n".join(patho) + "\n", encoding="utf-8")
    (folder / "README.md").write_text(readme, encoding="utf-8")
    print(f"{name}: {len(sample)} lines", file=sys.stderr)


def main() -> None:
    rng = random.Random(42)
    cc, cc_exp = claude_code(rng)
    write("claude_code_otel", cc, cc_exp, PATHOLOGICAL_CC, README_CC)
    inv, inv_exp = inventory(rng)
    write("mcp_inventory", inv, inv_exp, PATHOLOGICAL_INV, README_INV)


README_CC = """# claude_code_otel fixtures

| | |
|---|---|
| Source product | Claude Code 2.x OpenTelemetry export (logs and metrics) |
| Collector shape | OTLP/HTTP JSON as sent with `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`, converted by Remnant's receiver (`app/ingest/otlp.py`) with content dropped |
| Generator | `scripts/fixtures/ai_telemetry.py` (seed 42) |
| Values | Synthetic `example.com` users, invented hosts and sessions |

Sessions mix user_prompt (text dropped, length kept), api_request, tool_decision and tool_result for built-in tools and MCP servers (server and tool names kept from tool_parameters, arguments dropped), api_error, and cost and token metric points. Pathological lines cover bad times, wrong types, huge values, and broken JSON.
"""
README_INV = """# mcp_inventory fixtures

| | |
|---|---|
| Source product | MCP client configuration on endpoints (Claude Desktop, Claude Code, Cursor, VS Code) |
| Collector shape | JSON lines written by `scripts/endpoint/mcp-inventory.ps1` / `mcp_inventory.py` |
| Generator | `scripts/fixtures/ai_telemetry.py` (seed 42) |
| Values | Invented hosts, users, and server names; remote servers use `.example` hosts |

Pathological lines cover wrong types, a huge server name, truncated JSON, and unrelated events.
"""

if __name__ == "__main__":
    main()
