"""How many threads queries may start (D79).

Each DuckDB connection starts its own worker threads, sized by default from the core count
the operating system reports. Inside a container that is the host's count, so a burst of
queries on a small LXC can hit the host's process limit. The server sizes queries from the
CPUs it can actually use and caps how many run at once.
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

AUTO_MAX_THREADS = 4  # per query, when not configured
AUTO_MAX_QUERIES = 4  # at once, when not configured
WORKER_POOL = 40  # the async framework's default worker thread limit
STACK_MB = 8  # default thread stack reservation, counted by the address-space cap
ARENA_MB = 256  # allocator arenas for the server's own threads, capped at start-up


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _cgroup_cpus(root: Path) -> float | None:
    """CPU quota from cgroup v2 (cpu.max) or v1 (cfs quota and period), in CPUs."""
    v2 = (_read(root / "sys/fs/cgroup/cpu.max") or "").split()
    if len(v2) == 2 and v2[0] != "max" and v2[0].isdigit() and v2[1].isdigit() and int(v2[1]):
        return int(v2[0]) / int(v2[1])
    quota = (_read(root / "sys/fs/cgroup/cpu/cpu.cfs_quota_us") or "").strip()
    period = (_read(root / "sys/fs/cgroup/cpu/cpu.cfs_period_us") or "").strip()
    if quota.isdigit() and period.isdigit() and int(period) and int(quota) > 0:
        return int(quota) / int(period)
    return None


def usable_cpus(root: Path = Path("/")) -> int:
    """CPUs this process may run on: affinity, then any cgroup quota. Never below 1."""
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    quota = _cgroup_cpus(root)
    if quota is not None:
        cpus = min(cpus, max(1, math.ceil(quota)))
    return max(1, cpus)


@dataclass(frozen=True)
class QueryThreads:
    per_query: int
    at_once: int

    @property
    def peak(self) -> int:
        """Threads queries can add at the worst moment: the framework's worker pool (each
        waiting query holds one), plus per running query its extra DuckDB workers and one
        timeout timer."""
        return WORKER_POOL + self.busy + 1  # + the rollup build's one DuckDB thread

    @property
    def busy(self) -> int:
        """DuckDB worker threads that can be running at once for page queries: the CPU
        load. The worker pool in `peak` is mostly requests waiting on a slot or on I/O,
        which count against a pids or address-space limit but not against the cores."""
        return self.at_once * self.per_query

    @property
    def headroom_mb(self) -> int:
        """Address space those threads reserve, added on top of the memory cap so a burst
        cannot fail to start a thread for want of address space (lab finding, D79)."""
        return self.peak * STACK_MB + ARENA_MB


def query_threads(threads: int, max_queries: int, cpus: int | None = None) -> QueryThreads:
    """Configured values, or automatic ones (0) from the usable CPUs."""
    cpus = usable_cpus() if cpus is None else cpus
    # Automatic: as many queries at once as there are cores (at most 4), and threads per
    # query so all of them together use about twice the cores. A page sends several
    # queries at once; more threads than that only make them wait on each other (owner,
    # 2026-10-31: three Dashboard sections in parallel were each slower on 4 vCPU).
    at_once = max_queries or max(2, min(AUTO_MAX_QUERIES, cpus))
    per_query = threads or max(1, min(AUTO_MAX_THREADS, cpus // at_once * 2))
    return QueryThreads(per_query=per_query, at_once=at_once)


def cap_allocator_arenas(arenas: int = 4) -> str:
    """glibc reserves 64 MB of address space per arena, up to eight per core. Leaves an
    operator's MALLOC_ARENA_MAX alone (glibc applied it at start) and otherwise caps the
    arenas. Best effort, glibc only. Returns the startup line's wording."""
    # glibc's own variable, read for the log line only; app settings stay in AppConfig.
    preset = os.environ.get("MALLOC_ARENA_MAX", "").strip()
    if preset:
        return f"{preset} (MALLOC_ARENA_MAX)"
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        if libc.mallopt(-8, arenas) != 1:  # M_ARENA_MAX; returns 1 on success
            return "glibc default"
    except (OSError, AttributeError):
        return "glibc default"
    return str(arenas)


BACKGROUND_NICE = 10  # rollup builds yield the CPU to page requests


def run_low[T](fn: Callable[[], T]) -> T:
    """Run `fn` on a fresh thread at lower CPU priority and wait for it. DuckDB's worker
    threads start from that thread, so they inherit the priority; the shared worker pool
    is never lowered (a lowered thread cannot raise itself back without privileges)."""
    out: list[T] = []
    err: list[BaseException] = []

    def work() -> None:
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), BACKGROUND_NICE)
        except (AttributeError, OSError):
            pass  # not Linux, or not allowed: run at normal priority
        try:
            out.append(fn())
        except BaseException as exc:  # handed back to the caller's thread
            err.append(exc)

    t = threading.Thread(target=work, name="rollup-build", daemon=True)
    t.start()
    t.join()
    if err:
        raise err[0]
    return out[0]
