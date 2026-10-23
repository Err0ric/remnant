#!/usr/bin/env python3
"""Fixtures for the claude_hooks template (ADR-0026): what the hooks plugin sends, run
through the receiver's own conversion, so the lines are exactly what lands in a spool.

    cd backend && uv run python ../scripts/fixtures/claude_hooks.py

Synthetic only: example.com people, invented hosts, sessions, and paths.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.ingest.otlp import log_records  # noqa: E402

FIX = ROOT / "backend" / "tests" / "fixtures" / "logs" / "claude_hooks"
START = datetime(2026, 10, 22, 17, 0, tzinfo=UTC)
PEOPLE = [("alice@example.com", "alice", "ws-0042"), ("bob@example.com", "bob", "lt-0107"), ("", "carol", "ws-0311")]
TOOLS = [
    ("Read", {"path": "/home/{u}/app/src/main.py"}),
    ("Edit", {"path": "/home/{u}/app/src/auth.py"}),
    ("Bash", {"program": "pytest"}),
    ("WebFetch", {"web_host": "docs.example.com"}),
    ("mcp__github__search_issues", {"mcp_server_name": "github", "mcp_tool_name": "search_issues"}),
    ("Bash", {"program": "curl"}),
]
NAMES = {
    "session_start": "session",
    "user_prompt_submit": "user",
    "pre_tool_use": "tool_call",
    "post_tool_use": "tool_result",
    "stop": "session",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def payload(t: datetime, host: str, attr: dict[str, object]) -> dict[str, object]:
    def value(v: object) -> dict[str, object]:
        return {"intValue": str(v)} if isinstance(v, int) else {"stringValue": str(v)}

    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "claude-hooks"}},
                        {"key": "host.name", "value": {"stringValue": host}},
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "claude-hooks", "version": "1.0.0"},
                        "logRecords": [
                            {
                                "timeUnixNano": str(int(t.timestamp()) * 1_000_000_000),
                                "body": {"stringValue": str(attr["event_name"])},
                                "attributes": [
                                    {"key": k, "value": value(v)}
                                    for k, v in attr.items()
                                    if v not in (None, "")
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def main() -> None:
    rng = random.Random(26)
    lines: list[str] = []
    expected: list[dict[str, object]] = []
    t = START
    for n in range(6):
        email, os_user, host = PEOPLE[n % len(PEOPLE)]
        session = f"sess-{n:03d}"
        events: list[tuple[str, dict[str, object]]] = [("session_start", {"session_source": "startup"})]
        prompt = f"fix the failing test number {n}"
        events.append(("user_prompt_submit", {"prompt_sha256": sha(prompt), "prompt_chars": len(prompt)}))
        for tool, extra in rng.sample(TOOLS, 3):
            filled = {k: str(v).replace("{u}", os_user) for k, v in extra.items()}
            events.append(("pre_tool_use", {"tool_name": tool, **filled, "tool_input_sha256": sha(tool + session), "tool_input_chars": rng.randint(20, 400)}))
            events.append(("post_tool_use", {"tool_name": tool, **filled, "tool_input_chars": rng.randint(20, 400), "tool_response_chars": rng.randint(10, 20000)}))
        events.append(("stop", {}))
        for name, extra in events:
            t += timedelta(seconds=rng.randint(1, 40))
            attr: dict[str, object] = {"event_name": f"claude_hooks.{name}", "role": NAMES[name], "session_id": session, "user": email, "os_user": os_user, "cwd": f"/home/{os_user}/app", **extra}
            for rec in log_records(payload(t, host, attr), keep_content=False):
                lines.append(json.dumps(rec, separators=(",", ":"), ensure_ascii=False))
                row: dict[str, object] = {"parse_status": "ok", "class_uid": 6003, "message": f"claude_hooks.{name}", "actor_user_name": email or os_user, "device_hostname": host, "activity_id": 2 if name in ("post_tool_use", "stop") else 1}
                if extra.get("web_host"):
                    row["dst_endpoint_hostname"] = extra["web_host"]
                expected.append(row)
    FIX.mkdir(parents=True, exist_ok=True)
    (FIX / "sample.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (FIX / "expected.jsonl").write_text("\n".join(json.dumps(e, sort_keys=True) for e in expected[:10]) + "\n", encoding="utf-8")
    (FIX / "pathological.log").write_text("\n".join(PATHOLOGICAL) + "\n", encoding="utf-8")
    (FIX / "README.md").write_text(README, encoding="utf-8")
    print(f"claude_hooks: {len(lines)} lines", file=sys.stderr)


PATHOLOGICAL = [
    '{"signal":"log","time":"not a time","service":"claude-hooks","event":"claude_hooks.pre_tool_use","attr":{"user":"x@example.com"}}',
    '{"signal":"log","time":null,"service":"claude-hooks","event":"claude_hooks.stop","attr":"not an object"}',
    '{"signal":"log","time":"2026-10-22T18:00:00+00:00","service":"claude-hooks","event":"claude_hooks.post_tool_use","attr":{"user":["a","b"],"path":' + json.dumps("/x" * 4000) + "}}",
    '{"signal":"log","event":"claude_hooks.',
    "garbage line with no braces",
    "",
    '{"signal":"log","time":"2026-10-22T18:00:00+00:00","event":"claude_hooks.unknown_event","attr":{"user":"x@example.com","role":"\\u0000"}}',
]
README = """# claude_hooks fixtures

| | |
|---|---|
| Source product | Remnant hooks plugin 1.0.0 for Claude Code and Cowork (ADR-0026), `hooks/send.sh` |
| Collector shape | OTLP/HTTP JSON log records, converted by Remnant's receiver (`app/ingest/otlp.py`) with content dropped |
| Generator | `scripts/fixtures/claude_hooks.py` (seed 26) |
| Values | Synthetic `example.com` people (one with no account email, so the OS user is used), invented hosts, sessions, and paths |

Six sessions: start, prompt (hash and length only), three tool calls with their results (file paths, a web host, program names, an MCP server and tool), and stop. Pathological lines cover bad times, wrong types, a very long path, an unknown event, and broken JSON.
"""

if __name__ == "__main__":
    main()
