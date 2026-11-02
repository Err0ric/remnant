"""A short per-scope cache for the heavy page reads (owner, 2026-10-31): a reload of the
Dashboard, AI Watch, AI usage, or Microsoft 365 within a minute reuses the numbers instead
of reading the lake again. Keys always carry the caller's permitted sources, so a cached
answer is only ever served to a caller with exactly the same scope (rule 13); every request
is still audited."""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from time import monotonic
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from app.auth.users import User, UserStore
from app.core import timing
from app.core.speed import SpeedLog
from app.core.threads import run_low
from app.engine.views import permitted_sources
from app.meta.db import MetaDB

log = structlog.get_logger(__name__)

TTL_S = 60.0
MAX_ENTRIES = 256
# Default views (Dashboard 7d, Microsoft 365 Overview 7d, AI Watch 7d) are refreshed in the
# background and served at once from the last refresh (owner, 2026-11-01).
REFRESH_EVERY_S = 60.0
STALE_MAX_S = 300.0  # older than this (refreshes stopped or failing): computed in the request
WATCH_S = 600.0  # a view is refreshed while someone opened it in the last 10 minutes
MAX_WATCHED = 64


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

    def peek(self, key: Hashable, max_age_s: float) -> tuple[Any, float] | None:
        """A kept value and its age, up to `max_age_s` old (default views, refreshed in the
        background): (value, seconds since it was computed)."""
        with self._lock:
            hit = self._items.get(key)
        age = None if hit is None else monotonic() - hit[0]
        if hit is None or age is None or age >= max_age_s:
            timing.cache("miss")
            return None
        timing.cache("hit")
        return hit[1], age

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


# compute(user, permitted sources) -> (JSON body, sources read)
Compute = Callable[[User, list[str] | None], tuple[bytes, list[str]]]


@dataclass
class _Watched:
    user_id: str
    scope: tuple[str, ...] | None
    compute: Compute
    seen: float


class Refresher:
    """Recomputes the default views people opened recently, at low CPU priority, so the
    next load is served at once. Each refresh runs as the viewer who opened it, with their
    permissions read again: a disabled user, or one whose sources changed, is dropped and
    their views are computed in the request again (rule 13). A refresh is not audited;
    the view served from it is, like any cached view (D147, proposed)."""

    def __init__(self, cache: PageCache, meta: MetaDB, users: UserStore) -> None:
        self._cache = cache
        self._meta = meta
        self._users = users
        self._watched: dict[Hashable, _Watched] = {}
        self._lock = threading.Lock()

    def watch(
        self, key: Hashable, user_id: str, scope: tuple[str, ...] | None, compute: Compute
    ) -> None:
        with self._lock:
            if key not in self._watched and len(self._watched) >= MAX_WATCHED:
                oldest = min(self._watched, key=lambda k: self._watched[k].seen)
                self._watched.pop(oldest, None)
            self._watched[key] = _Watched(user_id, scope, compute, monotonic())

    def tick(self) -> int:
        """Refresh every view seen in the last WATCH_S; returns how many were refreshed."""
        now = monotonic()
        with self._lock:
            for key in [k for k, w in self._watched.items() if now - w.seen > WATCH_S]:
                self._watched.pop(key, None)
            items = list(self._watched.items())
        done = 0
        for key, w in items:
            user = self._users.get(w.user_id)
            allowed = permitted_sources(self._meta, user) if user and not user.disabled else None
            if user is None or user.disabled or scope_key(allowed) != w.scope:
                with self._lock:
                    self._watched.pop(key, None)
                continue
            try:
                value = run_low(lambda u=user, a=allowed, c=w.compute: c(u, a))  # type: ignore[misc]  # bound per item
            except Exception as exc:  # one failing view must not stop the others
                log.warning("page.refresh_failed", view=str(key), error=type(exc).__name__)
                continue
            self._cache.put(key, value)
            done += 1
        return done


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


def server_timing(
    speed: SpeedLog | None = None,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
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
            # Health > Speed: by route template, never the values in the path.
            route = request.scope.get("route")
            summary = t.summary()
            template = getattr(route, "path", None)
            if isinstance(template, str) and not template.startswith("/api/"):
                template = "/api" + template  # routers are mounted under /api
            if speed is not None and summary is not None and isinstance(template, str):
                speed.record(
                    f"{request.method} {template}", summary["total"], summary["db"],
                    summary["wait"], summary["cache"],
                )  # fmt: skip
        return response

    return middleware
