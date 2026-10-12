#!/usr/bin/env python3
"""Measure ingest rate, lake size, and query latency on this machine (README tested scale).

Generates synthetic syslog with scripts/loggen.py, ingests it through the real watcher
(Automatic parser), then times a few typical searches through the real /api/query path.
Everything lives in a temporary folder that is deleted afterwards.

    cd backend && uv run python ../scripts/bench.py --events 200000
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import loggen  # noqa: E402  # sibling script, standard library only

QUERIES = {
    "count all": "SELECT count(*) FROM events",
    "events per host": "SELECT device_hostname, count(*) FROM events GROUP BY 1 ORDER BY 2 DESC",
    "failed logins by source IP": (
        "SELECT src_endpoint_ip, count(*) FROM events WHERE class_uid = 3002 AND status_id = 2"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    ),
    "text search in message": (
        "SELECT time, message FROM events WHERE message ILIKE '%invalid user%'"
        " ORDER BY coalesce(time, time_observed) DESC LIMIT 100"
    ),
    "latest 100 events": (
        "SELECT * FROM events ORDER BY coalesce(time, time_observed) DESC LIMIT 100"
    ),
}


def hardware() -> dict[str, str]:
    cpu = platform.processor() or "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem = "unknown"
    try:
        kb = int(Path("/proc/meminfo").read_text().split()[1])
        mem = f"{kb / 1024 / 1024:.1f} GB"
    except (OSError, ValueError, IndexError):
        pass
    return {
        "CPU": f"{cpu}, {os.cpu_count()} cores",
        "Memory": mem,
        "OS": f"{platform.system()} {platform.release()}",
        "Python": platform.python_version(),
    }


def du(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--events", type=int, default=100_000, help="Events to generate")
    p.add_argument("--runs", type=int, default=5, help="Timed runs per query")
    args = p.parse_args(argv)

    from fastapi.testclient import TestClient

    from app.core.config import load_config
    from app.core.logging import configure_logging
    from app.main import create_app

    configure_logging("WARNING")
    with tempfile.TemporaryDirectory(prefix="bench-") as tmp:
        root = Path(tmp)
        logs = root / "logs"
        loggen.main(
            ["--out", str(logs), "--backfill", str(args.events), "--rate", "0", "--seed", "7"]
        )
        raw_bytes = du(logs / "syslog")
        config = load_config(
            Path("missing.yaml"),
            {
                "APP__PATHS__DATA_DIR": str(root / "data"),
                "APP__PATHS__ALLOWED_ROOTS": str(logs),
                "APP__INGEST__ENABLED": "false",
            },
        )
        app = create_app(config)
        c = TestClient(app, base_url="http://127.0.0.1:8080")
        res = c.post(
            "/api/sources",
            json={
                "source_id": "bench_syslog",
                "format": "syslog",
                "path": str(logs / "syslog"),
                "glob": "**/*.log",
                "template_id": "auto",
            },
        )
        res.raise_for_status()

        started = time.perf_counter()
        total = 0
        while (n := app.state.ingest.run_once()) > 0:
            total += n
        ingest_s = time.perf_counter() - started
        lake_bytes = du(root / "data" / "lake")

        timings: dict[str, float] = {}
        for name, sql in QUERIES.items():
            samples = []
            for _ in range(args.runs):
                t = time.perf_counter()
                r = c.post("/api/query", json={"sql": sql})
                r.raise_for_status()
                samples.append((time.perf_counter() - t) * 1000)
            timings[name] = statistics.median(samples)

    report: dict[str, Any] = {
        **hardware(),
        "Events ingested": f"{total:,}",
        "Ingest rate": f"{total / ingest_s:,.0f} events/s (Automatic parser, one source)",
        "Raw log size": f"{raw_bytes / 1e6:.1f} MB",
        "Lake size": f"{lake_bytes / 1e6:.1f} MB ({raw_bytes / max(lake_bytes, 1):.1f}x smaller)",
    }
    print("| Measure | Result |\n|---|---|")
    for k, v in report.items():
        print(f"| {k} | {v} |")
    print(f"\n| Query (median of {args.runs}) | ms |\n|---|---|")
    for k, v in timings.items():
        print(f"| {k} | {v:.0f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
