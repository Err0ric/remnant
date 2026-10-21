"""Lake files that survive a power cut, and a place for ones that did not.

A file is written under a temporary name, flushed to disk, renamed into place, and the
folder flushed, so after a crash a published file is complete or absent. A file found
empty or unreadable anyway (written by an older version, or a disk fault) is moved to
`<data>/quarantine/<source>/<day>/`, outside what queries read, and never deleted: an
administrator decides what to do with it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from app.ingest.integrity import LakeEvents

log = structlog.get_logger()


def _fsync_dir(folder: Path) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:  # some platforms cannot open folders; the rename still happened
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(table: pa.Table, final: Path) -> Path:
    """Write `table` to `final` so a crash leaves either the whole file or nothing."""
    tmp = final.parent / f".{final.name}.tmp"
    pq.write_table(table, tmp, compression="zstd")
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, final)
    _fsync_dir(final.parent)
    return final


def quarantine_dir(lake: Path) -> Path:
    return lake.parent / "quarantine"


def quarantine(
    lake: Path, path: Path, reason: str, events: LakeEvents | None = None
) -> Path | None:
    """Move a damaged file out of the lake, keeping its source and day folders. A file the
    integrity ledger recorded with other content is left in place (None), so verification
    reports it as changed instead of a clean quarantine hiding the edit."""
    rel = path.relative_to(lake)
    if events is not None and not events.removed([path], f"quarantine: {reason[:120]}"):
        log.warning("lake.quarantine_skipped_changed", file=str(rel))
        return None
    dest = quarantine_dir(lake) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dest)
    log.warning("lake.quarantined", file=str(rel), reason=reason[:160])
    return dest


def readable(path: Path) -> str | None:
    """None when the file's footer reads, else why not."""
    try:
        if path.stat().st_size == 0:
            return "empty file"
        pq.read_metadata(path)
    except Exception as exc:  # pyarrow raises several types for damaged files
        return f"{type(exc).__name__}: {exc}"
    return None


def sweep(lake: Path, full: bool = False, events: LakeEvents | None = None) -> int:
    """Quarantine empty part files (and, with `full`, any whose footer does not read).
    Returns how many were moved."""
    if not lake.is_dir():
        return 0
    moved = 0
    for path in lake.glob("source=*/day=*/part-*.parquet"):
        if path.is_symlink() or not path.is_file():
            continue
        if path.parent.is_symlink() or path.parent.parent.is_symlink():
            continue  # a linked folder points outside the lake: never move files from it
        if not full and path.stat().st_size > 0:
            continue
        why = readable(path)
        if why is not None and quarantine(lake, path, why, events) is not None:
            moved += 1
    return moved


def quarantined_count(lake: Path) -> int:
    folder = quarantine_dir(lake)
    return sum(1 for _ in folder.rglob("*.parquet")) if folder.is_dir() else 0
