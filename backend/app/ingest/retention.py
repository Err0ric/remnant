"""Delete whole day partitions older than each source's retention (SPEC 3.3).

Only folders shaped exactly like `source=<id>/day=YYYY-MM-DD` directly under the
lake are considered. Symlinks are never followed or removed, so a link planted in
the lake cannot point the job at data outside it.
"""

import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.ingest.integrity import LakeEvents, NoEvents

_SOURCE = re.compile(r"source=([a-z0-9][a-z0-9_]{0,63})")
_DAY = re.compile(r"day=(\d{4}-\d{2}-\d{2})")


@dataclass(slots=True)
class RetentionReport:
    partitions_deleted: int = 0
    sources: list[str] = field(default_factory=list)


class RetentionJob:
    def __init__(
        self,
        lake_dir: Path,
        retention_days: Mapping[str, int],
        default_days: int = 30,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
        events: LakeEvents | None = None,
    ) -> None:
        self._lake = lake_dir
        self._events = events or NoEvents()
        self._days = dict(retention_days)
        self._default = default_days
        self._today = today

    def run(self) -> RetentionReport:
        report = RetentionReport()
        if not self._lake.is_dir() or self._lake.is_symlink():
            return report
        today = self._today()
        for source_dir in sorted(self._lake.iterdir()):
            src = _SOURCE.fullmatch(source_dir.name)
            if src is None or source_dir.is_symlink() or not source_dir.is_dir():
                continue
            cutoff = today - timedelta(days=self._days.get(src.group(1), self._default))
            deleted = 0
            for day_dir in sorted(source_dir.iterdir()):
                m = _DAY.fullmatch(day_dir.name)
                if m is None or day_dir.is_symlink() or not day_dir.is_dir():
                    continue
                try:
                    day = date.fromisoformat(m.group(1))
                except ValueError:
                    continue
                if day < cutoff:
                    files = [p for p in day_dir.glob("part-*.parquet") if p.is_file()]
                    days_kept = self._days.get(src.group(1), self._default)
                    ok = self._events.removed(files, f"retention: older than {days_kept} days")
                    if len(ok) == len(files):
                        shutil.rmtree(day_dir)
                    else:  # a changed file stays for verification to report
                        for path in ok:
                            path.unlink(missing_ok=True)
                    deleted += 1
            if deleted:
                report.partitions_deleted += deleted
                report.sources.append(src.group(1))
            if not any(source_dir.iterdir()):
                source_dir.rmdir()
        return report
