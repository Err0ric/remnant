"""The daily AI rollup (ADR-0035 Part 1): closed days built from events, read through a
per-query view scoped like `events`, rebuilt on late events and catalog changes, removed
with retention, never visible to user SQL, and giving AI usage the same answer as events."""

import json
import shutil
from datetime import datetime, timedelta
from typing import Any

import pytest

from app.ai.rollup import AiRollup
from app.ai.usage import Usage
from app.engine.duckdb import QueryScope
from app.ingest.writer import LakeWriter
from tests.integration.test_schedules import NOW, _lake_rows, make_lab


def _dns(source: str, at: datetime, n: int, host: str = "chatgpt.com") -> list[dict[str, Any]]:
    rows = _lake_rows(source, "dns_bind", at, n)
    return [
        {
            **r,
            "dst_endpoint_hostname": host,
            "src_endpoint_ip": f"10.0.0.{5 + i % 3}",
            "classification": "local_only",
        }
        for i, r in enumerate(rows)
    ]


@pytest.fixture
def lab(tmp_path: Any) -> dict[str, Any]:
    out = make_lab(tmp_path)
    app = out["app"]
    lake = app.state.engine._lake
    for back in (1, 2, 3):  # three closed days
        LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(days=back), 6))
    LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(hours=1), 4))  # today, live
    LakeWriter(lake).write(_dns("dns_b", NOW - timedelta(days=2), 5, host="claude.ai"))
    rollup: AiRollup = app.state.ai_rollup
    rollup._clock = lambda: NOW
    out["rollup"] = rollup
    return out


def week() -> QueryScope:
    return QueryScope(None, NOW - timedelta(days=7), NOW)


def _by_service(usage: Usage, scope: QueryScope) -> dict[str, tuple[int, int, int]]:
    found, _ = usage.services(scope)
    return {u.service.id: (u.events, u.people, u.machines) for u in found}


def test_closed_days_are_built_with_classification_and_today_stays_live(
    lab: dict[str, Any],
) -> None:
    report = lab["rollup"].run()
    # Every closed source day is built, the lab's other sources too (with no AI rows).
    assert report.built == 6 and report.removed == 0
    data = lab["rollup"]._dir
    built = {p.parent.parent.name for p in data.glob("source=*/day=*/part-0.parquet")}
    assert {"source=dns_a", "source=dns_b"} <= built
    assert len(list(data.glob("source=dns_a/day=*/part-0.parquet"))) == 3
    today = NOW.date().isoformat()
    assert not (data / "source=dns_a" / f"day={today}").exists()
    rows = (
        lab["app"]
        .state.engine.run(
            "SELECT DISTINCT classification FROM ai_rollup", QueryScope(None), rollup=True
        )
        .rows
    )
    assert rows == [["local_only"]]  # never upgraded (ADR-0035 row 4)
    assert lab["rollup"].run().built == 0  # nothing stale the second time


def test_ai_usage_gives_the_same_answer_from_the_rollup(lab: dict[str, Any]) -> None:
    app = lab["app"]
    live = _by_service(Usage(app.state.engine, app.state.ai_catalog), week())
    lab["rollup"].run()
    covered = lab["rollup"].covered(week())
    assert {c for c in covered if c.startswith("dns_")} == {
        f"dns_a|{(NOW - timedelta(days=d)).date()}" for d in (1, 2, 3)
    } | {f"dns_b|{(NOW - timedelta(days=2)).date()}"}
    assert _by_service(app.state.ai_usage, week()) == live
    assert live["chatgpt"][0] == 3 * 6 + 4  # closed days from the rollup plus today live


def test_the_rollup_is_scoped_like_events_and_hidden_from_user_sql(
    lab: dict[str, Any],
) -> None:
    lab["rollup"].run()
    engine = lab["app"].state.engine
    only_b = QueryScope(["dns_b"], NOW - timedelta(days=7), NOW)
    rows = engine.run("SELECT DISTINCT source_id FROM ai_rollup", only_b, rollup=True).rows
    assert rows == [["dns_b"]]
    assert all(c.startswith("dns_b|") for c in lab["rollup"].covered(only_b))
    res = lab["admin"].post("/api/query", json={"sql": "SELECT * FROM ai_rollup"}, headers=lab["h"])
    assert res.status_code == 400 and "Unknown table" in res.text


def test_late_events_and_catalog_changes_rebuild_and_retention_removes(
    lab: dict[str, Any],
) -> None:
    rollup = lab["rollup"]
    rollup.run()
    lake = lab["app"].state.engine._lake
    LakeWriter(lake).write(_dns("dns_a", NOW - timedelta(days=2, hours=3), 2))  # late
    assert rollup.run().built == 1
    assert _by_service(lab["app"].state.ai_usage, week())["chatgpt"][0] == 3 * 6 + 4 + 2
    key = rollup.catalog_key()
    lab["app"].state.ai_catalog.domain_table = lambda: [("chatgpt", "chatgpt.com")]
    assert rollup.catalog_key() != key
    assert rollup.run().built == 6  # every closed day rebuilt for the new domains
    day = (NOW - timedelta(days=3)).date().isoformat()
    shutil.rmtree(lake / "source=dns_a" / f"day={day}")
    report = rollup.run()
    assert report.removed == 1
    assert not (rollup._dir / "source=dns_a" / f"day={day}").exists()
    manifest = json.loads(next(rollup._dir.glob("source=dns_a/day=*/_built.json")).read_text())
    assert manifest["catalog"] == rollup.catalog_key()
