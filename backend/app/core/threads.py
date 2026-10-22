"""How many threads queries may start (D79).

Each DuckDB connection starts its own worker threads, sized by default from the core count
the operating system reports. Inside a container that is the host's count, so a burst of
queries on a small LXC can hit the host's process limit. The server sizes queries from the
CPUs it can actually use and caps how many run at once.
"""

from __future__ import annotations

import math
import os
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
        return WORKER_POOL + self.at_once * self.per_query

    @property
    def headroom_mb(self) -> int:
        """Address space those threads reserve, added on top of the memory cap so a burst
        cannot fail to start a thread for want of address space (lab finding, D79)."""
        return self.peak * STACK_MB + ARENA_MB


def query_threads(threads: int, max_queries: int, cpus: int | None = None) -> QueryThreads:
    """Configured values, or automatic ones (0) from the usable CPUs."""
    cpus = usable_cpus() if cpus is None else cpus
    return QueryThreads(
        per_query=threads or min(AUTO_MAX_THREADS, cpus),
        at_once=max_queries or AUTO_MAX_QUERIES,
    )


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
