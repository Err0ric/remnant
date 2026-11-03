"""Which background jobs are failing right now (owner, 2026-11-03: AI Watch failed every
hour and on every page refresh with nothing but a class name in the server log).

Each job records success or failure as it runs. A failing job keeps when it started
failing, how many runs failed since, and the last failure as `log_detail` gives it (the
error class, DuckDB's own class, and a message cut before any quoted value). Health and
the pages that depend on a job show what is failing; a success clears it. In memory: a
restart starts clean, and the next run says again.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.errors import log_detail


@dataclass(slots=True)
class Failure:
    job: str
    since: datetime
    last_at: datetime
    count: int
    error: str
    engine_error: str | None = None
    detail: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


class JobStatus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failing: dict[str, Failure] = {}

    def ok(self, job: str) -> None:
        with self._lock:
            self._failing.pop(job, None)

    def failed(self, job: str, exc: BaseException, now: datetime | None = None) -> Failure:
        at = now or datetime.now(UTC)
        d = log_detail(exc)
        with self._lock:
            had = self._failing.get(job)
            f = Failure(
                job=job,
                since=had.since if had else at,
                last_at=at,
                count=(had.count if had else 0) + 1,
                error=d["error"],
                engine_error=d.get("engine_error"),
                detail=d.get("detail"),
            )
            self._failing[job] = f
            return f

    def failing(self, prefix: str = "") -> list[Failure]:
        with self._lock:
            out = [f for j, f in self._failing.items() if j.startswith(prefix)]
        return sorted(out, key=lambda f: f.since)
