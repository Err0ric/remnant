#!/usr/bin/env python3
"""Load test before the Claude plugin pilot (owner's batch, item 6): synthetic hook records
from the hooks plugin (default 30 people x 500 records a day x 30 days), parsed by the
claude_hooks template into a temporary lake, the AI rollup and today build made, then AI
usage, AI Watch, the AI inventory, and a person's Timeline timed through the real API.

    cd backend && uv run python ../scripts/bench_hooks.py --people 30 --per-day 500 --days 30

Synthetic only: example.com people, invented hosts, sessions, and paths. Everything lives
in a temporary folder that is deleted afterwards (keep it with --keep).
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import load_config  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.ingest.otlp import NativeLine, log_records  # noqa: E402
from app.ingest.records import DecodedLine  # noqa: E402
from app.ingest.writer import LakeWriter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.templates.loader import load_dir  # noqa: E402
from app.templates.registry import STARTER_DIR  # noqa: E402
from app.templates.runtime import TemplateNormalizer  # noqa: E402
from app.templates.tables import load_tables  # noqa: E402

TOOLS = [
    ("Read", {"path": "/home/{u}/app/src/main.py"}),
    ("Edit", {"path": "/home/{u}/app/src/auth.py"}),
    ("Bash", {"program": "pytest"}),
    ("Grep", {"path": "/home/{u}/app"}),
    ("WebFetch", {"web_host": "docs.example.com"}),
    ("WebFetch", {"web_host": "claude.ai"}),
    ("WebSearch", {"web_host": "api.anthropic.com"}),
    ("mcp__github__search_issues", {"mcp_server_name": "github", "mcp_tool_name": "search"}),
    ("mcp__tickets__create", {"mcp_server_name": "tickets", "mcp_tool_name": "create"}),
]


def otlp(t: datetime, host: str, attr: dict[str, object]) -> dict[str, Any]:
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
                        "scope": {"name": "claude-hooks"},
                        "logRecords": [
                            {
                                "timeUnixNano": str(int(t.timestamp()) * 1_000_000_000),
                                "body": {"stringValue": str(attr["event_name"])},
                                "attributes": [
                                    {"key": k, "value": {"stringValue": str(v)}}
                                    for k, v in attr.items()
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def records(person: int, day: datetime, per_day: int, rng: random.Random) -> list[str]:
    """One person's day: sessions of a start, prompts, tool call and result pairs, a stop,
    and an end, spread over working hours, until about `per_day` records."""
    user, host = f"user{person:02d}@example.com", f"ws-{person:04d}"
    out: list[str] = []
    t = day + timedelta(hours=8, minutes=rng.randrange(60))
    seq, n = 0, 0
    while n < per_day:
        sid = f"s-{person:02d}-{day:%m%d}-{n}"
        events: list[tuple[str, dict[str, object]]] = [("session_start", {"role": "session"})]
        for _ in range(rng.randint(3, 8)):
            events.append(("user_prompt_submit", {"role": "user", "prompt_chars": 40}))
            for _ in range(rng.randint(2, 6)):
                tool, extra = rng.choice(TOOLS)
                extra = {k: str(v).format(u=f"u{person}") for k, v in extra.items()}
                events.append(("pre_tool_use", {"role": "tool_call", "tool_name": tool, **extra}))
                after = "post_tool_use_failure" if rng.random() < 0.03 else "post_tool_use"
                events.append((after, {"role": "tool_result", "tool_name": tool, **extra}))
            events.append(("stop", {"role": "turn"}))
        events.append(("session_end", {"role": "session"}))
        for name, attrs in events:
            if n >= per_day:
                break
            seq += 1
            n += 1
            t += timedelta(seconds=rng.randint(5, 90))
            attr = {
                "event_name": f"claude_hooks.{name}",
                "session_id": sid,
                "install_id": f"i-{person}",
                "seq": seq,
                "user": user,
                "os_user": f"u{person}",
                **attrs,
            }
            for rec in log_records(otlp(t, host, attr), keep_content=False):
                out.append(rec.text if isinstance(rec, NativeLine) else json.dumps(rec))
    return out


def build_lake(lake: Path, people: int, per_day: int, days: int, now: datetime) -> int:
    tables, _ = load_tables(STARTER_DIR / "maps")
    templates, _ = load_dir(STARTER_DIR, tables)
    rng = random.Random(7)  # noqa: S311  # synthetic data, repeatable
    writer = LakeWriter(lake)
    total = 0
    for back in range(days, -1, -1):  # the oldest day first; today is partial
        day = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        seen = day + timedelta(hours=23) if back else now - timedelta(minutes=10)
        norm = TemplateNormalizer(
            templates["claude_hooks"], "hooks", clock=lambda s=seen: s, tables=tables
        )
        rows = []
        for p in range(people):
            for line in records(p, day, per_day if back else per_day // 3, rng):
                row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
                if row is not None and (row["time"] or day) <= now:
                    rows.append(row)
        writer.write(rows)
        total += len(rows)
    return total


def timed(
    c: TestClient, app: Any, path: str, params: dict[str, Any], runs: int = 3
) -> tuple[float, str]:
    times, header = [], ""
    for _ in range(runs):
        app.state.page_cache.clear()
        t = time.perf_counter()
        res = c.get(path, params=params)
        times.append(time.perf_counter() - t)
        if res.status_code != 200:
            raise SystemExit(f"{path}: {res.status_code} {res.text[:200]}")
        header = res.headers.get("Server-Timing", "")
    return statistics.median(times), header


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--people", type=int, default=30)
    ap.add_argument("--per-day", type=int, default=500)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = ap.parse_args()
    configure_logging("WARNING")
    tmp = Path(tempfile.mkdtemp(prefix="bench-hooks-"))
    try:
        now = datetime.now(UTC).replace(microsecond=0)
        t0 = time.perf_counter()
        n = build_lake(tmp / "data" / "lake", args.people, args.per_day, args.days, now)
        print(f"lake: {n:,} hook records in {time.perf_counter() - t0:.0f} s")
        config = load_config(
            Path("missing.yaml"),
            {"APP__PATHS__DATA_DIR": str(tmp / "data"), "APP__INGEST__ENABLED": "false"},
        )
        app = create_app(config)
        src = SimpleNamespace(source_id="hooks", kind="otlp", template_id="claude_hooks")
        app.state.sources.list = lambda: [src]
        t0 = time.perf_counter()
        roll = app.state.ai_rollup
        while roll.run().pending:
            pass
        roll.recheck(budget_s=600)
        roll.refresh_today(max_age_s=0)
        print(f"AI rollup and today build: {time.perf_counter() - t0:.1f} s")
        c = TestClient(app, base_url="http://127.0.0.1")  # loopback, no users: open
        start = lambda d: (now - timedelta(days=d)).replace(second=0).isoformat()  # noqa: E731
        rows = []
        for label, path, params in [
            ("AI usage 7d", "/api/ai/usage", {"start": start(7)}),
            ("AI usage 30d", "/api/ai/usage", {"start": start(30)}),
            ("AI Watch 7d", "/api/ai/watch/summary", {"days": 7}),
            ("AI Watch 30d", "/api/ai/watch/summary", {"days": 30}),
            ("AI inventory 30d", "/api/ai/inventory", {"days": 30}),
            ("Timeline 1d", "/api/people/user03@example.com/timeline", {"days": 1}),
            ("Timeline 7d", "/api/people/user03@example.com/timeline", {"days": 7}),
            ("Timeline 30d", "/api/people/user03@example.com/timeline", {"days": 30}),
        ]:
            secs, header = timed(c, app, path, params)
            rows.append((label, secs, header))
            print(f"{label:<18} {secs:6.2f} s  {header}")
        return 0
    finally:
        if args.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
