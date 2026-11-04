"""Says when a request waited for a worker thread (owner, 2026-11-03: at the UTC day
rollover a 4 ms request took 13 s, and nothing in the log said why; D193).

Every request-pool job (route handlers' and dependencies' blocking work, and anything sent
with `run_in_threadpool`) goes through `anyio.to_thread.run_sync` on the default limiter.
`install` wraps that call: it notes when a job was handed over and when a thread started
it, and keeps the jobs running now by name. A job that waited more than `WAIT_WARN_S` is
logged with its own name, how long it waited, how many jobs were running, and the jobs
holding the pool when its wait crossed `WAIT_WARN_S` (a watcher thread looks every
`TICK_S`), longest first. Holders are taken then, not when a thread finally starts the job:
by that time the jobs that kept it waiting may all have finished at once. Jobs on their own
limiter (sign-in checks, the rollup builds) are left alone.
"""

from __future__ import annotations

import functools
import itertools
import threading
import time
from collections.abc import Callable
from typing import Any

import anyio.to_thread
import structlog

log = structlog.get_logger(__name__)

WAIT_WARN_S = 2.0
TICK_S = 0.25
_lock = threading.Lock()
_running: dict[int, tuple[str, float]] = {}
# Jobs handed over and not started yet: when handed over, and the holders seen once the
# wait crossed WAIT_WARN_S (None until then).
_waiting: dict[int, tuple[float, list[tuple[str, float]] | None]] = {}
_ids = itertools.count()
_installed = False


def job_name(fn: Callable[..., Any]) -> str:
    """`module.function` for a function or a partial of one; no arguments, so no data."""
    while isinstance(fn, functools.partial):
        fn = fn.func
    name = getattr(fn, "__qualname__", None) or type(fn).__name__
    module = getattr(fn, "__module__", "") or ""
    return f"{module.rsplit('.', 1)[-1]}.{name}" if module else str(name)


def busy() -> int:
    with _lock:
        return len(_running)


def holders(now: float, top: int = 5) -> list[tuple[str, float]]:
    """The jobs running on the pool now, longest first, with seconds so far."""
    with _lock:
        jobs = list(_running.values())
    return [(n, round(now - t, 1)) for n, t in sorted(jobs, key=lambda j: j[1])[:top]]


def check(now: float) -> None:
    """Note the holders for every job whose wait has just crossed WAIT_WARN_S."""
    with _lock:
        due = [k for k, (h, seen) in _waiting.items() if seen is None and now - h > WAIT_WARN_S]
    if not due:
        return
    snapshot = holders(now)
    with _lock:
        for k in due:
            if k in _waiting:
                _waiting[k] = (_waiting[k][0], snapshot)


def _watch() -> None:
    while True:
        time.sleep(TICK_S)
        check(time.monotonic())


def _watched(fn: Callable[..., Any], handed: float, key: int) -> Callable[..., Any]:
    name = job_name(fn)
    with _lock:
        _waiting[key] = (handed, None)

    def run(*args: Any) -> Any:
        started = time.monotonic()
        waited = started - handed
        with _lock:
            seen = _waiting.pop(key, (handed, None))[1]
        if waited > WAIT_WARN_S:
            log.warning(
                "pool.wait", job=name, waited_s=round(waited, 1), running=busy(),
                holders=seen if seen is not None else holders(started),
            )  # fmt: skip
        with _lock:
            _running[key] = (name, started)
        try:
            return fn(*args)
        finally:
            with _lock:
                _running.pop(key, None)

    return run


def install() -> None:
    """Wrap the request pool once per process."""
    global _installed
    if _installed:
        return
    original = anyio.to_thread.run_sync

    async def run_sync(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("limiter") is not None:
            return await original(func, *args, **kwargs)
        key = next(_ids)
        try:
            return await original(_watched(func, time.monotonic(), key), *args, **kwargs)
        finally:
            with _lock:  # a job cancelled before it started never ran `run`
                _waiting.pop(key, None)

    anyio.to_thread.run_sync = run_sync  # type: ignore[assignment]  # same call signature
    threading.Thread(target=_watch, name="pool-watch", daemon=True).start()
    _installed = True
