#!/usr/bin/env python3
"""Time a running install's Dashboard the way the browser loads it: every section of the
7-day and 30-day windows at once, several rounds, wall time per round (D145).

Each round asks with a different time zone, so the 60-second page cache never answers
and every round runs its queries. Standard library only; uses a CLI API token.

    REMNANT_TOKEN=... python3 scripts/bench_pages.py https://remnant.home.internal:8443 --insecure

Compare settings by restarting the server with each set in remnant.env, for example
APP__SERVER__PAGE_QUERY_MB=256, APP__SERVER__MAX_CONCURRENT_QUERIES=8, or
APP__SERVER__SECTION_PARALLEL=1, then running this again.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request

PARTS = ("identity", "attacks", "detections")
WINDOWS = ("7d", "30d")
# Zones a whole hour apart from UTC, so each round is a fresh cache key with the same work.
ZONES = ("UTC", "Etc/GMT+1", "Etc/GMT+2", "Etc/GMT+3", "Etc/GMT+4", "Etc/GMT+5", "Etc/GMT+6")


def _get(base: str, path: str, token: str, ctx: ssl.SSLContext | None) -> tuple[int, float, str]:
    req = urllib.request.Request(  # noqa: S310  # http(s) only, checked in main
        base + path, headers={"Authorization": f"Bearer {token}"}
    )
    t = time.perf_counter()
    with urllib.request.urlopen(req, context=ctx, timeout=120) as res:  # noqa: S310  # http(s) only, checked in main
        res.read()
        return res.status, time.perf_counter() - t, res.headers.get("Server-Timing", "")


def round_once(base: str, token: str, tz: str, ctx: ssl.SSLContext | None) -> tuple[float, list]:
    found: list = []
    lock = threading.Lock()

    def one(window: str, part: str) -> None:
        q = urllib.parse.urlencode({"window": window, "part": part, "tz": tz})
        got = _get(base, f"/api/dashboard/sections?{q}", token, ctx)
        with lock:
            found.append((window, part, *got))

    threads = [threading.Thread(target=one, args=(w, p)) for w in WINDOWS for p in PARTS]
    t = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return time.perf_counter() - t, found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("base", help="server URL, for example https://remnant.home.internal:8443")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--insecure", action="store_true", help="accept a self-signed certificate")
    ap.add_argument("--json", action="store_true", help="print one JSON line instead")
    args = ap.parse_args()
    token = os.environ.get("REMNANT_TOKEN", "")
    if not token:
        print("Set REMNANT_TOKEN to a CLI API token (Settings > API tokens).", file=sys.stderr)
        return 2
    ctx = ssl._create_unverified_context() if args.insecure else None  # noqa: S323  # opt-in, self-signed installs
    base = args.base.rstrip("/")
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        print("The server URL must start with http:// or https://", file=sys.stderr)
        return 2
    walls = []
    for i in range(args.rounds):
        wall, found = round_once(base, token, ZONES[i % len(ZONES)], ctx)
        walls.append(wall)
        if not args.json:
            print(f"round {i + 1}: {wall:.2f} s")
            for window, part, status, secs, st in sorted(found):
                print(f"  {window:>3} {part:<10} {status} {secs:.2f} s  {st}")
    later = walls[1:] or walls
    summary = {
        "rounds": [round(w, 2) for w in walls],
        "median_s": round(statistics.median(later), 2),
        "worst_s": round(max(later), 2),
    }
    print(
        json.dumps(summary)
        if args.json
        else f"median {summary['median_s']} s, worst {summary['worst_s']} s (first round left out)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
