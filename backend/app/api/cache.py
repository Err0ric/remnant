"""A short per-scope cache for the heavy page reads (owner, 2026-10-31): a reload of the
Dashboard, AI Watch, AI usage, or Microsoft 365 within a minute reuses the numbers instead
of reading the lake again. Keys always carry the caller's permitted sources, so a cached
answer is only ever served to a caller with exactly the same scope (rule 13); every request
is still audited."""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Hashable
from time import monotonic
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from app.core import timing

TTL_S = 60.0
MAX_ENTRIES = 256


class PageCache:
    def __init__(self, ttl_s: float = TTL_S) -> None:
        self._ttl = ttl_s
        self._items: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            hit = self._items.get(key)
            if hit is None or monotonic() - hit[0] >= self._ttl:
                self._items.pop(key, None)
                timing.cache("miss")
                return None
            timing.cache("hit")
            return hit[1]

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if len(self._items) >= MAX_ENTRIES:
                oldest = min(self._items, key=lambda k: self._items[k][0])
                self._items.pop(oldest, None)
            self._items[key] = (monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def scope_key(allowed: list[str] | None) -> tuple[str, ...] | None:
    return None if allowed is None else tuple(sorted(allowed))


WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def clear_on_change(
    cache: PageCache,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Middleware: a successful change anywhere (a review, a closed alert, a setting)
    empties the cache, so the next page shows it; reads keep their 60 s."""

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.method in WRITES and response.status_code < 400:
            cache.clear()
        return response

    return middleware


def server_timing() -> Callable[
    [Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]
]:
    """Middleware: a Server-Timing header on API responses that read the cache or ran
    queries (owner, 2026-11-01): cache hit or miss, waiting for a slot and memory, DuckDB,
    the rest, and the total. Timings only, nothing about the data."""

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        t = timing.start(request.url.path)
        response = await call_next(request)
        header = t.header()
        if header is not None:
            response.headers["Server-Timing"] = header
        return response

    return middleware
