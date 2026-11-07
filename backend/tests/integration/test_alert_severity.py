"""One severity per alert (review item 2, 2026-11-06): a source gap's severity is stored on
its item and every surface reads that field: the alerts list and detail, the strip counts
the list returns, the overview's quiet sources, and the message sent to alert targets. Gap
items stored before gaps carried a severity get the gap's one at start."""

import json
from datetime import timedelta
from typing import Any

from app.alerts.items import GAP_SEVERITY
from tests.integration.test_quiet_sources import lab, tick, watch  # noqa: F401  # fixture
from tests.integration.test_schedules import NOW


def test_source_gap_alerts_report_one_severity_everywhere(lab: dict[str, Any]) -> None:  # noqa: F811
    for sid in ("lin_auth", "win_dc"):
        assert watch(lab, sid).status_code == 200
    lab["clock"].now = NOW + timedelta(hours=2)
    tick(lab)
    # One gap alert stored before gaps carried a severity (no severity on it).
    legacy = lab["app"].state.alert_items.raise_item(
        "gap", "old_src", "old_src stopped sending", ref_id="old_src@legacy"
    )
    assert legacy.severity is None
    assert lab["app"].state.alert_items.fill_severity() == 1
    assert lab["app"].state.alert_items.fill_severity() == 0  # idempotent

    body = lab["admin"].get("/api/alerts").json()
    gaps = [i for i in body["items"] if i["kind"] == "gap"]
    assert len(gaps) == 3
    assert {i["severity"] for i in gaps} == {GAP_SEVERITY}
    # The strip counts come from the same stored field as the badges.
    want = {"high": 0, "medium": 0, "other": 0}
    for i in body["items"]:
        want[i["severity"] if i["severity"] in ("high", "medium") else "other"] += 1
    assert body["by_severity"] == want
    assert body["by_severity"]["medium"] == 3 and body["by_severity"]["high"] == 0
    # The detail reads the same field.
    one = lab["admin"].get(f"/api/alerts/{gaps[0]['item_id']}").json()
    assert one["severity"] == gaps[0]["severity"]
    # The overview's quiet sources are the ones the gap alerts name.
    quiet = {
        s["source_id"]
        for s in lab["admin"].get("/api/overview").json()["sources"]
        if s["quiet_since"]
    }
    assert quiet == {i["subject"] for i in gaps} - {"old_src"}
    # The message to the alert target carries the item's severity too.
    docs = [json.loads(b) for _, b in lab["rx"].got]
    assert docs and {d["kind"] for d in docs} == {"quiet"}
    assert {d["severity"] for d in docs} == {GAP_SEVERITY}
