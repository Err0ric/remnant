"""ADR-0041: the Microsoft 365 rollup gives the Overview exactly the numbers events give,
counts a change or consent reported by Graph and the Management API once even across days
and separate sources, reads today from events, and never shows a source the caller may not
read (rule 13)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.engine.duckdb import QueryScope
from app.enrich.networks import Places
from app.ingest.writer import LakeWriter
from app.search.m365 import overview, to_dict
from app.search.m365_rollup import PART, M365Rollup
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
SOURCES = [
    ("m365_signin", "file", "m365_signin"),
    ("m365_graph", "file", "m365_directory_audit"),
    ("m365_mgmt", "file", "m365_management_activity"),
]
PLACES = Places(("US",), (), False, None)
CODES = (0, 0, 0, 50126, 50074, 50053, 0, 50126)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(days: int) -> list[dict[str, Any]]:
    rows = []
    for d in range(days):
        day = NOW.replace(hour=0) - timedelta(days=d)
        for i, code in enumerate(CODES):
            at = day + timedelta(hours=i * 3 % 24, minutes=d)
            if at > NOW:
                continue
            more: dict[str, Any] = {
                "userPrincipalName": f"user{(i + d) % 3}@example.com",
                "ipAddress": f"198.51.100.{i}" if i % 2 else f"203.0.113.{d}",
                "appDisplayName": ["Outlook", "Teams", "SharePoint"][i % 3],
            }
            if i == 3:
                more["riskLevelDuringSignIn"] = "high"
            rows.append(
                _row(
                    "m365_signin", "successful sign-in", "m365_signin",
                    createdDateTime=_iso(at),
                    status={"errorCode": code, "failureReason": f"code {code}"}, **more,
                )
            )  # fmt: skip
        for j, (test, extra) in enumerate(
            [
                ("SharePoint file download", {}),
                ("Copilot interaction", {}),
                ("DLP rule match", {}),
                (
                    "SharePoint file download",
                    {"Operation": "New-InboxRule", "Workload": "Exchange"},
                ),
            ]
        ):
            at = day + timedelta(hours=1 + j, minutes=d)
            if at <= NOW:
                rows.append(
                    _row(
                        "m365_management_activity", test, "m365_mgmt", CreationTime=_iso(at)[:-1],
                        Id=f"6b2f3a10-0000-4000-8000-{d:06d}{j:06d}", **extra,
                    )
                )  # fmt: skip
        # A role grant, from Graph only.
        at = day + timedelta(hours=2)
        if at <= NOW:
            rows.append(
                _row(
                    "m365_directory_audit", "role assignment by a user", "m365_graph",
                    activityDateTime=_iso(at), correlationId=f"role-{d}",
                )
            )  # fmt: skip
    return rows


def _consent_across_midnight() -> list[dict[str, Any]]:
    """One blocked consent: Graph's copy just before midnight, the Management API's just
    after, sharing the correlation id, in two sources and two days."""
    at = NOW.replace(hour=0) - timedelta(days=3)
    graph = _row(
        "m365_directory_audit", "a blocked consent (Entra writes Unknown as the app name)",
        "m365_graph", activityDateTime=_iso(at - timedelta(seconds=10)),
    )  # fmt: skip
    mgmt = _row(
        "m365_management_activity", "the same blocked consent from the Management API",
        "m365_mgmt", CreationTime=_iso(at + timedelta(seconds=10))[:-1],
    )  # fmt: skip
    granted = _row(
        "m365_directory_audit", "a granted admin consent names its app", "m365_graph",
        activityDateTime=_iso(at - timedelta(days=2)),
    )  # fmt: skip
    return [graph, mgmt, granted]


def _lab(tmp_path: Path) -> tuple[Any, M365Rollup]:
    engine = make_lab(tmp_path)["app"].state.engine
    root = tmp_path / "rollup-m365"
    engine._m365_rollup = root
    rollup = M365Rollup(
        engine,
        engine._lake,
        root,
        sources=lambda: [s for s, _, _ in SOURCES],
        clock=lambda: NOW,
        max_days_per_run=500,
    )
    return engine, rollup


def _same(a: Any, b: Any) -> None:
    da, db = to_dict(a), to_dict(b)
    assert da == db


def test_rollup_gives_the_same_overview_as_events(tmp_path: Path) -> None:
    engine, rollup = _lab(tmp_path)
    LakeWriter(engine._lake).write(_rows(40) + _consent_across_midnight())
    report = rollup.run()
    assert report.built >= 3 * 39 and not report.skipped
    for window in ("24h", "7d", "30d"):
        live = overview(engine, None, SOURCES, PLACES, window, NOW)
        rolled = overview(engine, None, SOURCES, PLACES, window, NOW, rollup)
        _same(live, rolled)
    m = overview(engine, None, SOURCES, PLACES, "30d", NOW, rollup)
    assert m.consents is not None and (m.consents.value, m.consents.extra) == (1, 1)
    assert m.sign_ins is not None and m.sign_ins.value > 0
    # The 30-day page (60 days with the window before) read the 39 closed days each
    # source has from the rollup, and today from events.
    scope = QueryScope([s for s, _, _ in SOURCES], m.before, NOW)
    covered = rollup.covered(scope)
    assert len(covered) == 3 * 39
    assert not any(c.endswith(NOW.date().isoformat()) for c in covered)


def test_a_restricted_viewer_reads_only_their_sources(tmp_path: Path) -> None:
    engine, rollup = _lab(tmp_path)
    LakeWriter(engine._lake).write(_rows(10) + _consent_across_midnight())
    rollup.run()
    live = overview(engine, ["m365_signin"], SOURCES, PLACES, "7d", NOW)
    rolled = overview(engine, ["m365_signin"], SOURCES, PLACES, "7d", NOW, rollup)
    _same(live, rolled)
    assert rolled.read == ["m365_signin"]
    assert rolled.consents is not None and rolled.consents.value == 0
    assert all(c.kpi.value == 0 for c in rolled.counts)


def test_late_events_rebuild_the_day_and_a_removed_day_is_dropped(tmp_path: Path) -> None:
    engine, rollup = _lab(tmp_path)
    LakeWriter(engine._lake).write(_rows(5))
    rollup.run()
    day = NOW - timedelta(days=2)
    late = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        createdDateTime=_iso(day.replace(hour=5)),
    )  # fmt: skip
    LakeWriter(engine._lake).write([late])
    # Stale until rebuilt: that day is read from events meanwhile, so the numbers agree.
    scope = QueryScope(["m365_signin"], NOW - timedelta(days=7), NOW)
    assert f"m365_signin|{day.date().isoformat()}" not in rollup.covered(scope)
    _same(
        overview(engine, None, SOURCES, PLACES, "7d", NOW),
        overview(engine, None, SOURCES, PLACES, "7d", NOW, rollup),
    )
    assert rollup.run().built == 1
    assert f"m365_signin|{day.date().isoformat()}" in rollup.covered(scope)
    # Retention removed the lake day: the rollup day goes with it.
    import shutil

    lake_day = engine._lake / "source=m365_signin" / f"day={day.date().isoformat()}"
    shutil.rmtree(lake_day)
    assert rollup.run().removed == 1
    built = tmp_path / "rollup-m365" / "source=m365_signin" / f"day={day.date().isoformat()}"
    assert not (built / PART).exists()
