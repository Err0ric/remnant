"""The daily AI rollup (ADR-0035 Part 1, accepted with the owner's condition on access).

For each source and each closed day (UTC), the rows AI usage reduces events to (one per
service, person, machine, address, and hour) are stored as Parquet under
`<data>/rollup/ai/source=<id>/day=<date>/part-0.parquet`, outside the lake, so they are
never read as events and never enter the integrity ledger (row 7: derived, rebuildable).

A day is rebuilt when its event files change (late events, compaction) or the catalog's
domains change (rows 5 and 6); it is removed when its source day is removed (retention).
Reads go through the engine's `ai_rollup` view, built per query from the caller's sources
exactly like `events` (row 4), and carry each source's classification as the events had it.
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

from app.ai.catalog import Catalog
from app.ai.usage import rollup_build_sql
from app.engine.duckdb import QueryEngine, QueryScope

log = structlog.get_logger(__name__)

MANIFEST = "_built.json"
PART = "part-0.parquet"
MAX_ROWS = 200_000  # a closed day with more grouped rows than this is read live instead
SCHEMA = pa.schema(
    [
        ("source_id", pa.string()),
        ("classification", pa.string()),
        ("service_id", pa.string()),
        ("who0", pa.string()),
        ("shost", pa.string()),
        ("ip", pa.string()),
        ("dev", pa.string()),
        ("t", pa.timestamp("us", tz="UTC")),
        ("n", pa.int64()),
        ("first_t", pa.timestamp("us", tz="UTC")),
        ("last_t", pa.timestamp("us", tz="UTC")),
    ]
)


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


class AiRollup:
    def __init__(
        self,
        engine: QueryEngine,
        catalog: Catalog,
        lake_dir: Path,
        rollup_dir: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_days_per_run: int = 60,
    ) -> None:
        self._engine = engine
        self._catalog = catalog
        self._lake = lake_dir
        self._dir = rollup_dir
        self._clock = clock
        self._max = max_days_per_run

    # --- freshness ----------------------------------------------------------------------

    def catalog_key(self) -> str:
        pairs = sorted(self._catalog.domain_table())
        return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()[:16]

    def _inputs(self, lake_day: Path) -> list[list[Any]]:
        return sorted([p.name, p.stat().st_size] for p in lake_day.glob("part-*.parquet"))

    def _fresh(self, source: str, day: str, key: str) -> bool:
        built = self._dir / f"source={source}" / f"day={day}"
        lake_day = self._lake / f"source={source}" / f"day={day}"
        try:
            m = json.loads((built / MANIFEST).read_text())
        except (OSError, ValueError):
            return False
        return (
            m.get("catalog") == key
            and m.get("inputs") == self._inputs(lake_day)
            and (built / PART).is_file()
            and not m.get("skipped")
        )

    def _closed_days(self) -> list[tuple[str, str]]:
        """(source, day) for every closed day in the lake, newest first."""
        today = self._clock().astimezone(UTC).date().isoformat()
        found = []
        for src in self._lake.glob("source=*"):
            for d in src.glob("day=*"):
                day = d.name.removeprefix("day=")
                if day < today and any(d.glob("part-*.parquet")):
                    found.append((src.name.removeprefix("source="), day))
        return sorted(found, key=lambda p: (p[1], p[0]), reverse=True)

    # --- the job ------------------------------------------------------------------------

    def run(self) -> RollupReport:
        """Remove days whose source day is gone, then build stale closed days, newest first,
        at most `max_days_per_run` per call so the job stays bounded (a catalog change
        rebuilds the window over several runs, oldest last: ADR-0035 row 5)."""
        report = RollupReport()
        if self._dir.is_dir():
            for built in self._dir.glob("source=*/day=*"):
                lake_day = self._lake / built.parent.name / built.name
                if not lake_day.is_dir():
                    shutil.rmtree(built, ignore_errors=True)
                    report.removed += 1
        if not self._lake.is_dir():
            return report
        key = self.catalog_key()
        stale = [(s, d) for s, d in self._closed_days() if not self._fresh(s, d, key)]
        for source, day in stale[: self._max]:
            if self._build(source, day, key):
                report.built += 1
            else:
                report.skipped += 1
        report.pending = max(0, len(stale) - self._max)
        if report.built or report.removed:
            log.info(
                "ai_rollup.run",
                built=report.built,
                removed=report.removed,
                pending=report.pending,
                skipped=report.skipped,
            )
        return report

    def _build(self, source: str, day: str, key: str) -> bool:
        lake_day = self._lake / f"source={source}" / f"day={day}"
        inputs = self._inputs(lake_day)
        start = datetime.combine(date.fromisoformat(day), time(0), UTC)
        scope = QueryScope([source], start, start + timedelta(days=1) - timedelta(microseconds=1))
        out = self._dir / f"source={source}" / f"day={day}"
        out.mkdir(parents=True, exist_ok=True)
        result = self._engine.run(
            rollup_build_sql(self._catalog.domain_table()),
            scope,
            row_cap=MAX_ROWS,
            timeout_s=120,
            intel=False,
        )
        if result.truncated:
            # Too many rows to be worth it: that day is read live, and marked so.
            (out / PART).unlink(missing_ok=True)
            self._manifest(out, key, inputs, skipped=True)
            return False
        cols = list(zip(*result.rows, strict=True)) if result.rows else [()] * len(SCHEMA)
        arrays = []
        for kind, values in zip([f.type for f in SCHEMA], cols, strict=True):
            if pa.types.is_timestamp(kind):
                arrays.append(pa.array([_ts(v) for v in values], type=kind))
            elif pa.types.is_integer(kind):
                arrays.append(pa.array([int(v or 0) for v in values], type=kind))
            else:
                arrays.append(pa.array([None if v is None else str(v) for v in values], type=kind))
        table = pa.Table.from_arrays(arrays, schema=SCHEMA)
        tmp = out / f".{PART}.tmp"
        pq.write_table(table, tmp)
        os.replace(tmp, out / PART)
        self._manifest(out, key, inputs)
        return True

    def _manifest(
        self, out: Path, key: str, inputs: list[list[Any]], skipped: bool = False
    ) -> None:
        tmp = out / f".{MANIFEST}.tmp"
        tmp.write_text(json.dumps({"catalog": key, "inputs": inputs, "skipped": skipped}))
        os.replace(tmp, out / MANIFEST)

    # --- reading ------------------------------------------------------------------------

    def covered(self, scope: QueryScope) -> list[str]:
        """ "source|YYYY-MM-DD" for every fresh rollup day in scope: those are read from the
        rollup, the rest of the range from events."""
        if scope.start is None or scope.end is None:
            return []
        first = scope.start.astimezone(UTC).date().isoformat()
        last = scope.end.astimezone(UTC).date().isoformat()
        key = self.catalog_key()
        out = []
        for d in self._engine.rollup_dirs(scope):
            source = d.name.removeprefix("source=")
            for built in d.glob("day=*"):
                day = built.name.removeprefix("day=")
                if first <= day <= last and self._fresh(source, day, key):
                    out.append(f"{source}|{day}")
        return sorted(out)
