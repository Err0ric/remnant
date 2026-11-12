"""ADR-0049 0c: a vendor alert that rises after its item was closed opens a new item linked
to the closed one (the close and its reason stay), and the starter CEF alert template."""

import re
from pathlib import Path
from typing import Any

import pytest

from app.alerts.external import ExternalAlerts
from app.ingest.normalizer import SourceSpec
from app.ingest.records import DecodedLine
from app.templates.registry import STARTER_DIR, TemplateRegistry
from app.templates.router import AutoNormalizer
from tests.integration.test_external_alerts import T, _ext, _Registry, _send
from tests.integration.test_schedules import make_lab
from tests.unit.test_alert_templates import ALERT, template

STARTER = TemplateRegistry(STARTER_DIR, Path("/nonexistent"))
SAMPLE = Path(__file__).parents[1] / "fixtures" / "logs" / "cef_alerts" / "sample.log"


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    app = out["app"]
    out["t"] = template()
    out["watch"] = ExternalAlerts(
        app.state.engine, app.state.meta, app.state.alert_items, _Registry(out["t"])
    )
    out["at"] = T
    return out


def _close(lab: dict[str, Any], item_id: str, reason: str = "resolved") -> None:
    res = lab["admin"].post(
        f"/api/alerts/{item_id}/close", json={"reason": reason}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text


def test_a_rise_on_a_closed_item_opens_a_linked_item(lab: dict[str, Any]) -> None:
    _send(lab, ALERT.replace("|9|", "|5|"))
    (first,) = _ext(lab)
    _close(lab, first["item_id"])
    _send(lab, ALERT)  # the same vendor alert, now High
    items = {i["item_id"]: i for i in _ext(lab)}
    assert len(items) == 2
    old = items[first["item_id"]]
    assert old["state"] == "closed" and old["close_reason"] == "resolved"  # left as decided
    (new,) = (i for i in items.values() if i["item_id"] != first["item_id"])
    assert new["state"] == "open" and new["severity"] == "high"
    assert new["follows"] == first["item_id"]
    assert new["detail"].startswith("Follows an earlier alert closed as Resolved.")
    assert "rose to high after an earlier alert was closed" in new["changes"][0]
    detail = lab["admin"].get(f"/api/alerts/{new['item_id']}").json()
    assert detail["follows"] == first["item_id"] and detail["alert_ids"]["count"] == 1
    _send(lab, ALERT)  # a resend at the same level: nothing new
    assert len(_ext(lab)) == 2


def test_a_resend_on_a_closed_item_at_the_same_level_raises_nothing(lab: dict[str, Any]) -> None:
    _send(lab, ALERT)
    (first,) = _ext(lab)
    _close(lab, first["item_id"], "expected")
    _send(lab, ALERT)
    (only,) = _ext(lab)
    assert only["state"] == "closed" and only["follows"] is None


def test_the_starter_alert_template_is_never_picked_automatically() -> None:
    t = STARTER.get("cef_alerts")
    assert t is not None and t.emits == "alerts"
    auto = AutoNormalizer(
        SourceSpec(source_id="mixed", format="syslog"),
        STARTER.all(),
        STARTER.starter_ids,
        clock=lambda: T,
        tables=STARTER.tables,
    )
    row = auto.normalize(DecodedLine(text=ALERT, bytes_invalid=False, truncated=False))
    assert row["template_id"] == "cef_generic" and row["class_uid"] != 2004


def test_the_starter_alert_sample_raises_one_key_per_vendor_alert(lab: dict[str, Any]) -> None:
    t = STARTER.get("cef_alerts")
    assert t is not None
    lab["t"] = t
    lab["watch"] = ExternalAlerts(
        lab["app"].state.engine, lab["app"].state.meta, lab["app"].state.alert_items,
        _Registry(t),
    )  # fmt: skip
    # The sample is dated 9 October; move it to the lab's day so it is inside the look-back.
    lines = [
        x.replace("Oct  9", "Nov  9").replace("2026-10-09T", "2026-11-09T")
        for x in SAMPLE.read_text().splitlines()
    ]
    _send(lab, *lines)
    found = [re.search(r"CEF:0\|(\w+)\|(\w+)\|.*externalId=(\S+)", x) for x in lines]
    wanted = {(f"{m[1]} {m[2]}", m[3]) for m in found if m}
    assert len(wanted) > 40  # resends share an ID
    with lab["app"].state.meta.connect() as con:
        keys = {
            (r[0], r[1]) for r in con.execute("SELECT product, alert_id FROM external_alert_keys")
        }
    assert keys == wanted
    assert len(_ext(lab)) >= 1
