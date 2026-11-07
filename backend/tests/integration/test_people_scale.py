"""People and devices load time on a busy lake (owner, 2026-11-07): 30 days of DNS and
firewall traffic beside sign-ins with a password spray and Claude Code hooks, timed phase
by phase from the Server-Timing header, median of 3 loads, with closed days already in
the rollups as on a running install. The full-size run is
`-m scale`; it prints the table the PR and release note quote."""

import re
import shutil
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from tests.scale_lake import write_dns, write_people

RUNS = 3


def _phases(header: str) -> dict[str, float]:
    return {m[1]: float(m[2]) for m in re.finditer(r"(\w+);dur=([0-9.]+)", header)}


def time_people(tmp: Path, per_day: int, days: int = 30) -> dict[str, float]:
    """Median milliseconds per Server-Timing part over RUNS loads of the 30-day page."""
    lake = tmp / "lake"
    now = datetime.now(UTC)
    rows = write_dns(lake, per_day=per_day, days=days, end=now, names=5000)
    rows += write_people(lake, days=days, end=now, per_day=per_day)
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data")})
    app = create_app(config)
    dest = app.state.engine._lake
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(lake, dest)
    # As on a running install: closed days are already in the rollups.
    for rollup in (app.state.ai_rollup, app.state.auth_rollup, app.state.m365_rollup):
        rollup._max = 1000
        rollup.run()
    c = TestClient(app, base_url="http://127.0.0.1")
    start = (now - timedelta(days=days)).isoformat()
    runs: list[dict[str, float]] = []
    for _ in range(RUNS):
        r = c.get("/api/entities/risk", params={"start": start})
        assert r.status_code == 200, r.text
        runs.append(_phases(r.headers["server-timing"]))
    body = r.json()
    assert body["users"] and body["ips"] and body["hosts"] and body["targeted"]
    names = list(dict.fromkeys(n for run in runs for n in run))
    median = {n: statistics.median(run.get(n, 0.0) for run in runs) for n in names}
    print(f"\nPeople and devices, {rows:,} rows over {days} days, median of {RUNS} (ms)")
    for n, ms in median.items():
        print(f"| {n} | {ms:,.0f} |")
    return median


def test_small_lake_reports_every_phase(tmp_path: Path) -> None:
    """The quick run: the header names the parts the table is made of."""
    got = time_people(tmp_path, per_day=2000, days=3)
    assert {"signals_seen", "people_split", "scoring", "total"} <= set(got)


@pytest.mark.scale
def test_thirty_days_busy_office(tmp_path: Path) -> None:
    """100,000 DNS and 100,000 firewall rows a day, 40,000 sign-ins (most of them a
    spray), and 2,000 hook events: about 7 million rows over 30 days."""
    time_people(tmp_path, per_day=100_000)
