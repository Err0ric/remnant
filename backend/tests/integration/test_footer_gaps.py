"""Footer and alerts agree (review item 3, 2026-11-06): a source quiet past its threshold
has an open gap alert, and the overview names that alert on the source, which is what the
Dashboard footer and Health count. The alert keeps counting after its watch is gone (a
source whose quiet alert was turned off while the gap was open)."""

from datetime import timedelta
from typing import Any

from tests.integration.test_quiet_sources import lab, tick, watch  # noqa: F401  # fixture
from tests.integration.test_schedules import NOW


def _gap_alerts(env: dict[str, Any]) -> dict[str, str]:
    items = env["admin"].get("/api/alerts").json()["items"]
    return {i["subject"]: i["item_id"] for i in items if i["kind"] == "gap"}


def _overview(env: dict[str, Any], who: str = "admin") -> dict[str, Any]:
    return {s["source_id"]: s for s in env[who].get("/api/overview").json()["sources"]}


def test_a_quiet_source_has_an_open_gap_alert_and_the_overview_counts_it(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    assert watch(lab, "lin_auth").status_code == 200
    lab["clock"].now = NOW + timedelta(hours=2)
    tick(lab)
    alerts = _gap_alerts(lab)
    assert set(alerts) == {"lin_auth"}
    rows = _overview(lab)
    assert rows["lin_auth"]["gap_alert"] == alerts["lin_auth"]
    assert rows["win_dc"]["gap_alert"] is None
    # Another reader of the source sees the same alert named on it.
    assert _overview(lab, "ana")["lin_auth"]["gap_alert"] == alerts["lin_auth"]

    # The source sends again: the alert is resolved and the gap no longer counts.
    lab["received"]["lin_auth"] = lab["clock"].now
    lab["clock"].now += timedelta(minutes=5)
    tick(lab)
    assert _overview(lab)["lin_auth"]["gap_alert"] is None


def test_the_gap_still_counts_after_its_quiet_alert_is_turned_off(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    assert watch(lab, "lin_auth").status_code == 200
    lab["clock"].now = NOW + timedelta(hours=2)
    tick(lab)
    item = _gap_alerts(lab)["lin_auth"]
    off = lab["admin"].put(
        "/api/sources/lin_auth/watch",
        json={"quiet_after_s": None, "target_ids": []},
        headers=lab["h"],
    )
    assert off.status_code == 200, off.text
    rows = _overview(lab)
    assert rows["lin_auth"]["quiet_since"] is None  # the watch is gone
    assert rows["lin_auth"]["gap_alert"] == item  # the open alert still counts
