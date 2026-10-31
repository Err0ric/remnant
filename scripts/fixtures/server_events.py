#!/usr/bin/env python3
"""Fixtures for the server_events template (ADR-0040): the refusals this server records
about itself, as the writer spools them.

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


def record(t: datetime, event: str, attr: dict[str, object]) -> str:
    return json.dumps(
        {
            "signal": "log",
            "time": t.isoformat(),
            "service": "app-server",
            "event": f"server.refused.{event}",
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
        kind = rng.choice(["otlp_token", "sign_in", "sso", "api_token"])
        attr: dict[str, object] = {"client": ip, "dropped_since_last": 0}
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
        '{"signal":"log","time":"not a time","service":"app-server","event":"server.refused.sso","attr":{}}',
        '{"signal":"log","service":"app-server","event":"server.refused.api_token","attr":null}',
        "\x00\xff garbage " * 1200,
        '{"signal":"log","time":"2026-10-30T20:00:00+00:00","service":"app-server","event":"server.refused.',
    ]
    (FIX / "pathological.log").write_text("\n".join(bad) + "\n")


if __name__ == "__main__":
    main()
