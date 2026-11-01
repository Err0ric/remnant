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
    lock: threading.Lock = field(default_factory=threading.Lock)

    def query(self, wait_s: float, db_s: float) -> None:
        with self.lock:
            self.queries += 1
            self.wait_ms += wait_s * 1000
            self.db_ms += db_s * 1000

    def header(self) -> str | None:
        if not self.queries and self.cache is None:
            return None
        total = (time.perf_counter() - self.started) * 1000
        app = max(0.0, total - self.wait_ms - self.db_ms)
        parts = []
        if self.cache is not None:
            parts.append(f'cache;desc="{self.cache}"')
        parts += [
            f"wait;dur={self.wait_ms:.1f}",
            f'db;dur={self.db_ms:.1f};desc="{self.queries} queries"',
            f"app;dur={app:.1f}",
            f"total;dur={total:.1f}",
        ]
        return ", ".join(parts)


_current: ContextVar[Timing | None] = ContextVar("timing", default=None)


def start() -> Timing:
    t = Timing()
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
