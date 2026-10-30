"""AI usage on a busy DNS source (install finding F46): every tab answers within a small
per-query memory share, without spilling to disk, because each query reduces events to
small groups before any join. The full-size run (300k a day for 30 days) is `-m scale`."""

import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.config import load_config
from app.main import create_app
from tests.scale_lake import write_dns, write_identity


def _app(
    tmp: Path, lake: Path, memory_mb: int | None, spill: bool, env: dict[str, str] | None = None
) -> TestClient:
    config = load_config(
        Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data"), **(env or {})}
    )
    app = create_app(config)
    dest = app.state.engine._lake
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(lake, dest)
    if memory_mb is not None:
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


# The dashboard's first section answers well inside a page load (F63). Before F63 this run
# took 33 s (7 days) and 43 s (30 days) on a 2 vCPU runner, and failed with query_memory
# on a 4 GB install with real resolver data.
SUMMARY_BUDGET_S = 10.0


@pytest.mark.scale
def test_full_size_300k_a_day_for_30_days(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    end = datetime.now(UTC)
    write_dns(lake, per_day=300_000, days=30, end=end, names=150_000, daily_names=True)
    write_identity(lake, days=30, end=end)
    # The default share of a 4 GB server (D80), as on the install that found F63.
    c = _app(
        tmp_path, lake, memory_mb=None, spill=True, env={"APP__SERVER__MEMORY_LIMIT_MB": "4096"}
    )
    rollup = c.app.state.ai_rollup  # type: ignore[attr-defined]  # the app under test
    rollup._max = 1000
    assert rollup.run().built > 0
    for days in (1, 7, 30):
        _every_tab(c, days)
    for days in (7, 30):
        started = time.perf_counter()
        res = c.get("/api/ai/watch/summary", params={"days": days})
        took = time.perf_counter() - started
        assert res.status_code == 200, res.text
        assert took < SUMMARY_BUDGET_S, f"AI Watch summary ({days} days) took {took:.1f} s"
        assert res.json()["top"], "AI use in the data"


def test_too_little_memory_is_a_server_limit_with_its_own_code(tmp_path: Path) -> None:
    """A server-side memory limit is not a bad request: 503 with its own code, logged at
    WARN with the request id and which query it was (F63)."""
    lake = tmp_path / "lake"
    write_dns(lake, per_day=50_000, days=2, end=datetime.now(UTC))
    c = _app(tmp_path, lake, memory_mb=16, spill=True)
    start = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with capture_logs() as logs:
        res = c.get("/api/ai/usage", params={"start": start})
    assert res.status_code == 503
    assert res.json()["code"] == "query_memory"
    assert res.json()["detail"].startswith("The query needs more memory")
    warn = [e for e in logs if e["event"] == "query.memory"]
    assert warn and warn[0]["log_level"] == "warning"
    assert warn[0]["request_id"] == res.headers["X-Request-ID"]
    assert warn[0]["query"].startswith("ai_use.")


@pytest.mark.scale
def test_people_on_closed_days_fit_the_default_share(tmp_path: Path) -> None:
    """Owner, 2026-10-29 (install on 15ac401): 300k DNS a day and 100k Linux sign-ins a
    day for 30 days, with a rollup built before the identity files existed. Every AI page
    loads under the default share of a 4 GB server while the re-check is pending (without
    people for those days), and after it (with people). On 15ac401 these pages failed with
    query_memory: days not yet checked were read from events."""
    lake = tmp_path / "lake"
    end = datetime.now(UTC)
    write_dns(lake, per_day=300_000, days=30, end=end, names=150_000, daily_names=True)
    write_identity(lake, days=30, end=end, logons_per_day=100_000)
    c = _app(
        tmp_path, lake, memory_mb=None, spill=True, env={"APP__SERVER__MEMORY_LIMIT_MB": "4096"}
    )
    rollup = c.app.state.ai_rollup  # type: ignore[attr-defined]  # the app under test
    rollup._max = 1000
    assert rollup.run().built > 0
    # As built by an earlier version: no identity file, no identity flag.
    for f in rollup._dir.glob("source=*/day=*/ident.parquet"):
        f.unlink()
    for m in rollup._dir.glob("source=*/day=*/_built.json"):
        body = json.loads(m.read_text())
        body.pop("identity", None)
        m.write_text(json.dumps(body))

    # Every AI use query must leave the closed days to the rollup: on 15ac401 the days
    # not yet checked were read from events, which ran out of memory on the install.
    engine = c.app.state.engine  # type: ignore[attr-defined]
    real_run = engine.run
    skipped: list[frozenset[str]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        scope = args[1] if len(args) > 1 else kwargs.get("scope")
        week_ago = end - timedelta(days=6)
        if (
            str(kwargs.get("name", "")).startswith("ai_use.")
            and scope is not None
            and scope.start is not None
            and scope.start <= week_ago
            and (scope.end is None or scope.end >= end - timedelta(days=1))
        ):
            skipped.append(frozenset(kwargs.get("skip_days") or ()))
        return real_run(*args, **kwargs)

    engine.run = spy
    today = end.date().isoformat()
    closed = {
        f"{d.parent.name.removeprefix('source=')}|{d.name.removeprefix('day=')}"
        for d in engine._lake.glob("source=*/day=*")
        if d.name != f"day={today}" and d.name > f"day={(end - timedelta(days=6)).date()}"
    }

    def pages() -> dict[str, Any]:
        for days in (7, 30):
            res = c.get("/api/ai/watch/summary", params={"days": days})
            assert res.status_code == 200, res.text
        return _every_tab(c, days=30)

    body = pages()
    assert skipped and all(closed <= s for s in skipped), "closed days read from events"
    assert body["people_pending_days"] > 0 and body["people_days"] >= body["people_pending_days"]
    while rollup.recheck(budget_s=600):
        pass
    body = pages()
    assert body["people_pending_days"] == 0
    assert any(s["people"] > 0 for s in body["services"]), "people from DHCP and sign-ins"
