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
from app.search.auth_facts import BUILD_SQL as AUTH_BUILD_SQL
from app.search.m365 import BUILD_SQL

log = structlog.get_logger(__name__)

MANIFEST = "_built.json"
TODAY = "_today.json"  # the current partial build of today, for every source
TODAY_EVERY_S = 300.0  # rebuild today's facts at most this often
TODAY_MARGIN_S = 60  # the cutoff trails the build, so rows still being written are read live
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


def on_the_hour(t: datetime | None) -> bool:
    """Facts are per hour, so a range read from them must start on an hour. A start inside
    an hour (a half-hour zone's midnight, a range that is not a page window) reads that
    day from events instead: the hour would otherwise count events from before the start
    (a 20-hour AI usage range counted one more use than events did; 2026-11-01)."""
    return t is None or t == t.replace(minute=0, second=0, microsecond=0)


def _start_day(t: datetime | None) -> str | None:
    """The UTC day a range's start falls in when it is not on the hour, else None."""
    return None if on_the_hour(t) or t is None else t.astimezone(UTC).date().isoformat()


class FactRollup:
    """Per source and closed UTC day, the rows `build_sql` reduces events to, as Parquet,
    readable as `table` by server-built queries. Shared by the Microsoft 365 facts and the
    Dashboard's auth facts (owner, 2026-10-31)."""

    TABLE = "m365_rollup"
    BUILD_SQL = BUILD_SQL
    SCHEMA = SCHEMA

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
        self._sources = sources  # the sources whose days are built
        self._clock = clock
        self._max = max_days_per_run
        # What a built day was built with: a changed definition rebuilds every day.
        self.version = hashlib.sha256((self.BUILD_SQL + str(self.SCHEMA)).encode()).hexdigest()[:16]

    @property
    def folder(self) -> Path:
        return self._dir

    def today_mark(self) -> dict[str, Any]:
        try:
            body = json.loads((self._dir / TODAY).read_text())
        except (OSError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

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
        current = m.get("version") == self.version and m.get("inputs") == self._inputs(lake_day)
        if not readable:
            return bool(current)
        return bool(current and (built / PART).is_file() and not m.get("skipped"))

    def _closed_days(self) -> list[tuple[str, str]]:
        """(source, day) for every closed day of the sources built, newest first."""
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
                f"{self.TABLE}.run",
                built=report.built,
                removed=report.removed,
                pending=report.pending,
                skipped=report.skipped,
            )
        return report

    def _build(
        self, source: str, day: str, upto: datetime | None = None, label: str | None = None
    ) -> bool:
        """A day's facts. With `upto`, today so far: rows observed by then, labeled
        `label` ("day@cutoff") so a query only ever reads the build it asked for."""
        lake_day = self._lake / f"source={source}" / f"day={day}"
        inputs = self._inputs(lake_day)
        out = self._dir / f"source={source}" / f"day={day}"
        out.mkdir(parents=True, exist_ok=True)
        result = self._engine.run(
            f"SELECT * FROM (\n{self.BUILD_SQL}\n) LIMIT {MAX_ROWS + 1}",  # noqa: S608  # fixed SQL text
            _day_scope(source, day),
            row_cap=MAX_ROWS,
            timeout_s=120,
            intel=False,
            background=True,
            name=f"{self.TABLE}.build",
            upto=upto,
        )
        if result.truncated:
            (out / PART).unlink(missing_ok=True)
            self._manifest(out, [] if upto else inputs, skipped=True)
            return False
        schema = self.SCHEMA
        width = len(schema) - 1  # every column but `day`
        cols = list(zip(*result.rows, strict=True)) if result.rows else [()] * width
        arrays = []
        for f, values in zip(list(schema)[:width], cols, strict=True):
            if pa.types.is_timestamp(f.type):
                arrays.append(pa.array([_ts(v) for v in values], type=f.type))
            elif pa.types.is_integer(f.type):
                arrays.append(pa.array([None if v is None else int(v) for v in values], f.type))
            elif pa.types.is_boolean(f.type):
                arrays.append(pa.array([None if v is None else bool(v) for v in values], f.type))
            else:
                arrays.append(pa.array([None if v is None else str(v) for v in values], f.type))
        arrays.append(pa.array([label or day] * len(result.rows), pa.string()))
        tmp = out / f".{PART}.tmp"
        # Sorted by kind in small row groups, so a reader of one kind skips the others.
        table = pa.Table.from_arrays(arrays, schema=schema).sort_by([("kind", "ascending")])
        pq.write_table(table, tmp, row_group_size=8192)
        os.replace(tmp, out / PART)
        # A partial day has no inputs: when the day closes it is rebuilt in full.
        self._manifest(out, [] if upto else inputs, partial=label)
        return True

    def _manifest(
        self,
        out: Path,
        inputs: list[list[Any]],
        skipped: bool = False,
        partial: str | None = None,
    ) -> None:
        tmp = out / f".{MANIFEST}.tmp"
        body = {"version": self.version, "inputs": inputs, "skipped": skipped, "partial": partial}
        tmp.write_text(json.dumps(body))
        os.replace(tmp, out / MANIFEST)

    # --- today so far (owner, 2026-10-31: today's events dominated a page) ---------------

    def refresh_today(self, max_age_s: float = TODAY_EVERY_S) -> int:
        """Build today's facts up to a cutoff a minute back (rows observed later are read
        live), at most every `max_age_s`. Returns the sources built."""
        now = self._clock().astimezone(UTC)
        day = now.date().isoformat()
        try:
            mark = json.loads((self._dir / TODAY).read_text())
        except (OSError, ValueError):
            mark = {}
        built_at = mark.get("built_at")
        if (
            mark.get("day") == day
            and mark.get("version") == self.version
            and built_at
            and (now - datetime.fromisoformat(built_at)).total_seconds() < max_age_s
        ):
            return 0
        cutoff = now - timedelta(seconds=TODAY_MARGIN_S)
        label = f"{day}@{cutoff.isoformat()}"
        done = []
        for source in self._sources():
            lake_day = self._lake / f"source={source}" / f"day={day}"
            if any(lake_day.glob("part-*.parquet")) and self._build(source, day, cutoff, label):
                done.append(source)
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._dir / f".{TODAY}.tmp"
        tmp.write_text(json.dumps({
            "day": day, "cutoff": cutoff.isoformat(), "label": label, "version": self.version,
            "sources": done, "built_at": now.isoformat(),
        }))  # fmt: skip
        os.replace(tmp, self._dir / TODAY)
        return len(done)

    def today(self, scope: QueryScope) -> tuple[list[str], list[str], datetime] | None:
        """(keys "source|day@cutoff", sources, cutoff) for today's partial facts of the
        sources in scope, or None: those sources' rows observed by the cutoff come from
        the rollup, later ones from events."""
        now = self._clock().astimezone(UTC)
        try:
            mark = json.loads((self._dir / TODAY).read_text())
        except (OSError, ValueError):
            return None
        if mark.get("day") != now.date().isoformat() or mark.get("version") != self.version:
            return None
        if _start_day(scope.start) == now.date().isoformat():
            return None
        if scope.end is not None and scope.end < datetime.fromisoformat(mark["cutoff"]):
            return None
        wanted = {d.name.removeprefix("source=") for d in self._engine.rollup_dirs(
            scope, table=self.TABLE
        )}  # fmt: skip
        sources = sorted(set(mark.get("sources", [])) & wanted)
        if not sources:
            return None
        label = str(mark["label"])
        return [f"{s}|{label}" for s in sources], sources, datetime.fromisoformat(mark["cutoff"])

    # --- reading ------------------------------------------------------------------------

    def covered(self, scope: QueryScope) -> list[str]:
        """ "source|YYYY-MM-DD" for every fresh closed day the range touches, of the sources
        in scope only: those are read from the rollup (the hours in range), the rest from
        events. Ranges start on the hour (page windows), so hours split exactly."""
        if scope.start is None or scope.end is None:
            return []
        partial = _start_day(scope.start)
        out = []
        for d in self._engine.rollup_dirs(scope, table=self.TABLE):
            source = d.name.removeprefix("source=")
            for built in d.glob("day=*"):
                day = built.name.removeprefix("day=")
                try:
                    begins = datetime.combine(date.fromisoformat(day), time(0), UTC)
                except ValueError:
                    continue
                # Closed days that overlap the range: facts are per hour (or carry their
                # time), so a reader keeps the hours in range ($fact_lo, $fact_hi).
                if (
                    begins + timedelta(days=1) > scope.start
                    and begins <= scope.end
                    and begins.date() < self._clock().astimezone(UTC).date()
                    and day != partial
                    and self._fresh(source, day)
                ):
                    out.append(f"{source}|{day}")
        return sorted(out)


class M365Rollup(FactRollup):
    """The Microsoft 365 Overview's facts (ADR-0041)."""


AUTH_SCHEMA = pa.schema(
    [
        ("kind", pa.string()),
        ("source_id", pa.string()),
        ("t", pa.timestamp("us", tz="UTC")),
        ("ip", pa.string()),
        ("host", pa.string()),
        ("n", pa.int64()),
        ("day", pa.string()),
    ]
)


class AuthRollup(FactRollup):
    """The Dashboard's Attacks and access facts (D135): failed sign-ins outside Microsoft
    365 and VPN logins, per hour, address, and host."""

    TABLE = "auth_rollup"
    BUILD_SQL = AUTH_BUILD_SQL
    SCHEMA = AUTH_SCHEMA
