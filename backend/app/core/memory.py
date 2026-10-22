"""How much memory the server may use (D58).

The server caps its own address space at start-up so that a query asking for more memory
than the machine has fails with an error instead of getting the whole process killed.
"""

from __future__ import annotations

import os
from pathlib import Path

AUTO_SHARE = 0.75  # of the machine's or container's memory, when not configured
MIN_MB = 1024


UNLIMITED = 1 << 60  # cgroup v1 reports "no limit" as a value near 2**63


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _meminfo_bytes(root: Path) -> int | None:
    """MemTotal from /proc/meminfo. LXCFS virtualizes it inside LXC containers, where
    sysconf still reports the host's memory (install finding, 2026-10-21)."""
    text = _read(root / "proc" / "meminfo")
    for line in (text or "").splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024  # kB
    return None


def _cgroup_limits(root: Path) -> list[tuple[int, str]]:
    """Limits for this process's own cgroup (v2 and v1), plus the cgroup root files."""
    dirs: list[tuple[Path, str]] = []
    for line in (_read(root / "proc" / "self" / "cgroup") or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        rel = parts[2].strip().lstrip("/")
        if parts[1] == "":
            dirs.append((root / "sys/fs/cgroup" / rel, "memory.max"))
        elif "memory" in parts[1].split(","):
            dirs.append((root / "sys/fs/cgroup/memory" / rel, "memory.limit_in_bytes"))
    dirs += [
        (root / "sys/fs/cgroup", "memory.max"),
        (root / "sys/fs/cgroup/memory", "memory.limit_in_bytes"),
    ]
    out: list[tuple[int, str]] = []
    for d, name in dirs:
        text = (_read(d / name) or "").strip()
        if text.isdigit() and 0 < int(text) < UNLIMITED:  # "max" means no limit here
            out.append((int(text), "/" + str((d / name).relative_to(root))))
    return out


def _sysconf_bytes() -> int | None:
    try:
        pages, page = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None
    return pages * page if pages > 0 and page > 0 else None


def detect(root: Path = Path("/")) -> tuple[int, str] | None:
    """(MB, source) for the smallest of: /proc/meminfo, cgroup limits, sysconf.
    None when nothing could be read. `root` is injectable for tests."""
    sizes: list[tuple[int, str]] = []
    mem = _meminfo_bytes(root)
    if mem:
        sizes.append((mem, "/proc/meminfo"))
    sizes += _cgroup_limits(root)
    phys = _sysconf_bytes()
    if phys:
        sizes.append((phys, "sysconf"))
    if not sizes:
        return None
    size, source = min(sizes)
    return size // (1024 * 1024), source


def available_mb() -> int | None:
    """Physical memory, or the container's limit when lower. None when unknown."""
    found = detect()
    return found[0] if found else None


def budget_note(configured: int) -> str:
    """Startup line source, e.g. 'auto, 75% of 8192 MB from /proc/meminfo'."""
    if configured:
        return "server.memory_limit_mb"
    found = detect()
    if found is None:
        return "auto"
    return f"auto, {round(AUTO_SHARE * 100)}% of {found[0]} MB from {found[1]}"


def server_budget_mb(configured: int) -> int | None:
    """The address-space cap in MB: the configured value, or 75% of what is available.
    None means no cap (unknown size, or below the minimum the server needs)."""
    if configured:
        return max(configured, MIN_MB)
    total = available_mb()
    if total is None:
        return None
    budget = int(total * AUTO_SHARE)
    return budget if budget >= MIN_MB else None
