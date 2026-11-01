"""Per-request timings for the Server-Timing header (owner, 2026-11-01): whether a page came
from the 60-second cache, time waiting for a query slot and memory, time in DuckDB, and the
rest (Python, audit, serialization). The request's middleware sets a collector in a context
variable; the engine and the page cache add to it from whatever thread runs them, as long
as the thread was started with the request's context (run_in_threadpool does this; plain
thread pools use `in_context`). Queries that run in parallel add up, so `db` can be more
than the wall time; `app` is what is left of the total, never below 0."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Timing:
    started: float = field(default_factory=time.perf_counter)
    wait_ms: float = 0.0
    db_ms: float = 0.0
    queries: int = 0
    cache: str | None = None  # "hit" or "miss"
    path: str | None = None  # the request, for query traces
    lock: threading.Lock = field(default_factory=threading.Lock)
    # When each query waited and ran (perf_counter seconds), for wall times: queries in
    # parallel overlap, so their sums can pass the total (owner, 2026-11-01).
    waits: list[tuple[float, float]] = field(default_factory=list)
    runs: list[tuple[float, float]] = field(default_factory=list)

    def query(self, wait_s: float, db_s: float) -> None:
        end = time.perf_counter()
        with self.lock:
            self.queries += 1
            self.wait_ms += wait_s * 1000
            self.db_ms += db_s * 1000
            self.runs.append((end - db_s, end))
            self.waits.append((end - db_s - wait_s, end - db_s))

    def header(self) -> str | None:
        if not self.queries and self.cache is None:
            return None
        total = (time.perf_counter() - self.started) * 1000
        with self.lock:
            db, wait = _covered(self.runs), _covered(self.waits)
            busy = _covered(self.runs + self.waits)
        # Wall times: while any query ran (db), while any waited (wait), and the rest (app).
        # The sums over queries in parallel are kept as db_sum and wait_sum.
        app = max(0.0, total - busy)
        parts = []
        if self.cache is not None:
            parts.append(f'cache;desc="{self.cache}"')
        parts += [
            f"wait;dur={wait:.1f}",
            f'db;dur={db:.1f};desc="{self.queries} queries"',
            f"app;dur={app:.1f}",
            f"total;dur={total:.1f}",
            f"db_sum;dur={self.db_ms:.1f}",
            f"wait_sum;dur={self.wait_ms:.1f}",
        ]
        return ", ".join(parts)


def _covered(spans: list[tuple[float, float]]) -> float:
    """Milliseconds covered by at least one span."""
    total, end = 0.0, float("-inf")
    for a, b in sorted(spans):
        if b <= end:
            continue
        total += b - max(a, end)
        end = b
    return total * 1000


_current: ContextVar[Timing | None] = ContextVar("timing", default=None)


def start(path: str | None = None) -> Timing:
    t = Timing(path=path)
    _current.set(t)
    return t


def current() -> Timing | None:
    return _current.get()


def cache(result: str) -> None:
    t = _current.get()
    if t is not None and t.cache != "miss":  # one miss in a request is a miss
        t.cache = result


def in_context[T](fn: Callable[..., T]) -> Callable[..., T]:
    """`fn` wrapped to run in a copy of the caller's context, for thread pools."""
    parent = copy_context()

    def run(*args: Any, **kwargs: Any) -> T:
        return parent.copy().run(fn, *args, **kwargs)

    return run
