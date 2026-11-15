"""GET /api/alerts/metrics (D261): sign-in, the Queue's visibility for each role, range
checks, the overdue days from the config, and no audit row for numbers only."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from tests.integration.test_schedules import BASE, NOW, make_lab

URL = "/api/alerts/metrics"


@pytest.fixture
def lab(tmp_path: Path, pin_now: Any) -> dict[str, Any]:
    out = make_lab(tmp_path)
    out["app"].state.alert_items._clock = out["clock"]
    out["clock"].now = NOW - timedelta(days=4)
    items = out["app"].state.alert_items
    items.raise_item("rule", "win", "Windows rule", ref_id="w1", sources=["win_dc"],
                     severity="high")  # fmt: skip
    lin = items.raise_item("rule", "lin", "Linux rule", ref_id="l1", sources=["lin_auth"])
    out["clock"].now = NOW - timedelta(days=3)
    out["app"].state.alert_items.close(
        lin.item_id, out["app"].state.auth.users.get(out["ids"]["ana"]), "resolved", None, None
    )
    pin_now(NOW)
    return out


def audit_rows(lab: dict[str, Any]) -> int:
    with lab["app"].state.meta.connect() as con:
        return int(con.execute("SELECT count(*) FROM audit_log").fetchone()[0])


def test_sign_in_is_required(lab: dict[str, Any]) -> None:
    assert TestClient(lab["app"], base_url=BASE).get(URL).status_code == 401


def test_each_role_counts_only_what_the_queue_shows_it(lab: dict[str, Any]) -> None:
    start = (NOW - timedelta(days=7)).isoformat()
    before = audit_rows(lab)
    admin = lab["admin"].get(URL, params={"start": start})
    assert admin.status_code == 200, admin.text
    a = admin.json()
    assert (a["opened"], a["closed"], a["open"], a["restricted"]) == (2, 1, 1, False)
    assert a["open_by_severity"] == {"high": 1, "medium": 0, "other": 0}
    assert a["overdue_by_severity"]["high"] == 1  # open 4 days, High is 3
    assert a["thresholds"] == {"critical": 1, "high": 3, "medium": 7, "low": 30}
    assert a["time_to_close"] == {"count": 1, "median_s": 86_400, "p90_s": 86_400}
    assert len(a["days"]) == 8 and a["timezone"] == "UTC"
    # Ana and the auditor read Linux only: the Windows alert is never counted, only flagged.
    for who in ("ana", "aud"):
        got = lab[who].get(URL, params={"start": start}).json()
        assert (got["opened"], got["closed"], got["open"], got["overdue"]) == (1, 1, 0, 0)
        assert got["restricted"] is True, who
    # Numbers only: no audit row, like the alert count.
    assert audit_rows(lab) == before


def test_the_range_is_checked(lab: dict[str, Any]) -> None:
    end = NOW.isoformat()
    for params in (
        {"start": end, "end": end},
        {"start": (NOW - timedelta(days=367)).isoformat(), "end": end},
    ):
        res = lab["admin"].get(URL, params=params)
        assert res.status_code == 400, (params, res.text)
    assert lab["admin"].get(URL, params={"start": "yesterday"}).status_code == 422
    # The calendar's edges answer 400, never 500.
    for edge in ("0001-06-01T00:00:00Z", "9999-12-31T23:59:59Z"):
        res = lab["admin"].get(URL, params={"end": edge})
        assert res.status_code == 400 and res.json()["code"], (edge, res.text)
    assert lab["admin"].get(URL, params={"end": end}).status_code == 200


def test_the_default_start_is_fixed_never_from_hidden_alerts(lab: dict[str, Any]) -> None:
    # An older alert Ana cannot read (Windows), and Bob's private one: the default start is
    # 30 days before the end for everyone and tells her nothing about them.
    items = lab["app"].state.alert_items
    lab["clock"].now = NOW - timedelta(days=200)
    items.raise_item("rule", "old", "Old", ref_id="o1", sources=["win_dc"])
    items.raise_item("schedule", "mine", "Private", ref_id="p1",
                     owner_id=lab["ids"]["bob"], shared=False)  # fmt: skip
    for who in ("ana", "admin"):
        got = lab[who].get(URL).json()
        assert got["start"] == (NOW - timedelta(days=30)).isoformat(), who
        assert got["end"] == NOW.isoformat()


def test_open_now_agrees_with_the_queue_up_to_its_200(lab: dict[str, Any]) -> None:
    items = lab["app"].state.alert_items

    def count() -> int:
        return int(lab["admin"].get("/api/alerts/count").json()["open"])

    def metric() -> int:
        return int(lab["admin"].get(URL).json()["open"])

    assert metric() == count() == 1
    for n in range(204):
        items.raise_item("rule", f"bulk{n}", "Bulk", ref_id=f"b{n}")
    # Above 200 the Queue's count reads the newest 200 open alerts; this is the full count.
    assert (metric(), count()) == (205, 200)


def test_the_route_uses_the_overdue_days_of_the_apps_config(lab: dict[str, Any]) -> None:
    def high() -> tuple[int, int]:
        got = lab["admin"].get(URL).json()
        return got["thresholds"]["high"], got["overdue_by_severity"]["high"]

    # The High Windows alert has been open 4 days: overdue at 3 days, not at 5.
    assert high() == (3, 1)
    lab["app"].state.config.alerts.overdue_days_high = 5
    assert high() == (5, 0)


def test_the_overdue_days_come_from_the_config(tmp_path: Path) -> None:
    cfg = load_config(Path("missing.yaml"), {"APP__ALERTS__OVERDUE_DAYS_HIGH": "5"})
    assert cfg.alerts.overdue_days_high == 5 and cfg.alerts.overdue_days_low == 30
    with pytest.raises(Exception, match="overdue_days_medium"):
        load_config(Path("missing.yaml"), {"APP__ALERTS__OVERDUE_DAYS_MEDIUM": "0"})
