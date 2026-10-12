"""Scheduling glue for lake maintenance: compaction hourly, retention daily."""

import time
from collections.abc import Callable
from pathlib import Path

from app.ingest.compaction import CompactionReport, Compactor
from app.ingest.lakelock import lake_lock
from app.ingest.retention import RetentionJob, RetentionReport
from app.ingest.sources import SourceStore


class LakeMaintenance:
    def __init__(
        self,
        lake_dir: Path,
        sources: SourceStore,
        orphan_retention_days: int,
        compaction_interval_s: float,
        retention_interval_s: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lake = lake_dir
        self._sources = sources
        self._orphan_days = orphan_retention_days
        self._compaction_every = compaction_interval_s
        self._retention_every = retention_interval_s
        self._now = monotonic
        self._last_compaction: float | None = None
        self._last_retention: float | None = None

    def compact(self) -> CompactionReport:
        return Compactor(self._lake).run()

    def apply_retention(self) -> RetentionReport:
        # Sources removed from config fall back to orphan_retention_days, so their
        # data ages out instead of living forever.
        days = {s.source_id: s.retention_days for s in self._sources.list()}
        return RetentionJob(self._lake, days, default_days=self._orphan_days).run()

    def tick(self) -> None:
        """Run whichever job is due. Called from the server loop. While a backup holds
        the lake lock, the jobs wait for the next tick."""
        with lake_lock(self._lake, wait=False) as held:
            if held:
                self._run_due()

    def _run_due(self) -> None:
        now = self._now()
        if self._last_retention is None or now - self._last_retention >= self._retention_every:
            self.apply_retention()
            self._last_retention = now
        if self._last_compaction is None or now - self._last_compaction >= self._compaction_every:
            self.compact()
            self._last_compaction = now
