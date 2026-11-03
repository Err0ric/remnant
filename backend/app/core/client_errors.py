"""Errors the web UI reports from people's browsers (owner 2026-11-02): kept in memory for
Health (the last 24 hours, at most KEEP) and written to the server log. Rate-limited per
user and overall, so a broken page in many tabs cannot flood either. The browser sends only
an error kind, a scrubbed short message, the page path, and its build: never log content."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

KEEP = 50
PER_USER_PER_MINUTE = 10
PER_MINUTE = 60


@dataclass(slots=True)
class ClientError:
    at: datetime
    error_id: str
    kind: str
    name: str
    message: str
    route: str
    build: str
    stale: bool  # the page was built before the build this server serves
    user_id: str | None


class ClientErrors:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: deque[ClientError] = deque(maxlen=KEEP)
        self._hits: dict[str, deque[datetime]] = {}
        self.dropped = 0

    def allow(self, user_id: str | None, now: datetime) -> bool:
        """Count one report; False when this user or the server is over its limit."""
        with self._lock:
            ok = True
            for key, cap in ((f"u:{user_id}", PER_USER_PER_MINUTE), ("*", PER_MINUTE)):
                q = self._hits.setdefault(key, deque())
                while q and now - q[0] > timedelta(minutes=1):
                    q.popleft()
                if len(q) >= cap:
                    ok = False
            if ok:
                for key in (f"u:{user_id}", "*"):
                    self._hits[key].append(now)
            else:
                self.dropped += 1
            return ok

    def add(self, error: ClientError) -> None:
        with self._lock:
            self._kept.append(error)

    def recent(self, now: datetime) -> list[ClientError]:
        """Newest first, the last 24 hours."""
        with self._lock:
            rows = [e for e in self._kept if now - e.at <= timedelta(hours=24)]
        return sorted(rows, key=lambda e: e.at, reverse=True)
