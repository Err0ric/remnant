#!/usr/bin/env python3
"""Fixtures for the server_events template (ADR-0040, handoff item 9): the sign-ins,
changes, and refusals this server records about itself, as the writer spools them.

    cd backend && uv run python ../scripts/fixtures/server_events.py

Synthetic only: RFC 5737 addresses, invented user names and token ids.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIX = ROOT / "backend" / "tests" / "fixtures" / "logs" / "server_events"
START = datetime(2026, 10, 30, 20, 0, tzinfo=UTC)
ADDRS = ["198.51.100.20", "203.0.113.9", "192.0.2.44", "2001:db8::7"]
USERS = ["admin", "dana", "root", "erin@example.com"]
USERS_ID = {"alice": 1, "bob": 2, "dana": 3}


PATHS = [
    ("POST", "/api/query", 200),
    ("POST", "/api/searches", 201),
    ("DELETE", "/api/tokens/{token_id}", 204),
    ("PUT", "/api/sources/{source_id}", 403),
    ("POST", "/api/auth/logout", 204),
    ("GET", "/api/audit/{log}/export", 200),
]
ACTIVITY = {"POST": 1, "GET": 2, "PUT": 3, "DELETE": 4}


def record(t: datetime, event: str, attr: dict[str, object]) -> str:
    return json.dumps(
        {
            "signal": "log",
            "time": t.isoformat(),
            "service": "app-server",
            "event": event if event.startswith("server.") else f"server.refused.{event}",
            "attr": attr,
            "resource": {"service_name": "app-server"},
        },
        separators=(",", ":"),
    )


def main() -> None:
    rng = random.Random(40)
    out = []
    expected: list[dict[str, object]] = []
    for i in range(60):
        t = START + timedelta(seconds=7 * i)
        ip = rng.choice(ADDRS)
        kind = rng.choice(["otlp_token", "sign_in", "sso", "api_token", "ok", "request"])
        attr: dict[str, object] = {"client": ip, "dropped_since_last": 0}
        if kind in ("ok", "request"):
            user = rng.choice(["alice", "bob", "dana"])
            uid = f"0f3c2a10-0000-4000-8000-{USERS_ID[user]:012d}"
            if kind == "ok":
                event = "server.sign_in"
                attr |= {"outcome": "success", "user_id": uid, "username": user,
                         "method": rng.choice(["password", "sso"]), "session": "browser"}  # fmt: skip
                row = {"class_uid": 3002, "status_id": 1, "activity_id": 1}
            else:
                event = "server.request"
                method, path, status = rng.choice(PATHS)
                attr |= {"outcome": "success" if status < 400 else "failure", "method": method,
                         "path": path, "status": status, "duration_ms": round(rng.uniform(1, 400), 1),
                         "user_id": uid, "username": user}  # fmt: skip
                row = {"class_uid": 6003, "status_id": 1 if status < 400 else 2,
                       "activity_id": ACTIVITY[method], "status_detail": path}  # fmt: skip
            out.append(record(t, event, attr))
            expected.append({"parse_status": "ok", "message": event, "src_endpoint_ip": ip,
                             "actor_user_name": user, **row})  # fmt: skip
            continue
        if kind == "otlp_token":
            attr |= rng.choice(
                [{"reason": "token", "token_prefix": "rmt_q9Zx"}, {"reason": "revoked", "token_id": f"tok-{i:04d}"}]
            )
        elif kind == "sign_in":
            attr |= {"username": rng.choice(USERS)}
            if i % 9 == 0:
                attr["reason"] = "rate_limited"
        elif kind == "sso":
            attr |= {"reason": rng.choice(["not_invited", "group", "invalid"])}
        else:
            attr |= {"token_prefix": "cli_7Hq2"}
        out.append(record(t, kind, attr))
        row: dict[str, object] = {
            "parse_status": "ok",
            "class_uid": 3002,
            "status_id": 2,
            "message": f"server.refused.{kind}",
            "src_endpoint_ip": ip,
        }
        if attr.get("username"):
            row["actor_user_name"] = attr["username"]
        expected.append(row)
    FIX.mkdir(parents=True, exist_ok=True)
    (FIX / "sample.log").write_text("\n".join(out) + "\n")
    (FIX / "expected.jsonl").write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in expected[:10]) + "\n"
    )
    bad = [
        record(START, "sign_in", {"client": "x" * 9000, "username": "y" * 2000}),
        record(START, "server.request", {"method": "Z" * 5000, "status": "not a status"}),
        record(START, "server.sign_in", {"outcome": ["a", "list"], "client": None}),
        '{"signal":"log","time":"not a time","service":"app-server","event":"server.refused.sso","attr":{}}',
        '{"signal":"log","service":"app-server","event":"server.refused.api_token","attr":null}',
        "\x00\xff garbage " * 1200,
        '{"signal":"log","time":"2026-10-30T20:00:00+00:00","service":"app-server","event":"server.refused.',
    ]
    (FIX / "pathological.log").write_text("\n".join(bad) + "\n")


if __name__ == "__main__":
    main()
