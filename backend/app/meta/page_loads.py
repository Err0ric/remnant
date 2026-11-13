"""One audit row per Dashboard visit (handoff item 3, owner 2026-11-12: the audit log
records access, not requests), written at once and never held (rule 14).

The Dashboard sends with every request of one visit an `X-Page-Load` id, an
`X-Page-Load-Parts` list naming every part the page will request (its sections,
"overview", and "ai_watch"), and `X-Page-Load-Window`, the page's window. The first
request with a given
(user, id) writes the `dashboard.view` row before it is answered: the declared parts, the
window, the caller's source scope, and the visit's start. Memory then keeps only what that
row already covers, while the visit lasts, so later requests of the visit that it covers
write nothing (the page's 60 s and 300 s refetches included). The visit is sliding: each of
its requests keeps it open until WINDOW_S (plus JITTER_S for timer drift) after that
request, up to MAX_VISIT_S from its first request; after either, the next request starts a
new visit and writes a new row, with a new start. Nothing waits in memory to be written:
a crash or restart loses only this memory, and the next request simply writes a row again.

The headers are client values, so they can only reduce repeats, never hide access:
- a request is skipped only when a row already written names its exact part, window, and
  source scope, for the same user and id; anything else (a part not in the list, another
  window, a changed scope) writes a new row at once;
- a forged parts list can only make a row list more than was shown, never less: every
  request it covers is a part it named;
- without an id, with a malformed id, list, or window, after the visit ends, or past the cap of
  MAX_LOADS visits, a request writes its own row as before.
AI Watch on the Dashboard (owner, 2026-11-12; amends ADR-0029 G3 for this page): an answer
that names someone still writes its own `ai.view_people` row, every time; an answer that
names no one, read for the visit's own window, is the part `ai_watch` of the visit's row and
writes no `ai.view` row; for any other range the caller writes `ai.view` itself.
"""

import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core import clock
from app.meta.audit import AuditLog

ACTION = "dashboard.view"
LOAD_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
OVERVIEW = "overview"
AI_WATCH = "ai_watch"  # the Dashboard's AI Watch, when it names no one (see below)
# The sections of `app.search.dashboard.PARTS` and its `Window` values (a test checks);
# not imported, as `app.meta` imports no search module.
KNOWN_PARTS = frozenset(("identity", "attacks", "detections", OVERVIEW, AI_WATCH))
WINDOWS = frozenset(("24h", "7d", "30d"))
WINDOW_S = 60.0  # a visit stays open this long after each of its requests
JITTER_S = 5.0  # plus this much, so a 60 s refetch that arrives a little late still counts
MAX_VISIT_S = 12 * 3600.0  # and never longer than this from its first request
MAX_LOADS = 10_000  # beyond this many open visits, requests are audited one by one

Scope = tuple[str, ...] | None  # the caller's readable sources; None: every source
_Key = tuple[str, str | None, Scope]  # (part, window, scope) a written row covers


@dataclass(frozen=True, slots=True)
class Declared:
    """What one request says about its page visit."""

    load_id: str
    parts: frozenset[str]
    window: str | None


def declared(headers: Mapping[str, str]) -> Declared | None:
    """The request's page visit, or None when it has none or any header is malformed."""
    load_id = headers.get("x-page-load")
    raw = headers.get("x-page-load-parts")
    window = headers.get("x-page-load-window")
    if load_id is None or raw is None or not LOAD_ID.fullmatch(load_id) or len(raw) > 256:
        return None
    parts = frozenset(p.strip() for p in raw.split(","))
    if not parts or not parts <= KNOWN_PARTS:
        return None
    if window is not None and window not in WINDOWS:
        return None
    return Declared(load_id, parts, window)


@dataclass(slots=True)
class _Load:
    first: float
    last: float
    started_at: str
    covered: set[_Key] = field(default_factory=set)


def _key(part: str, window: str | None, scope: Scope) -> _Key:
    # The Overview has no window: the same numbers whatever the page's window.
    return (part, None if part == OVERVIEW else window, scope)


def _ended(load: _Load, t: float) -> bool:
    """No request for longer than the window, or open for longer than the hard limit."""
    return t - load.last > WINDOW_S + JITTER_S or t - load.first >= MAX_VISIT_S


class PageLoadAudit:
    def __init__(self, audit: AuditLog, now: Callable[[], float] = time.monotonic) -> None:
        self._audit = audit
        self._now = now
        self._loads: dict[tuple[str, str], _Load] = {}
        self._lock = threading.Lock()

    def record(
        self,
        visit: Declared | None,
        user_id: str,
        ip: str | None,
        parts: list[str],
        window: str | None,
        scope: list[str] | None,
        fallback: tuple[str, dict[str, Any]] | None,
    ) -> None:
        """Audit one request that showed `parts` of the Dashboard at `window`, read from
        `scope` (the caller's readable sources; None: every source). Without a visit, or
        past the cap, `fallback` (action, detail) is written at once, when given. Every row
        is written before this returns. Blocking: call it through the thread pool."""
        if visit is None:
            self._fallback(fallback, user_id, ip)
            return
        sc: Scope = None if scope is None else tuple(sorted(scope))
        w = window if window is not None else visit.window
        with self._lock:  # held while writing, so a concurrent request sees what it covers
            t = self._now()
            key = (user_id, visit.load_id)
            load = self._loads.get(key)
            if load is not None and _ended(load, t):
                del self._loads[key]
                load = None
            if load is None:
                if len(self._loads) >= MAX_LOADS:
                    self._expire(t)
                if len(self._loads) >= MAX_LOADS:
                    self._fallback(fallback, user_id, ip)
                    return
                load = _Load(first=t, last=t, started_at=clock.now().isoformat())
            if all(_key(p, window, sc) in load.covered for p in parts):
                load.last = t  # a written row names exactly this: the visit goes on
                return
            new = sorted(p for p in visit.parts | set(parts) if _key(p, w, sc) not in load.covered)
            self._audit.write(
                ACTION,
                "success",
                user_id,
                ip,
                {
                    "page_load": visit.load_id,
                    "shown": new,
                    "window": w,
                    "sources_in_scope": None if sc is None else list(sc),
                    "started_at": load.started_at,
                },
            )
            # Remembered only once the row is in the audit log.
            load.covered.update(_key(p, w, sc) for p in new)
            load.last = t
            self._loads[key] = load

    def _expire(self, t: float) -> None:
        for k, load in list(self._loads.items()):
            if _ended(load, t):
                del self._loads[k]

    def _fallback(
        self, fallback: tuple[str, dict[str, Any]] | None, user_id: str, ip: str | None
    ) -> None:
        if fallback is not None:
            self._audit.write(fallback[0], "success", user_id, ip, fallback[1])
