"""ADR-0049 Phase 0: alerts from an approved `emits: alerts` template become alert items,
one per product and vendor alert ID, grouped as D200 says, through the guarded engine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.alerts.external import ExternalAlerts
from app.ingest.records import DecodedLine
from app.ingest.writer import LakeWriter
from app.templates.runtime import TemplateNormalizer
from app.templates.validator import Template
from tests.integration.test_schedules import make_lab
from tests.unit.test_alert_templates import ALERT, template

T = datetime(2026, 11, 9, 21, 0, tzinfo=UTC)


class _Registry:
    def __init__(self, *templates: Template) -> None:
        self._t = list(templates)

    def all(self) -> list[Template]:
        return self._t


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


def _send(lab: dict[str, Any], *lines: str) -> None:
    lab["at"] += timedelta(minutes=2)
    at = lab["at"]
    norm = TemplateNormalizer(lab["t"], "edr", clock=lambda: at)
    rows = [
        norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False)) for x in lines
    ]
    LakeWriter(lab["app"].state.engine._lake).write(rows)
    lab["watch"].tick(at + timedelta(minutes=1))


def _ext(lab: dict[str, Any]) -> list[dict[str, Any]]:
    res = lab["admin"].get("/api/alerts?state=all")
    assert res.status_code == 200, res.text
    return [i for i in res.json()["items"] if i["subject"].startswith("ext:")]


def test_an_alert_raises_one_item_and_a_resend_raises_nothing(lab: dict[str, Any]) -> None:
    _send(lab, ALERT)
    (item,) = _ext(lab)
    assert item["kind"] == "rule" and item["severity"] == "high"
    assert item["title"] == "Credential dumping detected"
    assert item["why"] == "Alert from ExampleCorp EdgeSensor"
    assert item["people"] == ["alice"] and item["sources"] == ["edr"]
    _send(lab, ALERT)  # the vendor sends the same alert again
    (again,) = _ext(lab)
    assert again["item_id"] == item["item_id"] and again["count"] == item["count"]


def test_another_alert_on_the_same_person_adds_to_the_open_item(lab: dict[str, Any]) -> None:
    _send(lab, ALERT)
    _send(lab, ALERT.replace("A-1001", "A-1002"))
    (item,) = _ext(lab)
    assert item["count"] == 2


def test_a_resend_at_a_higher_severity_raises_the_item(lab: dict[str, Any]) -> None:
    _send(lab, ALERT.replace("|9|", "|5|"))
    assert _ext(lab)[0]["severity"] == "medium"
    _send(lab, ALERT)
    (item,) = _ext(lab)
    assert item["severity"] == "high"


def test_a_short_alert_is_stored_but_raises_nothing(lab: dict[str, Any]) -> None:
    short = ALERT.replace("externalId=A-1001 ", "")
    _send(lab, short)
    assert _ext(lab) == []
    sql = "SELECT parse_status, raw FROM events WHERE source_id = 'edr'"
    res = lab["admin"].post("/api/query", json={"sql": sql}, headers=lab["h"])
    assert res.json()["rows"] == [["partial", short]]


def test_a_low_alert_has_no_badge_and_says_its_level(lab: dict[str, Any]) -> None:
    _send(lab, ALERT.replace("|9|", "|2|"))
    (item,) = _ext(lab)
    assert item["severity"] is None
    assert item["why"] == "Alert from ExampleCorp EdgeSensor, low severity"


def test_no_alert_template_means_no_query(lab: dict[str, Any]) -> None:
    app = lab["app"]
    idle = ExternalAlerts(app.state.engine, app.state.meta, app.state.alert_items, _Registry())
    assert idle.tick(T) == 0


def _detail(lab: dict[str, Any], item_id: str) -> dict[str, Any]:
    res = lab["admin"].get(f"/api/alerts/{item_id}")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_grouped_alerts_are_all_listed_and_either_one_finds_the_item(
    lab: dict[str, Any],
) -> None:
    _send(lab, ALERT.replace("|9|", "|5|"))
    _send(lab, ALERT.replace("A-1001", "A-1002").replace("|9|", "|5|"))
    (item,) = _ext(lab)
    assert "alert_ids" not in item or item["alert_ids"] is None  # never on the list
    ids = _detail(lab, item["item_id"])["alert_ids"]
    assert ids["count"] == 2
    assert [i["alert_id"] for i in ids["ids"]] == ["A-1001", "A-1002"]
    # The second alert resent at a higher severity finds the same item and raises it.
    _send(lab, ALERT.replace("A-1001", "A-1002"))
    (again,) = _ext(lab)
    assert again["item_id"] == item["item_id"] and again["severity"] == "high"
    # Show alert events: both vendor alerts' lines, from a server-built query.
    res = lab["admin"].get(f"/api/alerts/{item['item_id']}/events")
    assert res.status_code == 200, res.text
    got = res.json()
    col = got["columns"].index("alert_id")
    assert sorted({r[col] for r in got["rows"]}) == ["A-1001", "A-1002"]
    assert len(got["rows"]) == 3


def test_events_and_ids_follow_the_items_access(lab: dict[str, Any]) -> None:
    _send(lab, ALERT)
    (item,) = _ext(lab)
    # ana (analyst) is in a Linux group only: the item read `edr`, so it is not hers.
    for path in ("", "/events", "/alert-ids"):
        res = lab["ana"].get(f"/api/alerts/{item['item_id']}{path}")
        assert res.status_code in (403, 404), (path, res.status_code)


def test_five_thousand_alerts_in_one_item_stay_fast(lab: dict[str, Any]) -> None:
    """D228: the ID list pages (count and first 50; Show all through the API) and the
    events query binds the stored keys as one list, so a 5,000-alert item keeps Alerts
    inside the speed rule (no page more than 100 ms slower)."""
    import time

    app = lab["app"]
    _send(lab, ALERT)
    (item,) = _ext(lab)

    # Owner, 2026-11-10: shape, not wall clock (the speed check times Alerts). The vendor
    # alert keys live in the metadata database, so its statements are what is checked: the
    # list and the detail run the same statements with 1 or 5,001 keys, every read of the
    # keys is a count or one LIMITed page, and neither answer carries the whole ID list.
    from contextlib import contextmanager

    meta = app.state.meta
    real_connect = meta.connect

    def shape(path: str) -> tuple[int, str]:
        sqls: list[str] = []

        @contextmanager
        def traced(*a: Any, **kw: Any) -> Any:
            with real_connect(*a, **kw) as con:
                con.set_trace_callback(sqls.append)
                try:
                    yield con
                finally:
                    con.set_trace_callback(None)

        meta.connect = traced
        try:
            res = lab["admin"].get(path)
        finally:
            meta.connect = real_connect
        assert res.status_code == 200, res.text
        keys = [
            q
            for q in sqls
            if "external_alert_keys" in q and q.lstrip().upper().startswith("SELECT")
        ]
        assert all("count(" in q.lower() or "LIMIT" in q.upper() for q in keys), keys
        if path != "/api/alerts":  # not vacuous: the detail does read the keys
            assert keys, sqls
        return len(sqls), res.text

    paths = ("/api/alerts", f"/api/alerts/{item['item_id']}")
    before = [shape(p)[0] for p in paths]
    events = f"/api/alerts/{item['item_id']}/events?limit=200"

    def timed() -> float:
        t0 = time.perf_counter()
        assert lab["admin"].get(events).status_code == 200
        return time.perf_counter() - t0

    # The same call on the same machine with the item's one key, before the 5,000 come: a
    # baseline measured in this run, so the bound follows the machine's load (handoff's
    # standing advice for timing tests).
    baseline = min(timed() for _ in range(3))
    at = lab["at"]
    norm = TemplateNormalizer(lab["t"], "edr", clock=lambda: at)
    lines = [ALERT.replace("A-1001", f"B-{n:05d}") for n in range(5_000)]
    rows = [
        norm.normalize(DecodedLine(text=x, bytes_invalid=False, truncated=False)) for x in lines
    ]
    LakeWriter(app.state.engine._lake).write(rows)
    with app.state.meta.connect() as con:
        con.executemany(
            "INSERT INTO external_alert_keys"
            " (product, alert_id, item_id, severity, first_seen, last_seen)"
            " VALUES ('ExampleCorp EdgeSensor', ?, ?, 'high', ?, ?)",
            [(f"B-{n:05d}", item["item_id"], f"{at:%FT%T}.{n:06d}", at.isoformat())
             for n in range(5_000)],
        )  # fmt: skip
    after = [shape(p) for p in paths]
    assert [n for n, _ in after] == before
    assert all(text.count("B-0") <= 50 for _, text in after)  # the first page of IDs only
    ids = _detail(lab, item["item_id"])["alert_ids"]
    assert ids["count"] == 5_001 and len(ids["ids"]) == 50
    page = lab["admin"].get(f"/api/alerts/{item['item_id']}/alert-ids?offset=5000&limit=200")
    assert [i["alert_id"] for i in page.json()["ids"]] == ["B-04999"]
    # Owner, 2026-11-10: the shape is checked, not a tight wall clock (the speed check
    # covers real slowdowns): one engine query, the keys bound as one list parameter (no
    # literal IN list in the SQL), and one page of rows.
    engine = app.state.engine
    real_run = engine.run
    calls: list[tuple[str, dict[str, Any]]] = []

    def spy(sql: str, scope: Any, params: Any = None, *a: Any, **kw: Any) -> Any:
        calls.append((sql, dict(params or {})))
        return real_run(sql, scope, params, *a, **kw)

    engine.run = spy
    try:
        t0 = time.perf_counter()
        res = lab["admin"].get(events)
        took = time.perf_counter() - t0
    finally:
        engine.run = real_run
    assert res.status_code == 200 and len(res.json()["rows"]) == 200
    (sql, params), *rest = calls
    assert not rest, [c[0][:80] for c in rest]
    assert "B-0" not in sql and "unnest($keys)" in sql
    assert len(params["keys"]) == 5_001 and params["limit"] == 200
    # A ceiling for a hang, not a speed rule: measured at about 30 times the one-key call
    # on a quiet machine (0.50 s against 0.016 s), so 100 times it under a load that slows
    # both alike, and never less than the old fixed 5 s (a burst can arrive between the
    # two timings), which failed once at a machine load of about 12. Still catches a hang.
    assert took < max(5.0, 100 * baseline), (took, baseline)
