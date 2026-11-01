"""Query memory as a shared budget (D58, D80, updated 2026-11-01).

Every query opens its own DuckDB instance with its own `memory_limit`, so the limits add
up. The ledger keeps their sum under the budget: one share (budget / (queries at once +
1)) stays free for the server itself, page sections reserve one share each, and Search,
export, and saved or scheduled searches take what is free while leaving two shares for
page sections. Alone, a search on a 4096 MB budget with 4 queries at once gets 1638 MB;
with others running it falls back to one share. Shares come from the budget, so raising
the budget grows both.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.errors import QueryBusyError

MIN_SHARE_MB = 256
PAGE_ROOM = 2  # shares a large query leaves free for page sections


@dataclass(frozen=True, slots=True)
class Grant:
    mb: int
    large: bool  # asked for more than a share
    fell_back: bool  # asked for more but got one share


class MemoryLedger:
    def __init__(self, budget_mb: int, at_once: int) -> None:
        self.share = max(MIN_SHARE_MB, budget_mb // (max(1, at_once) + 1))
        # What queries may hold together: the budget less one share for the server.
        self.capacity = max(self.share, budget_mb - self.share)
        self.large_max = max(self.share, self.capacity - PAGE_ROOM * self.share)
        self._used = 0
        self._cond = threading.Condition()

    @property
    def used(self) -> int:
        return self._used

    def take(self, large: bool, wait_s: float) -> Grant:
        deadline = time.monotonic() + wait_s
        with self._cond:
            while self.capacity - self._used < self.share:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise QueryBusyError(
                        "The server is using all the query memory it allows; try again in a moment"
                    )
                self._cond.wait(left)
            free = self.capacity - self._used
            mb = self.share
            if large:
                mb = max(self.share, min(self.large_max, free - PAGE_ROOM * self.share))
            self._used += mb
            return Grant(mb, large, large and mb == self.share < self.large_max)

    def give(self, grant: Grant) -> None:
        with self._cond:
            self._used -= grant.mb
            self._cond.notify_all()
