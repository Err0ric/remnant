"""One queue per model provider (ADR-0028, D78).

Small local model servers run one inference at a time and answer "busy" otherwise. The
gate takes a slot here around each provider call, first come first served, and waits at
most the provider's budget. A caller that goes away (browser closed, Cancel) leaves the
queue at once: API handlers set `CANCELLED` for the thread that runs the gate.
"""

from __future__ import annotations

import itertools
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

DEFAULT_WAIT_S = 120
LOCAL_DEFAULT_SLOTS = 1
POLL_S = 0.5

# Set by API handlers (watch_disconnect); copied into the worker thread with the context.
CANCELLED: ContextVar[Callable[[], bool] | None] = ContextVar("llm_cancelled", default=None)


class WaitCancelledError(Exception):
    """The caller went away while waiting."""


class WaitTimedOutError(Exception):
    """No slot within the wait budget."""


@dataclass(frozen=True, slots=True)
class QueueStatus:
    limit: int | None
    running: int
    waiting: int


class _Slots:
    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.running = 0
        self.waiting: deque[int] = deque()


class ProviderQueues:
    """Slots per provider. `limit` None means no queue (cloud by default)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[str, _Slots] = {}
        self._limits: dict[str, int | None] = {}
        self._tickets = itertools.count()

    def _get(self, provider_id: str) -> _Slots:
        with self._lock:
            return self._slots.setdefault(provider_id, _Slots())

    def acquire(
        self,
        provider_id: str,
        limit: int | None,
        deadline: float,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Wait for a slot until `deadline` (time.monotonic). Raises WaitTimedOutError or
        WaitCancelledError."""
        with self._lock:
            self._limits[provider_id] = limit
        s = self._get(provider_id)
        with s.cond:
            if limit is None:
                s.running += 1
                return
            ticket = next(self._tickets)
            s.waiting.append(ticket)
            try:
                while not (s.waiting[0] == ticket and s.running < limit):
                    if cancelled is not None and cancelled():
                        raise WaitCancelledError
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise WaitTimedOutError
                    s.cond.wait(min(POLL_S, left))
            finally:
                s.waiting.remove(ticket)
                s.cond.notify_all()
            s.running += 1

    def release(self, provider_id: str) -> None:
        s = self._get(provider_id)
        with s.cond:
            s.running = max(0, s.running - 1)
            s.cond.notify_all()

    def status(self, provider_id: str) -> QueueStatus:
        s = self._get(provider_id)
        with self._lock:
            limit = self._limits.get(provider_id)
        with s.cond:
            return QueueStatus(limit=limit, running=s.running, waiting=len(s.waiting))

    def busy(self, provider_id: str) -> bool:
        """A call of ours holds a slot: a refusal now means occupied, not down."""
        return self.status(provider_id).running > 0


def sleep_until(seconds: float, deadline: float, cancelled: Callable[[], bool] | None) -> None:
    """Back off between busy retries, in short steps so a cancel is seen quickly."""
    end = min(time.monotonic() + seconds, deadline)
    while (left := end - time.monotonic()) > 0:
        if cancelled is not None and cancelled():
            raise WaitCancelledError
        time.sleep(min(POLL_S, left))


# One set of queues for the process (ADR-0028 row 11): the gate and the health check share it.
QUEUES = ProviderQueues()
_LAST_OK: dict[str, float] = {}
RECENT_OK_S = 600


def health_ok(provider_id: str) -> None:
    _LAST_OK[provider_id] = time.monotonic()


def recently_healthy(provider_id: str) -> bool:
    seen = _LAST_OK.get(provider_id)
    return seen is not None and time.monotonic() - seen < RECENT_OK_S


def slots_for(max_concurrent: int | None, local: bool) -> int | None:
    """The provider's setting, or the default: one at a time for local, no queue for cloud."""
    if max_concurrent:
        return max_concurrent
    return LOCAL_DEFAULT_SLOTS if local else None


def backoff_s(attempt: int, retry_after: int | None) -> float:
    """1 s, 2 s, 4 s ... capped at 15 s, with jitter; Retry-After wins when given."""
    if retry_after is not None:
        return float(retry_after)
    return min(15.0, 2.0 ** (attempt - 1)) * random.uniform(0.8, 1.2)  # noqa: S311  # jitter, not security
