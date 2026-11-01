"""The daily Microsoft 365 rollup (ADR-0041, owner 2026-10-31; replaces D129's deferral).

For each Microsoft 365 source and each closed day (UTC), the Overview's facts
(`app.search.m365.FACTS`) are stored as Parquet under
`<data>/rollup/m365/source=<id>/day=<date>/part-0.parquet`, outside the lake, so they are
never read as events and never enter the integrity ledger (derived, rebuildable).

Per source, so access stays source-based (rule 13): a caller reads only the rollup folders
of sources they may read, exactly like `events`. Changes and consents keep their
one-operation key (D122), so the Overview counts each once across days and across sources
(Graph and the Management API as separate sources) from the rollup alone.

A day is rebuilt when its event files change (late events, compaction) or the facts' SQL
changes (an upgrade that changes a definition); it is removed when its lake day is gone
(retention). Only days wholly inside a page's range are read from the rollup; the rest,
today included, come from events.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from app.engine.duckdb import QueryEngine, QueryScope
from app.search.m365 import BUILD_SQL

log = structlog.get_logger(__name__)

MANIFEST = "_built.json"
PART = "part-0.parquet"
# A closed day with more facts than this is read live instead (the engine's largest result).
MAX_ROWS = 100_000
SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("source_id", pa.string()),
        ("t", pa.timestamp("us", tz="UTC")),
        ("outcome", pa.string()),
        ("risky", pa.bool_()),
        ("who", pa.string()),
        ("app", pa.string()),
        ("ip", pa.string()),
        ("reason", pa.string()),
        ("code", pa.int32()),
        ("op", pa.string()),
        ("k", pa.string()),
        ("sub", pa.string()),
        ("status", pa.int32()),
        ("n", pa.int64()),
        ("last_t", pa.timestamp("us", tz="UTC")),
        ("day", pa.string()),
    ]
)
# What a built day was built with: a changed definition rebuilds every day.
VERSION = hashlib.sha256((BUILD_SQL + str(SCHEMA)).encode()).hexdigest()[:16]


@dataclass(slots=True)
class RollupReport:
    built: int = 0
    removed: int = 0
    pending: int = 0  # stale days left for the next run
    skipped: int = 0  # days too large for the rollup; read live


def _ts(v: Any) -> datetime | None:
    if v is None:
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _day_scope(source: str, day: str) -> QueryScope:
    start = datetime.combine(date.fromisoformat(day), time(0), UTC)
    return QueryScope([source], start, start + timedelta(days=1) - timedelta(microseconds=1))


class M365Rollup:
    def __init__(
        self,
        engine: QueryEngine,
        lake_dir: Path,
        rollup_dir: Path,
        sources: Callable[[], list[str]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_days_per_run: int = 60,
    ) -> None:
        self._engine = engine
        self._lake = lake_dir
        self._dir = rollup_dir
        self._sources = sources  # the Microsoft 365 sources, as the Overview picks them
        self._clock = clock
        self._max = max_days_per_run

    # --- freshness ----------------------------------------------------------------------

    def _inputs(self, lake_day: Path) -> list[list[Any]]:
        return sorted([p.name, p.stat().st_size] for p in lake_day.glob("part-*.parquet"))

    def _fresh(self, source: str, day: str, readable: bool = True) -> bool:
        """Built from the day's current files with the current definitions. `readable`:
        and has facts to read (a day too large is current but read live)."""
        built = self._dir / f"source={source}" / f"day={day}"
        try:
            m = json.loads((built / MANIFEST).read_text())
        except (OSError, ValueError):
            return False
        lake_day = self._lake / f"source={source}" / f"day={day}"
        current = m.get("version") == VERSION and m.get("inputs") == self._inputs(lake_day)
        if not readable:
            return bool(current)
        return bool(current and (built / PART).is_file() and not m.get("skipped"))

    def _closed_days(self) -> list[tuple[str, str]]:
        """(source, day) for every closed day of a Microsoft 365 source, newest first."""
        today = self._clock().astimezone(UTC).date().isoformat()
        found = []
        for source in self._sources():
            for d in (self._lake / f"source={source}").glob("day=*"):
                day = d.name.removeprefix("day=")
                if day < today and any(d.glob("part-*.parquet")):
                    found.append((source, day))
        return sorted(found, key=lambda p: (p[1], p[0]), reverse=True)

    # --- the job ------------------------------------------------------------------------

    def run(self) -> RollupReport:
        """Remove days whose lake day is gone, then build stale closed days, newest first,
        at most `max_days_per_run` per call so the job stays bounded."""
        report = RollupReport()
        if self._dir.is_dir():
            for built in self._dir.glob("source=*/day=*"):
                if not (self._lake / built.parent.name / built.name).is_dir():
                    shutil.rmtree(built, ignore_errors=True)
                    report.removed += 1
        if not self._lake.is_dir():
            return report
        stale = [(s, d) for s, d in self._closed_days() if not self._fresh(s, d, readable=False)]
        for source, day in stale[: self._max]:
            if self._build(source, day):
                report.built += 1
            else:
                report.skipped += 1
        report.pending = max(0, len(stale) - self._max)
        if report.built or report.removed or report.skipped:
            log.info(
                "m365_rollup.run",
                built=report.built,
                removed=report.removed,
                pending=report.pending,
                skipped=report.skipped,
            )
        return report

    def _build(self, source: str, day: str) -> bool:
        lake_day = self._lake / f"source={source}" / f"day={day}"
        inputs = self._inputs(lake_day)
        out = self._dir / f"source={source}" / f"day={day}"
        out.mkdir(parents=True, exist_ok=True)
        result = self._engine.run(
            f"SELECT * FROM (\n{BUILD_SQL}\n) LIMIT {MAX_ROWS + 1}",  # noqa: S608  # fixed SQL text
            _day_scope(source, day),
            row_cap=MAX_ROWS,
            timeout_s=120,
            intel=False,
            name="m365_rollup.build",
        )
        if result.truncated:
            (out / PART).unlink(missing_ok=True)
            self._manifest(out, inputs, skipped=True)
            return False
        width = len(SCHEMA) - 1  # every column but `day`
        cols = list(zip(*result.rows, strict=True)) if result.rows else [()] * width
        arrays = []
        for f, values in zip(list(SCHEMA)[:width], cols, strict=True):
            if pa.types.is_timestamp(f.type):
                arrays.append(pa.array([_ts(v) for v in values], type=f.type))
            elif pa.types.is_integer(f.type):
                arrays.append(pa.array([None if v is None else int(v) for v in values], f.type))
            elif pa.types.is_boolean(f.type):
                arrays.append(pa.array([None if v is None else bool(v) for v in values], f.type))
            else:
                arrays.append(pa.array([None if v is None else str(v) for v in values], f.type))
        arrays.append(pa.array([day] * len(result.rows), pa.string()))
        tmp = out / f".{PART}.tmp"
        pq.write_table(pa.Table.from_arrays(arrays, schema=SCHEMA), tmp)
        os.replace(tmp, out / PART)
        self._manifest(out, inputs)
        return True

    def _manifest(self, out: Path, inputs: list[list[Any]], skipped: bool = False) -> None:
        tmp = out / f".{MANIFEST}.tmp"
        tmp.write_text(json.dumps({"version": VERSION, "inputs": inputs, "skipped": skipped}))
        os.replace(tmp, out / MANIFEST)

    # --- reading ------------------------------------------------------------------------

    def covered(self, scope: QueryScope) -> list[str]:
        """ "source|YYYY-MM-DD" for every fresh day wholly inside the range, of the sources
        in scope only: those are read from the rollup, the rest from events."""
        if scope.start is None or scope.end is None:
            return []
        out = []
        for d in self._engine.rollup_dirs(scope, m365=True):
            source = d.name.removeprefix("source=")
            for built in d.glob("day=*"):
                day = built.name.removeprefix("day=")
                try:
                    begins = datetime.combine(date.fromisoformat(day), time(0), UTC)
                except ValueError:
                    continue
                if (
                    scope.start <= begins
                    and begins + timedelta(days=1) <= scope.end
                    and self._fresh(source, day)
                ):
                    out.append(f"{source}|{day}")
        return sorted(out)
