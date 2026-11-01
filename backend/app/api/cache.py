"""A short per-scope cache for the heavy page reads (owner, 2026-10-31): a reload of the
Dashboard, AI Watch, AI usage, or Microsoft 365 within a minute reuses the numbers instead
of reading the lake again. Keys always carry the caller's permitted sources, so a cached
answer is only ever served to a caller with exactly the same scope (rule 13); every request
is still audited."""

from __future__ import annotations

import threading
from collections.abc import Hashable
from time import monotonic
from typing import Any

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
                return None
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
