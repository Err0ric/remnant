"""One read position per file, not per path (ADR-0051, D250).

A text file's position is keyed by the file itself, `(source, device, inode)`, with two
content checks: a hash of the first 256 bytes and a hash of the 256 bytes before the offset.
The path is a column that says where the file was last seen, never the key, so a rename
changes only that column, two files never share a record, and one file never has two. A
record is used only when the open file matches it (`same_content`); the name is never
trusted.

EVTX files, syslog spools, Loki, and connectors keep their own positions.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import structlog

from app.ingest.sources import open_regular
from app.meta.db import MetaDB

log = structlog.get_logger(__name__)

CHECK_BYTES = 256
NOT_DRAINED = -1  # stored as the size of a file not read to its end: never a real size
COPY_FIX = "file_positions_from_checkpoints"
MAX_OWED = 1000  # files from the update still waiting to be readable
OWED_DAYS = timedelta(days=7)  # and for how long they are waited for


@dataclass(frozen=True, slots=True)
class FilePosition:
    source_id: str
    device: int
    inode: int
    path: str  # where the file was last seen (`path_key`)
    offset: int
    # Size and modified time when it was last read to its end: a file that still has both
    # is not opened (ADR-0051 row 7). `NOT_DRAINED` when more was left to read.
    size: int
    mtime_ns: int
    head: str
    tail: str
    csv_header: str | None = None
    skip_to_newline: bool = False
    updated_at: str = ""  # when it last moved; set by the store
    seen_at: str = ""  # when it was last listed or read; set by the store


def _digest(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def content_hashes(fh: BinaryIO, offset: int) -> tuple[str, str]:
    """The two checks for a position at `offset`: the start of the file (as many bytes as
    were read, at most 256, with their count) and the 256 bytes before the offset."""
    n = min(CHECK_BYTES, offset)
    fh.seek(0)
    head = f"{n}:{_digest(fh.read(n))}"
    fh.seek(max(0, offset - CHECK_BYTES))
    return head, _digest(fh.read(min(CHECK_BYTES, offset)))


def same_content(fh: BinaryIO, pos: FilePosition, size: int) -> bool:
    """Is the open file the one the position was saved for? Not when it is shorter than the
    offset (emptied in place), or when either check differs (refilled, or another file that
    was given the inode number)."""
    return pos.offset <= size and content_hashes(fh, pos.offset) == (pos.head, pos.tail)


class FilePositions:
    """The `file_positions` table."""

    def __init__(self, meta: MetaDB, clock: Callable[[], datetime]) -> None:
        self._meta = meta
        self._clock = clock

    def get(self, source_id: str, device: int, inode: int) -> FilePosition | None:
        with self._meta.connect() as con:
            row = con.execute(
                f"SELECT {_COLUMNS} FROM file_positions"  # noqa: S608  # fixed column list
                " WHERE source_id = ? AND device = ? AND inode = ?",
                (source_id, _signed(device), _signed(inode)),
            ).fetchone()
        return None if row is None else _position(source_id, row)

    def on_other_devices(self, source_id: str, inode: int) -> list[FilePosition]:
        """Records for this inode number when none has the file's own device number. A
        device number is not stable across a restart or a remount (LVM, NVMe, NFS, a
        container bind mount), so the file may be one of these, under any name (it may
        have been rotated meanwhile); the caller checks its content."""
        with self._meta.connect() as con:
            rows = con.execute(
                f"SELECT {_COLUMNS} FROM file_positions"  # noqa: S608  # fixed column list
                " WHERE source_id = ? AND inode = ?",
                (source_id, _signed(inode)),
            ).fetchall()
        return [_position(source_id, r) for r in rows]

    def save(
        self,
        pos: FilePosition,
        con: sqlite3.Connection | None = None,
        replaces: FilePosition | None = None,
        now: str | None = None,
    ) -> None:
        """With `con`, inside the caller's transaction: the watcher saves the position and
        the older `checkpoints` row together, or neither. `replaces`: the record the file
        had under another device number, removed in the same transaction, so one file
        never has two. `now`: the time the caller stamps its `checkpoints` row with, so the
        two rows of one save never differ (a newer `checkpoints` row means an older version
        wrote it)."""
        if con is None:
            with self._meta.connect() as own:
                self.save(pos, own, replaces, now)
            return
        now = now or self._clock().isoformat()
        con.execute(
            "INSERT INTO file_positions (source_id, device, inode, path, offset, size,"
            " mtime_ns, head, tail, csv_header, skip_to_newline, updated_at, seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (source_id, device, inode) DO UPDATE SET path = excluded.path,"
            " offset = excluded.offset, size = excluded.size, mtime_ns = excluded.mtime_ns,"
            " head = excluded.head, tail = excluded.tail, csv_header = excluded.csv_header,"
            " skip_to_newline = excluded.skip_to_newline, updated_at = excluded.updated_at,"
            " seen_at = excluded.seen_at",
            (
                pos.source_id, _signed(pos.device), _signed(pos.inode), pos.path, pos.offset,
                pos.size, pos.mtime_ns, pos.head, pos.tail, pos.csv_header,
                int(pos.skip_to_newline), now, now,
            ),
        )  # fmt: skip
        if replaces is not None and replaces.device != pos.device:
            con.execute(
                "DELETE FROM file_positions WHERE source_id = ? AND device = ? AND inode = ?",
                (replaces.source_id, _signed(replaces.device), _signed(replaces.inode)),
            )
        # A record at offset 0 matches any content, so one left under another device number
        # (an empty file before the number changed) would send this file back to its start
        # if the number ever returned: it goes too.
        con.execute(
            "DELETE FROM file_positions WHERE source_id = ? AND inode = ? AND device <> ?"
            " AND offset = 0",
            (pos.source_id, _signed(pos.inode), _signed(pos.device)),
        )

    def seen_at(self, pos: FilePosition, path: str) -> None:
        """An idle file was listed: note where, without opening it."""
        with self._meta.connect() as con:
            con.execute(
                "UPDATE file_positions SET path = ?, seen_at = ?"
                " WHERE source_id = ? AND device = ? AND inode = ?",
                (path, self._clock().isoformat(), pos.source_id, _signed(pos.device),
                 _signed(pos.inode)),
            )  # fmt: skip

    def take_checkpoints(
        self, text_sources: set[str], roots: list[Path], start: bool
    ) -> set[tuple[str, str]]:
        """Take over what the path-keyed `checkpoints` table knows and this one does not
        (ADR-0051 row 10), so nothing is read twice. At each start (`start`) every row is
        looked at; later calls look only at the files still owed from the update. Returns
        the (source, path) pairs still owed: the caller calls again before it reads one.

        - The update: every row of a text source whose path still has the recorded inode
          becomes a position. A file that is missing or cannot be opened then (a folder
          not mounted yet, a permission) is owed: tried again later until it can be read
          or is another file, for `OWED_DAYS` at most. Rows of files deleted long ago are
          owed too (they cannot be told from a folder that is not mounted); at most
          `MAX_OWED` are kept, the most recently read first.
        - After going back a version and updating again: the older version moved only
          `checkpoints`, so a row newer than the file's position (or newer than every
          position, for a file first seen by the older version) is taken.

        Other rows are left; their files start at 0 when listed, as a file with another
        inode did before."""
        with self._meta.connect() as con:
            fix = con.execute(
                "SELECT value, applied_at FROM one_time_fixes WHERE fix_id = ?", (COPY_FIX,)
            ).fetchone()
        first = fix is None
        before = [tuple(k) for k in json.loads(fix["value"] or "[]")] if fix else []
        if fix and self._clock() - datetime.fromisoformat(fix["applied_at"]) > OWED_DAYS:
            before = []  # long gone: such a file is new when it appears
        waiting = set(before)
        if not (start or waiting):
            if fix and fix["value"] not in (None, "[]"):
                self._owed(first, [])
            return set()
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT source_id, path, inode, offset, csv_header, skip_to_newline, updated_at"
                " FROM checkpoints WHERE file_signature IS NULL ORDER BY updated_at DESC"
            ).fetchall()
            newest = con.execute("SELECT max(updated_at) FROM file_positions").fetchone()[0] or ""
        still: list[tuple[str, str]] = []
        taken = 0
        for r in rows:
            sid, key = r["source_id"], r["path"]
            owed = first or (sid, key) in waiting
            if sid not in text_sources or not (start or owed):
                continue
            try:
                with open_regular(_path(key), roots) as fh:
                    info = os.fstat(fh.fileno())
                    if info.st_ino != r["inode"] or r["offset"] > info.st_size:
                        continue  # another file has the name now
                    has = self.get(sid, info.st_dev, info.st_ino)
                    moved = None
                    if has is None:  # known under another device number, by its content?
                        moved = has = next(
                            (p for p in self.on_other_devices(sid, info.st_ino)
                             if p.offset and same_content(fh, p, info.st_size)),
                            None,
                        )  # fmt: skip
                    if has is None:
                        take = owed or r["updated_at"] > newest
                    else:
                        take = r["updated_at"] > has.updated_at and r["offset"] != has.offset
                    if not take:
                        continue
                    head, tail = content_hashes(fh, r["offset"])
            except OSError:
                if owed and len(still) < MAX_OWED:
                    still.append((sid, key))  # missing or unreadable now: owed
                continue
            self.save(
                FilePosition(
                    sid, info.st_dev, info.st_ino, key, r["offset"], NOT_DRAINED, 0, head, tail,
                    r["csv_header"], bool(r["skip_to_newline"]),
                ),
                replaces=moved,
            )  # fmt: skip
            taken += 1
        if first or still != before:
            self._owed(first, still)
        if taken or first:
            log.info("ingest.positions_taken", rows=taken, waiting=len(still), first=first)
        return set(still)

    def _owed(self, first: bool, still: list[tuple[str, str]]) -> None:
        """Record the files still owed; the first time, also when the update ran."""
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO one_time_fixes (fix_id, applied_at, changed, value)"
                " VALUES (?, ?, 0, ?) ON CONFLICT (fix_id) DO UPDATE SET value = excluded.value",
                (COPY_FIX, self._clock().isoformat(), json.dumps(still)),
            )

    def at_path(self, source_id: str, path: str) -> list[FilePosition]:
        """Every record last seen under this name: the file that has it now, and the
        files that had it before a rotation, until the sweep removes them."""
        with self._meta.connect() as con:
            rows = con.execute(
                f"SELECT {_COLUMNS} FROM file_positions"  # noqa: S608  # fixed column list
                " WHERE source_id = ? AND path = ?",
                (source_id, path),
            ).fetchall()
        return [_position(source_id, r) for r in rows]

    def sweep(self, before: datetime, sources: set[str]) -> int:
        """Remove the records of files that are gone and were not listed or read since
        `before` (ADR-0051 row 8: 30 days), for `sources` only: the ones being listed.
        Without the sweep records stay for ever, which is what lets a reused inode number
        find one. A record is removed only when its file is known to be gone
        (`file_is_gone`): a share that is not mounted for a month, or a folder that is
        away, keeps its records, or its files would all be read again when it returns.
        Returns the records removed."""
        removed = 0
        for sid in sorted(sources):
            with self._meta.connect() as con:
                rows = con.execute(
                    f"SELECT {_COLUMNS} FROM file_positions"  # noqa: S608  # fixed column list
                    " WHERE source_id = ? AND seen_at < ?",
                    (sid, before.isoformat()),
                ).fetchall()
            gone = [p for p in (_position(sid, r) for r in rows) if file_is_gone(p)]
            with self._meta.connect() as con:
                for p in gone:
                    con.execute(
                        "DELETE FROM file_positions WHERE source_id = ? AND device = ?"
                        " AND inode = ? AND seen_at < ?",
                        (sid, _signed(p.device), _signed(p.inode), before.isoformat()),
                    )
            removed += len(gone)
        return removed

    def drop_path(self, source_id: str, path: str) -> None:
        """A spool file ingest deleted after reading it: its record goes with it."""
        with self._meta.connect() as con:
            con.execute(
                "DELETE FROM file_positions WHERE source_id = ? AND path = ?", (source_id, path)
            )


_COLUMNS = (
    "device, inode, path, offset, size, mtime_ns, head, tail, csv_header, skip_to_newline,"
    " updated_at, seen_at"
)


def _position(source_id: str, row: sqlite3.Row) -> FilePosition:
    return FilePosition(
        source_id, _unsigned(row["device"]), _unsigned(row["inode"]), row["path"], row["offset"],
        row["size"], row["mtime_ns"], row["head"], row["tail"], row["csv_header"],
        bool(row["skip_to_newline"]), row["updated_at"], row["seen_at"],
    )  # fmt: skip


def file_is_gone(pos: FilePosition) -> bool:
    """Is the file a record stands for known to be gone? Yes when the folder it was last
    seen in is there, on the device the file was on, and has no file of that name, or
    another file under it. A folder that is absent, or on another device (the empty mount
    point of a share that is not mounted), says nothing about the file: not gone. So does
    a device number that changed since the record was written (D251)."""
    path = _path(pos.path)
    try:
        if os.stat(path.parent).st_dev != pos.device:
            return False
        there = os.stat(path)
    except FileNotFoundError:
        return path.parent.is_dir()
    except OSError:
        return False
    return (there.st_dev, there.st_ino) != (pos.device, pos.inode)


def _path(key: str) -> Path:
    """The path a `path_key` stands for."""
    if key.startswith("fsbytes:"):
        return Path(os.fsdecode(bytes.fromhex(key[len("fsbytes:") :])))
    return Path(key)


def _signed(n: int) -> int:
    """SQLite integers are signed 64-bit; a device or inode number may use the top bit."""
    return n - (1 << 64) if n >= 1 << 63 else n


def _unsigned(n: int) -> int:
    return n + (1 << 64) if n < 0 else n
