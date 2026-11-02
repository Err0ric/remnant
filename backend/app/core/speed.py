"""Page speed over the last 24 hours, for Health > Speed (owner's batch, item 5,
2026-11-01): each API request that sent a Server-Timing header is kept in memory with its
route (the template, such as /api/people/{person}/timeline, never the values), total,
DuckDB and slot-wait wall times, and whether the page cache answered. Nothing about the
data or the caller. Kept in memory only: a restart starts the 24 hours again."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

WINDOW_S = 24 * 3600
MAX_PER_ROUTE = 5000
MAX_ROUTES = 300


@dataclass(frozen=True, slots=True)
class Sample:
    at: float
    total: float
    db: float
    wait: float
    hit: bool | None  # None: no page cache on this route


@dataclass(frozen=True, slots=True)
class RouteSpeed:
    route: str
    requests: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    db_p50_ms: float
    wait_p95_ms: float
    cache_hits: int  # requests the page cache answered
    cached: int  # requests on a cached route (hits and misses)


def _pct(values: list[float], q: float) -> float:
    """Nearest-rank percentile of sorted values."""
    if not values:
        return 0.0
    k = max(0, min(len(values) - 1, math.ceil(q * len(values)) - 1))
    return values[k]


class SpeedLog:
    def __init__(self) -> None:
        self._now = time.monotonic
        self._samples: dict[str, deque[Sample]] = {}
        self._lock = threading.Lock()

    def record(self, route: str, total: float, db: float, wait: float, cache: str | None) -> None:
        now = self._now()
        with self._lock:
            q = self._samples.get(route)
            if q is None:
                if len(self._samples) >= MAX_ROUTES:
                    return  # route templates are a fixed set; this is a guard only
                q = self._samples[route] = deque(maxlen=MAX_PER_ROUTE)
            q.append(Sample(now, total, db, wait, None if cache is None else cache == "hit"))

    def stats(self) -> list[RouteSpeed]:
        cutoff = self._now() - WINDOW_S
        out = []
        with self._lock:
            for route, q in self._samples.items():
                while q and q[0].at < cutoff:
                    q.popleft()
                rows = list(q)
                if not rows:
                    continue
                totals = sorted(r.total for r in rows)
                cached = [r for r in rows if r.hit is not None]
                out.append(
                    RouteSpeed(
                        route=route,
                        requests=len(rows),
                        p50_ms=round(_pct(totals, 0.5), 1),
                        p95_ms=round(_pct(totals, 0.95), 1),
                        max_ms=round(totals[-1], 1),
                        db_p50_ms=round(_pct(sorted(r.db for r in rows), 0.5), 1),
                        wait_p95_ms=round(_pct(sorted(r.wait for r in rows), 0.95), 1),
                        cache_hits=sum(1 for r in cached if r.hit),
                        cached=len(cached),
                    )
                )
        return sorted(out, key=lambda r: -r.p95_ms)
