"""Merge small Parquet files within a partition (SPEC 3.3).

Files under `small_bytes` in one source/day partition are merged into files of
about `target_bytes`, sorted by template then time, in row groups small enough that a
filter on the template or time skips most of a file (owner re-time, 2026-11-01: 608,196
rows read to return 9,000 of one template). A closed day (before today) merges as soon
as it has two small files; the open day waits for `min_files_open_day` so the
active partition is not rewritten on every pass.

Crash safety: before the merged file is published, a manifest naming the output
and its inputs is written next to it. On the next run, a manifest whose output
exists finishes the job (retires the inputs); one whose output is missing is
discarded and the inputs stay. Data is never lost, and no read counts a row twice:
reads leave out the inputs of a manifest whose output is in place
(`app.core.lake_files`).

Merged inputs are retired, not deleted (owner, 2026-11-03: a running read failed with
"Cannot open file" when compaction deleted a file it had listed). They stay in place for
`RETIRE_GRACE_S`, hidden from new reads, and a later run deletes them and records the
removal in the integrity ledger then (D183).
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

from app.core import lake_files
from app.core.ids import uuid7
from app.core.lake_files import MANIFEST_SUFFIX, RETIRE_GRACE_S
from app.core.schema import arrow_schema
from app.ingest.durable import publish, quarantine, readable
from app.ingest.integrity import LakeEvents, NoEvents

# Rows of one template sit together, in time order: each row group's min and max
# template_id and time (Parquet statistics) then let DuckDB skip the groups a filter
# cannot match. Rows without a time keep their place after the timed ones.
SORT_KEYS = [("template_id", "ascending"), ("time", "ascending")]
# DuckDB's own row group size: small enough to skip, large enough to compress well.
ROW_GROUP_ROWS = 122_880

_PARTITION = re.compile(r"day=(\d{4}-\d{2}-\d{2})")


@dataclass(slots=True)
class CompactionReport:
    partitions: int = 0
    files_merged: int = 0
    files_written: int = 0
    recovered: int = 0
    deleted: int = 0  # retired files whose grace period was over


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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        grace_s: float = RETIRE_GRACE_S,
    ) -> None:
        self._clock = clock
        self._grace = grace_s
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
            report.deleted += self._reap(folder)
            try:
                closed = date.fromisoformat(match.group(1)) < today
            except ValueError:
                continue
            small = [
                p
                for p in lake_files.visible(folder)
                if not p.is_symlink() and p.stat().st_size < self._small
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
        merged = pa.concat_tables(tables).sort_by(SORT_KEYS)
        final = folder / f"part-{uuid7().hex}.parquet"
        manifest = folder / f"{final.stem}{MANIFEST_SUFFIX}"
        with manifest.open("w", encoding="utf-8") as fh:
            json.dump({"output": final.name, "inputs": [p.name for p in inputs]}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        published = publish(merged, final, row_group_size=ROW_GROUP_ROWS)
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
        """Retire the inputs (reads already running may still open them), then drop the
        manifest. Retiring first: with the manifest gone, the retired list hides them."""
        names = [n for n in inputs if n != output and (folder / n).is_file()]
        lake_files.retire(folder, names, output, self._clock())
        (folder / f"{Path(output).stem}{MANIFEST_SUFFIX}").unlink(missing_ok=True)

    def _reap(self, folder: Path) -> int:
        """Delete retired files whose grace period is over. The ledger records the
        removal now, when the file goes; a file whose content no longer matches the
        ledger is kept (still hidden) for verification to report."""
        due = lake_files.due(folder, self._clock(), self._grace)
        if not due:
            return 0
        into = lake_files.retired(folder)
        present = [folder / n for n in due if (folder / n).is_file()]
        deleted = 0
        by_output: dict[str, list[Path]] = {}
        for p in present:
            by_output.setdefault(into[p.name].get("into", "?"), []).append(p)
        done = [n for n in due if not (folder / n).is_file()]  # already gone
        for output, paths in by_output.items():
            for path in self._events.removed(paths, f"compacted into {output}"):
                path.unlink(missing_ok=True)
                done.append(path.name)
                deleted += 1
        lake_files.forget(folder, done)
        return deleted

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
