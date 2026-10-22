"""AI usage on a busy DNS source (install finding F46): every tab answers within a small
per-query memory share, without spilling to disk, because each query reduces events to
small groups before any join. The full-size run (300k a day for 30 days) is `-m scale`."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app
from tests.scale_lake import write_dns


def _app(tmp: Path, lake: Path, memory_mb: int, spill: bool) -> TestClient:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data")})
    app = create_app(config)
    dest = app.state.engine._lake
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(lake, dest)
    app.state.engine._memory_mb = memory_mb
    if not spill:
        # A file where the spill folder should be: any query that needs to spill fails.
        blocker = tmp / "no-spill"
        blocker.write_text("")
        app.state.engine._temp_dir = blocker
    return TestClient(app, base_url="http://127.0.0.1")


def _every_tab(c: TestClient, days: int) -> dict[str, Any]:
    start = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    usage = c.get("/api/ai/usage", params={"start": start})
    assert usage.status_code == 200, usage.text
    agents = c.get("/api/ai/agents")
    assert agents.status_code == 200, agents.text
    overview = c.get("/api/overview")
    assert overview.status_code == 200, overview.text
    body: dict[str, Any] = usage.json()
    return body


def test_thirty_days_of_busy_dns_fit_a_small_share_without_spilling(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    rows = write_dns(lake, per_day=70_000, days=30, end=datetime.now(UTC))
    c = _app(tmp_path, lake, memory_mb=256, spill=False)
    body = _every_tab(c, days=30)
    found = {s["service"]["id"]: s["events"] for s in body["services"]}
    # One row in 50 is an AI name; the 8 names take turns.
    assert sum(found.values()) == rows // 50
    assert {"chatgpt", "claude", "anthropic_api"} <= set(found)


def test_queries_spill_to_the_data_folder(tmp_path: Path) -> None:
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp_path / "data")})
    app = create_app(config)
    assert app.state.engine._temp_dir == tmp_path / "data" / "tmp" / "duckdb"
    assert app.state.engine._temp_dir.is_dir()


@pytest.mark.scale
def test_full_size_300k_a_day_for_30_days(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    write_dns(lake, per_day=300_000, days=30, end=datetime.now(UTC))
    c = _app(tmp_path, lake, memory_mb=1024, spill=True)
    for days in (1, 7, 30):
        _every_tab(c, days)


def test_too_little_memory_is_its_own_error_code(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    write_dns(lake, per_day=50_000, days=2, end=datetime.now(UTC))
    c = _app(tmp_path, lake, memory_mb=16, spill=True)
    start = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    res = c.get("/api/ai/usage", params={"start": start})
    assert res.status_code == 400
    assert res.json()["code"] == "query_memory"
    assert res.json()["detail"].startswith("The query needs more memory")
