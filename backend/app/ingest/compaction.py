"""Merge small Parquet files within a partition (SPEC 3.3).

Files under `small_bytes` in one source/day partition are merged into files of
about `target_bytes`, sorted by time. A closed day (before today) merges as soon
as it has two small files; the open day waits for `min_files_open_day` so the
active partition is not rewritten on every pass.

Crash safety: before the merged file is published, a manifest naming the output
and its inputs is written next to it. On the next run, a manifest whose output
exists finishes the job (removes the inputs); one whose output is missing is
discarded and the inputs stay. Data is never lost; a crash can at worst leave a
short window of duplicates that the next run removes.
"""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from app.core.ids import uuid7
from app.core.schema import arrow_schema
from app.ingest.durable import publish, quarantine, readable
from app.ingest.integrity import LakeEvents, NoEvents

MANIFEST_SUFFIX = ".compact.json"
_PARTITION = re.compile(r"day=(\d{4}-\d{2}-\d{2})")


@dataclass(slots=True)
class CompactionReport:
    partitions: int = 0
    files_merged: int = 0
    files_written: int = 0
    recovered: int = 0


log = structlog.get_logger(__name__)


class Compactor:
    def __init__(
        self,
        lake_dir: Path,
        small_bytes: int = 32 << 20,
        target_bytes: int = 128 << 20,
        min_files_open_day: int = 16,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
        events: LakeEvents | None = None,
    ) -> None:
        self._lake = lake_dir
        self._events = events or NoEvents()
        self._small = small_bytes
        self._target = target_bytes
        self._min_open = max(2, min_files_open_day)
        self._today = today
        self._schema = arrow_schema()

    def run(self) -> CompactionReport:
        report = CompactionReport()
        if not self._lake.is_dir():
            return report
        today = self._today()
        for folder in sorted(self._lake.glob("source=*/day=*")):
            match = _PARTITION.fullmatch(folder.name)
            if folder.is_symlink() or not folder.is_dir() or match is None:
                continue
            report.recovered += self._recover(folder)
            try:
                closed = date.fromisoformat(match.group(1)) < today
            except ValueError:
                continue
            small = [
                p
                for p in sorted(folder.glob("part-*.parquet"))
                if p.is_file() and not p.is_symlink() and p.stat().st_size < self._small
            ]
            if len(small) < (2 if closed else self._min_open):
                continue
            small = [p for p in small if self._usable(p)]
            # Never merge a file whose content differs from the ledger: the edit would be
            # laundered into a new, legitimately recorded file (security review).
            small = self._events.unchanged(small)
            if len(small) < (2 if closed else self._min_open):
                continue
            touched = False
            for batch in self._batches(small):
                if len(batch) < 2:
                    continue
                output = self._merge(folder, batch)
                self._finish(folder, output.name, [p.name for p in batch])
                report.files_merged += len(batch)
                report.files_written += 1
                touched = True
            report.partitions += int(touched)
        return report

    def _usable(self, path: Path) -> bool:
        """A damaged file is moved aside instead of failing the whole run."""
        why = readable(path)
        if why is None:
            return True
        quarantine(self._lake, path, why, self._events)
        return False

    def _batches(self, files: list[Path]) -> list[list[Path]]:
        batches: list[list[Path]] = []
        current: list[Path] = []
        size = 0
        for path in files:
            n = path.stat().st_size
            if current and size + n > self._target:
                batches.append(current)
                current, size = [], 0
            current.append(path)
            size += n
        if current:
            batches.append(current)
        return batches

    def _merge(self, folder: Path, inputs: list[Path]) -> Path:
        """Write the merged file and its manifest. Inputs are left in place."""
        tables = [self._conform(pq.read_table(p)) for p in inputs]
        merged = pa.concat_tables(tables).sort_by([("time", "ascending")])
        final = folder / f"part-{uuid7().hex}.parquet"
        manifest = folder / f"{final.stem}{MANIFEST_SUFFIX}"
        with manifest.open("w", encoding="utf-8") as fh:
            json.dump({"output": final.name, "inputs": [p.name for p in inputs]}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        published = publish(merged, final)
        self._events.added([published])
        return published

    def _conform(self, table: pa.Table) -> pa.Table:
        """Fit an older file to the current schema (migrations are additive only)."""
        columns = []
        for fld in self._schema:
            if fld.name in table.column_names:
                columns.append(table.column(fld.name).cast(fld.type))
            else:
                columns.append(pa.nulls(table.num_rows, type=fld.type))
        return pa.Table.from_arrays(columns, schema=self._schema)

    def _finish(self, folder: Path, output: str, inputs: list[str]) -> None:
        gone = [folder / n for n in inputs if n != output and (folder / n).is_file()]
        for path in self._events.removed(gone, f"compacted into {output}"):
            path.unlink(missing_ok=True)
        (folder / f"{Path(output).stem}{MANIFEST_SUFFIX}").unlink(missing_ok=True)

    def _recover(self, folder: Path) -> int:
        recovered = 0
        for manifest in folder.glob(f"*{MANIFEST_SUFFIX}"):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                output = _safe_name(data["output"])
                inputs = [_safe_name(n) for n in data["inputs"]]
            except (ValueError, KeyError, TypeError):
                manifest.unlink(missing_ok=True)
                continue
            if (folder / output).is_file() and _contains(folder / output, folder, inputs):
                self._finish(folder, output, inputs)
                recovered += 1
            elif (folder / output).is_file():
                # A manifest that does not describe a real merge (security review): keep
                # every file and drop the manifest.
                log.warning("compaction.manifest_rejected", manifest=manifest.name)
                manifest.unlink(missing_ok=True)
            else:
                (folder / f".{output}.tmp").unlink(missing_ok=True)
                manifest.unlink(missing_ok=True)
        return recovered


def _contains(output: Path, folder: Path, inputs: list[str]) -> bool:
    """True only when every event id in the inputs is in the output: proof the output is
    their merge, so the inputs may go."""
    try:
        have = set(pq.read_table(output, columns=["event_id"]).column(0).to_pylist())
        for name in inputs:
            path = folder / name
            if name == output.name or not path.is_file():
                continue
            ids = pq.read_table(path, columns=["event_id"]).column(0).to_pylist()
            if not have.issuperset(ids):
                return False
    except Exception:  # an unreadable file is no proof
        return False
    return True


def _safe_name(name: object) -> str:
    """Manifest entries must be plain part file names in the same folder."""
    if not isinstance(name, str) or not re.fullmatch(r"part-[A-Za-z0-9_-]+\.parquet", name):
        raise ValueError("bad manifest entry")
    return name
