"""Which part files of a lake day folder a new read may use (owner, 2026-11-03: AI Watch
failed every hour with "Cannot open file ... part-....parquet": compaction deleted files a
running 7-day DNS read had already listed).

Compaction no longer deletes the files it merges. It retires them: they stay where they
are, so a read that listed them still opens them, and `_retired.json` in the folder names
them, so a new read leaves them out. A later compaction pass deletes a retired file once
`RETIRE_GRACE_S` has passed (far longer than any query may run) and records the removal
in the integrity ledger then (ADR-0022), not before.

While a merge is being published, its manifest (`<output>.compact.json`) names the output
and its inputs. Once the output file is in the folder, the inputs are left out even before
they are retired, so no read counts both. A read takes the folder's state as manifests,
then the retired list, then the file listing, then the manifests again, and starts over if
they changed in between, so it never sees a step of a merge half done.

Every reader of lake part files that must not double count (the engine's `events`, the
rollup builds' file lists, compaction itself) lists them through `visible`.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

PART_GLOB = "part-*.parquet"
RETIRED = "_retired.json"
MANIFEST_SUFFIX = ".compact.json"
# Longer than any query may run (the longest limit is 120 s), with room to spare.
RETIRE_GRACE_S = 1800.0
_NAME = re.compile(r"part-[A-Za-z0-9_-]+\.parquet")


def _names(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and _NAME.fullmatch(v)]


def manifests(day_dir: Path) -> dict[str, list[str]]:
    """Merges in progress: output name -> its inputs."""
    out: dict[str, list[str]] = {}
    for m in sorted(day_dir.glob(f"*{MANIFEST_SUFFIX}")):
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        output = data.get("output")
        if isinstance(output, str) and _NAME.fullmatch(output):
            out[output] = _names(data.get("inputs"))
    return out


def retired(day_dir: Path) -> dict[str, dict[str, str]]:
    """Retired files: name -> {"at": ISO time, "into": the merged file}."""
    try:
        data = json.loads((day_dir / RETIRED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: v
        for k, v in data.items()
        if _NAME.fullmatch(k) and isinstance(v, dict) and isinstance(v.get("at"), str)
    }


def visible(day_dir: Path) -> list[Path]:
    """The part files a new read uses, sorted: every part file except retired ones and the
    inputs of a merge whose output is already in place."""
    for _ in range(5):
        before = manifests(day_dir)
        gone = set(retired(day_dir))
        files = sorted(p for p in day_dir.glob(PART_GLOB) if p.is_file())
        if manifests(day_dir) != before:
            continue  # a merge moved on while we looked: look again
        names = {p.name for p in files}
        for output, inputs in before.items():
            if output in names:
                gone.update(i for i in inputs if i != output)
        return [p for p in files if p.name not in gone]
    raise OSError(f"{day_dir.name}: files changing too fast to list")


def has_visible(day_dir: Path) -> bool:
    return bool(visible(day_dir)) if any(day_dir.glob(PART_GLOB)) else False


def _write(day_dir: Path, entries: dict[str, dict[str, str]]) -> None:
    path = day_dir / RETIRED
    if not entries:
        path.unlink(missing_ok=True)
        return
    tmp = day_dir / f".{RETIRED}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(entries, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def retire(day_dir: Path, names: Iterable[str], into: str, now: datetime | None = None) -> None:
    """Leave these files in place for reads already running; new reads skip them."""
    at = (now or datetime.now(UTC)).isoformat()
    entries = retired(day_dir)
    for n in names:
        if _NAME.fullmatch(n) and n != into:
            entries.setdefault(n, {"at": at, "into": into})
    _write(day_dir, entries)


def due(day_dir: Path, now: datetime | None = None, grace_s: float = RETIRE_GRACE_S) -> list[str]:
    """Retired files whose grace period is over."""
    t = now or datetime.now(UTC)
    out = []
    for name, entry in retired(day_dir).items():
        try:
            at = datetime.fromisoformat(entry["at"])
        except ValueError:
            at = t  # unreadable time: wait a full grace period from now
        if (t - at).total_seconds() >= grace_s:
            out.append(name)
    return sorted(out)


def forget(day_dir: Path, names: Iterable[str]) -> None:
    """Drop entries for files that are gone (or kept for verification to report)."""
    entries = retired(day_dir)
    for n in names:
        entries.pop(n, None)
    _write(day_dir, entries)
