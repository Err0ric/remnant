"""The daily AI rollup (ADR-0035 Part 1, accepted with the owner's condition on access).

For each source and each closed day (UTC), the rows AI usage reduces events to (one per
service, person, machine, address, and hour) are stored as Parquet under
`<data>/rollup/ai/source=<id>/day=<date>/part-0.parquet`, outside the lake, so they are
never read as events and never enter the integrity ledger (row 7: derived, rebuildable).

A day is rebuilt when its event files change (late events, compaction) or the catalog's
domains change (rows 5 and 6); it is removed when its source day is removed (retention).

Each day's manifest also records when every service, MCP server, and agent was first seen
that day: the first-seen index, so "New in 24 hours" never scans 30 days of events (F63).
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
from time import monotonic
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from app.ai.agents import ITEMS_SQL
from app.ai.catalog import Catalog
from app.ai.usage import MCP_SQL, first_services_sql, rollup_build_sql
from app.engine.duckdb import IDENT_FILE, QueryEngine, QueryScope
from app.search.addresses import IDENT_RAW

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
    indexed: int = 0  # days given their first-seen entries without a rebuild


# Who or which machine had an address on the day (logons, User-ID, VPN, DHCP, sign-ins on
# a machine), reduced to the first and last observation of each mapping per hour: spans
# run from one observation to the next, so the ones in between add nothing. A few
# thousand rows a day where the events are hundreds of thousands (owner, 2026-10-29).
IDENT_SQL = f"""WITH r AS ({IDENT_RAW}
)
SELECT DISTINCT kind, ip, t, who, host, mac, fin, src, dev FROM (
  SELECT kind, ip, who, host, mac, fin, src, dev, unnest([min(t), max(t)]) AS t
  FROM r
  GROUP BY kind, ip, who, host, mac, fin, src, dev, date_trunc('hour', t)
)"""  # noqa: S608  # fixed text

IDENT_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("ip", pa.string()),
        ("t", pa.timestamp("us", "UTC")),
        ("who", pa.string()),
        ("host", pa.string()),
        ("mac", pa.string()),
        ("fin", pa.bool_()),
        ("src", pa.string()),
        ("dev", pa.string()),
        ("day", pa.string()),
    ]
)


def _ts(v: Any) -> datetime | None:
    if v is None:
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _iso(v: Any) -> str:
    t = _ts(v)
    return t.isoformat() if t is not None else str(v)


def _first_services(table: pa.Table) -> dict[str, str]:
    """First seen per service in a day's rollup rows."""
    out: dict[str, datetime] = {}
    for sid, t in zip(
        table.column("service_id").to_pylist(), table.column("first_t").to_pylist(), strict=True
    ):
        if sid is not None and t is not None and (sid not in out or t < out[sid]):
            out[sid] = t
    return {f"service:{k}": _iso(v) for k, v in out.items()}


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
        self._first_cache: dict[Path, tuple[int, dict[str, datetime]]] = {}
        self._recheck_total = 0  # days the running re-check started with

    # --- freshness ----------------------------------------------------------------------

    def catalog_key(self) -> str:
        pairs = sorted(self._catalog.domain_table())
        return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()[:16]

    def _inputs(self, lake_day: Path) -> list[list[Any]]:
        return sorted([p.name, p.stat().st_size] for p in lake_day.glob("part-*.parquet"))

    def _fresh(self, source: str, day: str, key: str, readable: bool = True) -> bool:
        """Built from the day's current files and catalog. `readable`: and has rows to read
        (a day too large for the rollup is current but read live; it is not rebuilt until
        its files or the catalog change)."""
        built = self._dir / f"source={source}" / f"day={day}"
        lake_day = self._lake / f"source={source}" / f"day={day}"
        try:
            m = json.loads((built / MANIFEST).read_text())
        except (OSError, ValueError):
            return False
        current = m.get("catalog") == key and m.get("inputs") == self._inputs(lake_day)
        if not readable:
            return bool(current)
        return bool(current and (built / PART).is_file() and not m.get("skipped"))

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
        closed = self._closed_days()
        stale = [(s, d) for s, d in closed if not self._fresh(s, d, key, readable=False)]
        for source, day in stale[: self._max]:
            if self._build(source, day, key):
                report.built += 1
            else:
                report.skipped += 1
        # Days built before the first-seen index existed get it without a rebuild, so
        # they stay readable from the rollup meanwhile (F63).
        left = self._max - min(len(stale), self._max)
        done = set(stale)
        unindexed = [(s, d) for s, d in closed if (s, d) not in done and not self._indexed(s, d)]
        for source, day in unindexed[:left]:
            self._index_only(source, day)
            report.indexed += 1
        report.pending = max(0, len(stale) - self._max) + max(0, len(unindexed) - left)
        if report.built or report.removed or report.indexed:
            log.info(
                "ai_rollup.run",
                built=report.built,
                removed=report.removed,
                indexed=report.indexed,
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
        self._write_ident(out, scope, day)
        result = self._engine.run(
            rollup_build_sql(self._catalog.domain_table()),
            scope,
            row_cap=MAX_ROWS,
            timeout_s=120,
            intel=False,
            name="ai_rollup.build",
        )
        if result.truncated:
            # Too many rows to be worth it: that day is read live, and marked so.
            (out / PART).unlink(missing_ok=True)
            svc = self._engine.run(
                first_services_sql(self._catalog.domain_table()), scope, timeout_s=120,
                intel=False, name="ai_rollup.first",
            ).rows  # fmt: skip
            first = self._first_other(scope) | {f"service:{s}": _iso(t) for s, t in svc}
            self._manifest(out, key, inputs, skipped=True, first=first)
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
        self._manifest(out, key, inputs, first=self._first_other(scope) | _first_services(table))
        return True

    def _write_ident(self, out: Path, scope: QueryScope, day: str) -> int:
        """The day's identity observations (IDENT_SQL), with the day they belong to."""
        rows = self._engine.run(
            IDENT_SQL, scope, timeout_s=120, intel=False, name="ai_rollup.ident"
        ).rows
        cols = list(zip(*rows, strict=True)) if rows else [()] * 9
        arrays = [
            pa.array(list(cols[0]), pa.string()),
            pa.array(list(cols[1]), pa.string()),
            pa.array([_ts(v) for v in cols[2]], pa.timestamp("us", "UTC")),
            *(pa.array(list(cols[i]), pa.string()) for i in (3, 4, 5)),
            pa.array([bool(v) for v in cols[6]], pa.bool_()),
            *(pa.array(list(cols[i]), pa.string()) for i in (7, 8)),
            pa.array([day] * len(rows), pa.string()),
        ]
        tmp = out / f".{IDENT_FILE}.tmp"
        pq.write_table(pa.Table.from_arrays(arrays, schema=IDENT_SCHEMA), tmp)
        os.replace(tmp, out / IDENT_FILE)
        return len(rows)

    def _manifest(
        self,
        out: Path,
        key: str,
        inputs: list[list[Any]],
        skipped: bool = False,
        first: dict[str, str] | None = None,
    ) -> None:
        tmp = out / f".{MANIFEST}.tmp"
        body: dict[str, Any] = {
            "catalog": key, "inputs": inputs, "skipped": skipped, "first": first or {},
        }  # fmt: skip
        tmp.write_text(json.dumps(body))
        os.replace(tmp, out / MANIFEST)

    # --- who had an address on closed days (owner, 2026-10-29) ------------------------

    def _no_ident(self) -> list[tuple[str, str]]:
        """Built days with no identity file yet, newest first (built before it existed)."""
        out = []
        for built in self._dir.glob("source=*/day=*") if self._dir.is_dir() else []:
            if (built / MANIFEST).is_file() and not (built / IDENT_FILE).is_file():
                out.append(
                    (built.parent.name.removeprefix("source="), built.name.removeprefix("day="))
                )
        return sorted(out, key=lambda p: (p[1], p[0]), reverse=True)

    def recheck(self, budget_s: float = 20.0) -> int:
        """Write the identity file for days built before it existed, newest first, for at
        most `budget_s` per call (each maintenance tick), logged as `rollup.recheck`: start,
        each day, and finish. Until a day has it, AI pages show its use without people
        and say how many days are left; they never read that day's events instead."""
        todo = self._no_ident()
        if not todo:
            if self._recheck_total:
                log.info("rollup.recheck.finished", days=self._recheck_total)
                self._recheck_total = 0
            return 0
        if not self._recheck_total:
            self._recheck_total = len(todo)
            log.info("rollup.recheck.started", days=len(todo))
        done = 0
        started = monotonic()
        for source, day in todo:
            if done and monotonic() - started >= budget_s:
                break
            out = self._dir / f"source={source}" / f"day={day}"
            start = datetime.combine(date.fromisoformat(day), time(0), UTC)
            scope = QueryScope(
                [source], start, start + timedelta(days=1) - timedelta(microseconds=1)
            )
            rows = self._write_ident(out, scope, day)
            done += 1
            log.info(
                "rollup.recheck.day", source=source, day=day, rows=rows,
                left=len(todo) - done,
            )  # fmt: skip
        if done == len(todo):
            log.info("rollup.recheck.finished", days=self._recheck_total)
            self._recheck_total = 0
        return done

    def pending(self, covered: list[str]) -> int:
        """Covered days ("source|day") whose identity file is not written yet."""
        return sum(
            1
            for c in covered
            if not (
                self._dir / f"source={c.split('|')[0]}" / f"day={c.split('|')[1]}" / IDENT_FILE
            ).is_file()
        )

    # --- the first-seen index (F63) -----------------------------------------------------

    def _first_other(self, scope: QueryScope) -> dict[str, str]:
        """MCP servers and agents first seen in a source's day (telemetry, inventory, and
        usage reports; a day of other events matches none of their templates)."""
        out: dict[str, str] = {}
        for row in self._engine.run(
            MCP_SQL, scope, timeout_s=120, intel=False, name="ai_rollup.first"
        ).rows:
            out[f"mcp:{row[0]}"] = _iso(row[6])
        for row in self._engine.run(
            ITEMS_SQL, scope, {"recent": scope.end or self._clock()}, timeout_s=120, intel=False,
            name="ai_rollup.first",
        ).rows:  # fmt: skip
            out[f"agent:{row[1]}"] = _iso(row[5])
        return out

    def _indexed(self, source: str, day: str) -> bool:
        try:
            m = json.loads((self._dir / f"source={source}" / f"day={day}" / MANIFEST).read_text())
        except (OSError, ValueError):
            return False
        return "first" in m

    def _index_only(self, source: str, day: str) -> None:
        out = self._dir / f"source={source}" / f"day={day}"
        m = json.loads((out / MANIFEST).read_text())
        start = datetime.combine(date.fromisoformat(day), time(0), UTC)
        scope = QueryScope([source], start, start + timedelta(days=1) - timedelta(microseconds=1))
        first = self._first_other(scope)
        if (out / PART).is_file():
            first |= _first_services(pq.read_table(out / PART))
        self._manifest(out, m.get("catalog", ""), m.get("inputs", []), bool(m.get("skipped")),
                       first)  # fmt: skip

    def first_seen(self, sources: list[str] | None) -> dict[str, datetime]:
        """ "service:<id>", "mcp:<name>", or "agent:<key>" -> when first seen in any closed
        day of these sources (None: all) that the rollup has indexed. Read from the day
        manifests, cached per file, so a dashboard load reads no events for it."""
        out: dict[str, datetime] = {}
        if not self._dir.is_dir():
            return out
        wanted = None if sources is None else set(sources)
        for src in self._dir.glob("source=*"):
            if wanted is not None and src.name.removeprefix("source=") not in wanted:
                continue
            for path in src.glob(f"day=*/{MANIFEST}"):
                for k, t in self._day_first(path).items():
                    if k not in out or t < out[k]:
                        out[k] = t
        return out

    def _day_first(self, path: Path) -> dict[str, datetime]:
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return {}
        hit = self._first_cache.get(path)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        try:
            raw = json.loads(path.read_text()).get("first") or {}
        except (OSError, ValueError):
            raw = {}
        parsed = {str(k): t for k, v in raw.items() if (t := _ts(v)) is not None}
        self._first_cache[path] = (stamp, parsed)
        return parsed

    # --- reading ------------------------------------------------------------------------

    def covered(self, scope: QueryScope) -> list[str]:
        """ "source|YYYY-MM-DD" for every fresh rollup day in scope: those are read from the
        rollup, the rest of the range from events. Who had an address on those days comes
        from each day's identity file; a day without one yet (`pending`) has no people."""
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
