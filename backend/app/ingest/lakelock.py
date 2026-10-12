"""One lock for jobs that rewrite or delete lake files (compaction, retention) and for
backups, so a backup never copies a partition halfway through a merge.

Ingest does not take it: new files appear by atomic rename, so a backup either has a
new file or does not. The lock is advisory (`flock`) and is released if the process dies.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover  # Windows: no flock; single-process use only
    fcntl = None  # type: ignore[assignment]  # optional module, checked before use

LOCK_NAME = ".maintenance.lock"


@contextmanager
def lake_lock(lake_dir: Path, wait: bool = True) -> Iterator[bool]:
    """Hold the lake lock. Yields False (without the lock) when `wait` is off and it is
    busy, so a scheduled job can skip a round instead of queueing behind a backup."""
    lake_dir.mkdir(parents=True, exist_ok=True)
    with open(lake_dir / LOCK_NAME, "a+b") as fh:
        if fcntl is None:
            yield True
            return
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
