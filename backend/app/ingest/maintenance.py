"""Scheduling glue for lake maintenance: compaction hourly, retention daily."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.core.errors import log_detail
from app.core.job_status import JobStatus
from app.ingest.compaction import CompactionReport, Compactor
from app.ingest.durable import sweep
from app.ingest.integrity import IntegrityLedger, LakeEvents, NoEvents, Verification
from app.ingest.lakelock import lake_lock
from app.ingest.retention import RetentionJob, RetentionReport
from app.ingest.sources import SourceStore

if TYPE_CHECKING:
    from app.alerts.stops import DetectionStops

log = structlog.get_logger(__name__)

# Compaction leaves files this new for its next run (see Compactor): longer than the
# 5 s a ledger write may wait on a locked database.
SETTLE_S = 60.0
# How soon compaction looks again after a run that left a day folder undone.
RETRY_UNDONE_S = 300.0


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
        # Runs with the daily retention: ingest forgets files not seen for 30 days (ADR-0051).
        self.daily: Callable[[], object] | None = None
        self._sources = sources
        self._orphan_days = orphan_retention_days
        self._compaction_every = compaction_interval_s
        self._retention_every = retention_interval_s
        self._now = monotonic
        # Lake files ingest may still take back (IngestService.held): not compacted.
        self.hold: Callable[[], set[Path]] | None = None
        self._last_compaction: float | None = None
        self._last_retention: float | None = None
        # Jobs failing now, for Health; and the never-silent messages (alerts/stops.py).
        self.jobs = JobStatus()
        # Jobs that finished but left something undone: (title, reason), told every tick.
        self._standing: dict[str, tuple[str, str]] = {}
        self.stops: DetectionStops | None = None

    def compact(self) -> CompactionReport:
        return Compactor(self._lake, events=self._events, settle_s=SETTLE_S, hold=self.hold).run()

    def apply_retention(self) -> RetentionReport:
        # Sources removed from config fall back to orphan_retention_days, so their
        # data ages out instead of living forever.
        days = self._sources.retention_days()
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

    def _job(self, name: str, title: str, run: Callable[[], str | None]) -> bool:
        """Run one job. A failure never stops the jobs after it and is never silent
        (D236, D244, audit 2026-11 H7): Health lists it (`jobs`), and after the grace the
        alert targets get one "stopped" and, when it works again, one "running again"
        message. `run` returns a reason when it finished but left something undone.
        False only when the job failed outright (it is then tried again next tick)."""
        try:
            problem = run()
        except Exception as exc:
            log.warning("maintenance.job_failed", job=name, **log_detail(exc))
            self.jobs.failed(f"maintenance.{name}", exc)
            self._standing.pop(name, None)  # tried again next tick, and told then
            self._tell(name, title, f"{type(exc).__name__}: it will be tried again")
            return False
        if problem is not None:
            self.jobs.failed(f"maintenance.{name}", RuntimeError(problem))
            self._standing[name] = (title, problem)
            self._tell(name, title, problem)
            return True
        self._standing.pop(name, None)
        self.jobs.ok(f"maintenance.{name}")
        self._tell(name, title, None)
        return True

    def _tell(self, name: str, title: str, reason: str | None) -> None:
        """Report through alerts/stops.py. Its own failure (the meta database cannot be
        written) is logged and never stops the jobs after this one."""
        if self.stops is None:
            return
        try:
            if reason is None:
                self.stops.working(f"maintenance:{name}")
            else:
                self.stops.failing(f"maintenance:{name}", title, reason)
        except Exception as exc:
            log.warning("maintenance.report_failed", job=name, **log_detail(exc))

    def _compact_job(self) -> str | None:
        report = self.compact()
        if not report.failed:
            return None
        n = len(report.failed)
        first, error = report.failed[0]
        return (
            f"{n} day folder{'' if n == 1 else 's'} could not be compacted"
            f" (first: {first}, {error}); the others were"
        )

    def _run_due(self) -> None:
        # A job that finished but left something undone runs again only when it is next
        # due; the report is repeated every tick meanwhile, so the 15-minute grace is
        # counted from the first failure and not from the next run (D236).
        for name, (title, problem) in list(self._standing.items()):
            self._tell(name, title, problem)
        # Empty files break every query over their day; move them aside each tick.
        self._job("sweep", "Lake maintenance: unreadable files", self._sweep_job)
        now = self._now()
        # A job that failed outright is tried again on the next tick, not an interval later.
        if self._last_retention is None or now - self._last_retention >= self._retention_every:
            if self._job("retention", "Lake maintenance: retention", self._retention_job):
                self._last_retention = now
        if self._last_compaction is None or now - self._last_compaction >= self._compaction_every:
            if self._job("compaction", "Lake maintenance: compaction", self._compact_job):
                self._last_compaction = now
                if "compaction" in self._standing:
                    # A folder was left undone (its unreadable file is now aside): look
                    # again in a few minutes, not an hour, so Health clears when it is done.
                    self._last_compaction = now - self._compaction_every + RETRY_UNDONE_S
                # Only after a run that got through: while compaction fails outright it is
                # tried every tick, and the rollup build must not run every tick with it.
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
            if self._job("integrity", "Lake maintenance: integrity check", self._verify_job):
                self._last_integrity = now

    def _sweep_job(self) -> None:
        sweep(self._lake, events=self._events)

    def _retention_job(self) -> None:
        self.apply_retention()
        if self.daily is not None:
            self.daily()

    def _verify_job(self) -> None:
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
