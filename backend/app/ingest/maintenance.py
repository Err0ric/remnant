"""Scheduling glue for lake maintenance: compaction hourly, retention daily."""

import time
from collections.abc import Callable
from pathlib import Path

import structlog

from app.ingest.compaction import CompactionReport, Compactor
from app.ingest.durable import sweep
from app.ingest.integrity import IntegrityLedger, LakeEvents, NoEvents, Verification
from app.ingest.lakelock import lake_lock
from app.ingest.retention import RetentionJob, RetentionReport
from app.ingest.sources import SourceStore

log = structlog.get_logger(__name__)


class LakeMaintenance:
    def __init__(
        self,
        lake_dir: Path,
        sources: SourceStore,
        orphan_retention_days: int,
        compaction_interval_s: float,
        retention_interval_s: float,
        monotonic: Callable[[], float] = time.monotonic,
        integrity: IntegrityLedger | None = None,
        integrity_interval_s: float = 86_400.0,
    ) -> None:
        self._lake = lake_dir
        self._integrity = integrity
        self._events: LakeEvents = integrity or NoEvents()
        self._integrity_every = integrity_interval_s
        self._last_integrity: float | None = None
        self.on_verified: Callable[[Verification], None] | None = None
        # Runs after each compaction: the daily AI rollup builds closed days (ADR-0035 row 3).
        self.after_compaction: Callable[[], object] | None = None
        # Short work every tick, bounded by its own time budget (the rollup re-check).
        self.each_tick: Callable[[], object] | None = None
        self._sources = sources
        self._orphan_days = orphan_retention_days
        self._compaction_every = compaction_interval_s
        self._retention_every = retention_interval_s
        self._now = monotonic
        self._last_compaction: float | None = None
        self._last_retention: float | None = None

    def compact(self) -> CompactionReport:
        return Compactor(self._lake, events=self._events).run()

    def apply_retention(self) -> RetentionReport:
        # Sources removed from config fall back to orphan_retention_days, so their
        # data ages out instead of living forever.
        days = {s.source_id: s.retention_days for s in self._sources.list()}
        return RetentionJob(
            self._lake, days, default_days=self._orphan_days, events=self._events
        ).run()

    def sweep_all(self) -> int:
        """Move every unreadable part file out of the lake (run once at start)."""
        with lake_lock(self._lake, wait=False) as held:
            return sweep(self._lake, full=True, events=self._events) if held else 0

    def baseline(self) -> int:
        """Record every file already in the lake, once, when the ledger starts empty."""
        if self._integrity is None:
            return 0
        with lake_lock(self._lake, wait=False) as held:
            return self._integrity.ensure_baseline() if held else 0

    def tick(self) -> None:
        """Run whichever job is due. Called from the server loop. While a backup holds
        the lake lock, the jobs wait for the next tick."""
        with lake_lock(self._lake, wait=False) as held:
            if held:
                self._run_due()

    def _run_due(self) -> None:
        # Empty files break every query over their day; move them aside each tick.
        sweep(self._lake, events=self._events)
        now = self._now()
        if self._last_retention is None or now - self._last_retention >= self._retention_every:
            self.apply_retention()
            self._last_retention = now
        if self._last_compaction is None or now - self._last_compaction >= self._compaction_every:
            self.compact()
            self._last_compaction = now
            if self.after_compaction is not None:
                try:
                    self.after_compaction()
                except Exception:  # a rollup failure never stops lake maintenance
                    log.exception("ai_rollup.failed")
        if self.each_tick is not None:
            try:
                self.each_tick()
            except Exception:  # a rollup re-check failure never stops lake maintenance
                log.exception("rollup.recheck.failed")
        if self._integrity is not None and (
            self._last_integrity is None or now - self._last_integrity >= self._integrity_every
        ):
            self._last_integrity = now
            self.verify()

    def verify(self) -> Verification | None:
        """Check the lake and audit log against their chains (ADR-0022 row 3)."""
        if self._integrity is None:
            return None
        result = self._integrity.verify()
        log.info("integrity.verified", status=result.status, files=result.files)
        if self.on_verified is not None:
            self.on_verified(result)
        return result
