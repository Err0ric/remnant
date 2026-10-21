"""Failed-login limiter, keyed by client address and by username.

Each attempt is reserved atomically before the slow password check, so parallel
requests cannot all slip past the limit (review finding S2). A successful attempt
clears its keys. The key table is swept so it cannot grow without bound (S8).
"""

import math
import threading
from collections import deque


class LoginLimiter:
    def __init__(self, max_failures: int, window_s: int, max_keys: int = 10_000) -> None:
        self._max = max_failures
        self._window = window_s
        self._max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def reserve(self, keys: list[str], now: float) -> int:
        """Record an attempt for every key and return 0, or return the seconds to wait."""
        with self._lock:
            wait = 0.0
            for key in keys:
                q = self._attempts.get(key)
                if q is None:
                    continue
                while q and now - q[0] >= self._window:
                    q.popleft()
                if len(q) >= self._max:
                    wait = max(wait, self._window - (now - q[0]))
            if wait:
                return max(1, math.ceil(wait))
            for key in keys:
                self._attempts.setdefault(key, deque()).append(now)
            if len(self._attempts) > self._max_keys:
                self._sweep(now)
            return 0

    def success(self, keys: list[str]) -> None:
        with self._lock:
            for key in keys:
                self._attempts.pop(key, None)

    def size(self) -> int:
        with self._lock:
            return len(self._attempts)

    def _sweep(self, now: float) -> None:
        expired = [k for k, q in self._attempts.items() if not q or now - q[-1] >= self._window]
        for key in expired:
            del self._attempts[key]
        # Still too many live keys (a spray of distinct usernames): drop the oldest.
        if len(self._attempts) > self._max_keys:
            oldest = sorted(self._attempts, key=lambda k: self._attempts[k][-1])
            for key in oldest[: len(self._attempts) - self._max_keys]:
                del self._attempts[key]
