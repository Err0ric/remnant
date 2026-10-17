"""How much memory the server may use (D58).

The server caps its own address space at start-up so that a query asking for more memory
than the machine has fails with an error instead of getting the whole process killed.
"""

from __future__ import annotations

import os
from pathlib import Path

AUTO_SHARE = 0.75  # of the machine's or container's memory, when not configured
MIN_MB = 1024


def available_mb() -> int | None:
    """Physical memory, or the container's limit when lower. None when unknown."""
    sizes: list[int] = []
    try:
        pages, page = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page > 0:
            sizes.append(pages * page)
    except (ValueError, OSError, AttributeError):
        pass
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            text = Path(path).read_text().strip()
        except OSError:
            continue
        if text.isdigit() and int(text) < 1 << 60:  # "max" or a huge value: no limit
            sizes.append(int(text))
    return min(sizes) // (1024 * 1024) if sizes else None


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
