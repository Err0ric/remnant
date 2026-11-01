"""ADR-0041: the Microsoft 365 Overview over 30 days answers in under 2 s once closed days
are in the rollup (the owner's install took about 14 s reading events). The full-size run
is `-m scale`."""

import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.engine.duckdb import M365_ROLLUP_COLUMNS
from app.enrich.networks import Places
from app.search.m365 import overview, to_dict
from app.search.m365_rollup import M365Rollup
from tests.integration.test_schedules import make_lab
from tests.scale_lake import write_m365

BUDGET_S = 2.0
SOURCES = [("m365", "m365", None)]
PLACES = Places(("US",), (), False, None)


def _timed(engine: object, now: datetime, rollup: M365Rollup | None) -> tuple[float, dict]:
    took = []
    for _ in range(3):
        started = time.perf_counter()
        m = overview(engine, None, SOURCES, PLACES, "30d", now, rollup)  # type: ignore[arg-type]  # the lab's engine
        took.append(time.perf_counter() - started)
    return statistics.median(took), to_dict(m)


def _run(tmp_path: Path, signins: int, activity: int) -> tuple[float, float]:
    engine = make_lab(tmp_path)["app"].state.engine
    now = datetime.now(UTC)
    write_m365(engine._lake, signins, activity, days=61, end=now)
    root = tmp_path / "rollup-m365"
    engine.add_rollup("m365_rollup", root, M365_ROLLUP_COLUMNS)
    rollup = M365Rollup(engine, engine._lake, root, lambda: ["m365"], max_days_per_run=100)
    live_s, live = _timed(engine, now, None)
    report = rollup.run()
    assert report.built == 60 and not report.skipped
    rolled_s, rolled = _timed(engine, now, rollup)
    assert rolled == live  # the same numbers
    print(f"\n30-day Microsoft 365 Overview: events {live_s:.2f} s, rollup {rolled_s:.2f} s")
    return live_s, rolled_s


@pytest.mark.scale
def test_full_size_thirty_days_under_two_seconds(tmp_path: Path) -> None:
    """60,000 sign-ins and 100,000 operations a day, as a 300-person tenant with heavy
    SharePoint use; 61 days so the window before is full."""
    _, rolled_s = _run(tmp_path, signins=60_000, activity=100_000)
    assert rolled_s < BUDGET_S, f"30-day Overview took {rolled_s:.1f} s from the rollup"
