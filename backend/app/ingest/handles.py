"""The files the watcher keeps open to follow a rename (ADR-0051 row 3, D250).

A name can be given to another file between two passes (logrotate `create`), and what was
written to the old file just before is then reachable only through a handle opened earlier.
The watcher therefore keeps the handle of each text file it read from in the last 5 minutes,
at most `MAX_HANDLES` of them, the one read longest ago closed first. A handle is the file
itself, wherever it was moved, also when it is deleted. Handles are in memory only: after a
restart there are none (ADR-0051 row 4).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

MAX_HANDLES = 256
KEEP = timedelta(minutes=5)  # after the last read, and after a rename is seen
# A renamed file is held this long after it was first read to its end (owner, 2026-11-13;
# D252): a program keeps writing to it until it is told to reopen its log.
LINGER = timedelta(seconds=30)

FileId = tuple[str, int, int]  # source, device, inode


@dataclass(slots=True)
class Held:
    fh: BinaryIO
    path: Path  # the name it was read under
    key: str  # that name as a `path_key`
    read_at: datetime
    gone_at: datetime | None = None  # when the name was first seen to point elsewhere
    ended_at: datetime | None = None  # when a renamed file was first read to its end


class HeldHandles:
    def __init__(self) -> None:
        self._held: dict[FileId, Held] = {}

    def __len__(self) -> int:
        return len(self._held)

    def get(self, file: FileId) -> Held | None:
        return self._held.get(file)

    def items(self, source_id: str) -> list[tuple[FileId, Held]]:
        return [(f, h) for f, h in self._held.items() if f[0] == source_id]

    def of(self, source_id: str) -> list[Held]:
        return [h for _, h in self.items(source_id)]

    def keep(self, file: FileId, fh: BinaryIO, path: Path, key: str, now: datetime) -> None:
        """Hold `fh` for this file, in place of an older handle to it; over the limit, the
        handles read longest ago are closed."""
        old = self._held.pop(file, None)
        if old is not None and old.fh is not fh:
            _close(old.fh)
        self._held[file] = Held(fh, path, key, now)
        over = len(self._held) - MAX_HANDLES
        if over > 0:
            for f, _ in sorted(self._held.items(), key=lambda kv: kv[1].read_at)[:over]:
                self.drop(f)

    def drop(self, file: FileId) -> None:
        held = self._held.pop(file, None)
        if held is not None:
            _close(held.fh)

    def expire(self, now: datetime, sources: set[str]) -> None:
        """Close what was not read from for `KEEP`, and the handles of sources that are gone
        or turned off. A renamed file's handle is closed by the watcher, which stores its
        last line first (`closing`)."""
        for file, held in list(self._held.items()):
            if file[0] not in sources or (held.gone_at is None and now - held.read_at >= KEEP):
                self.drop(file)


def closing(held: Held, now: datetime) -> bool:
    """Is it time to close a renamed file's handle? `LINGER` after it was first read to
    its end, and `KEEP` after the rename was seen at the latest."""
    if held.gone_at is not None and now - held.gone_at >= KEEP:
        return True
    return held.ended_at is not None and now - held.ended_at >= LINGER


def _close(fh: BinaryIO) -> None:
    with contextlib.suppress(OSError):
        fh.close()
