"""Handoff item 3 (owner, 2026-11-12): one Dashboard visit writes one audit row, listing
every part it declared, instead of one row per request. The row is written by the first
request, before it is answered, and never held in memory (rule 14). The page-load headers
are client values: without them every request is audited as before, and they never hide
access."""

from pathlib import Path
from typing import Any

import pytest

from app.meta import page_loads
from app.meta.page_loads import PageLoadAudit
from tests.integration.test_ai_people_masking import ai_lab  # noqa: F401  # the fixture
from tests.integration.test_ai_usage import lab  # noqa: F401  # ai_lab's fixture
from tests.integration.test_dashboards import audit
from tests.integration.test_schedules import make_lab

PARTS = ("identity", "attacks", "detections")
DECLARED = "identity,attacks,detections,overview"
WITH_AI = DECLARED + ",ai_watch"  # what the Dashboard declares


def _headers(load: str | None, parts: str = DECLARED, window: str = "7d") -> dict[str, str]:
    if load is None:
        return {}
    return {"X-Page-Load": load, "X-Page-Load-Parts": parts, "X-Page-Load-Window": window}


def _section(client: Any, part: str, h: dict[str, str], window: str = "7d") -> None:
    res = client.get("/api/dashboard/sections", params={"window": window, "part": part}, headers=h)
    assert res.status_code == 200, res.text


def _visit(client: Any, load: str | None, window: str = "7d") -> None:
    """Every request the Dashboard makes that writes an audit row, with one id."""
    h = _headers(load, window=window)
    for part in PARTS:
        _section(client, part, h, window)
    assert client.get("/api/overview", headers=h).status_code == 200


@pytest.fixture
def dash(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    now = [1000.0]  # the page-load map's clock, moved by hand
    out["now"] = now
    out["app"].state.page_loads._now = lambda: now[0]
    return out


def _counts(d: dict[str, Any]) -> list[int]:
    return [len(audit(d, a)) for a in ("dashboard.sections", "overview.view", "dashboard.view")]


def test_one_visit_writes_one_row_with_every_part(dash: dict[str, Any]) -> None:
    before = _counts(dash)
    _visit(dash["ana"], "visit-0001")
    _visit(dash["ana"], "visit-0001")  # a refetch in the same visit adds nothing
    assert _counts(dash) == [before[0], before[1], before[2] + 1]
    row = audit(dash, "dashboard.view")[-1]
    assert row["shown"] == ["attacks", "detections", "identity", "overview"]
    assert row["window"] == "7d" and row["page_load"] == "visit-0001"
    assert row["sources_in_scope"] == ["lin_auth"] and row["started_at"]


def test_the_row_is_written_before_the_first_answer(dash: dict[str, Any]) -> None:
    _section(dash["ana"], "identity", _headers("visit-0001"))
    rows = audit(dash, "dashboard.view")  # read at once: no wait, no loop
    assert len(rows) == 1
    assert rows[0]["shown"] == ["attacks", "detections", "identity", "overview"]


def test_the_overview_first_writes_the_row_with_the_page_window(dash: dict[str, Any]) -> None:
    h = _headers("visit-0001", window="30d")
    assert dash["ana"].get("/api/overview", headers=h).status_code == 200
    for part in PARTS:
        _section(dash["ana"], part, h, "30d")
    rows = audit(dash, "dashboard.view")
    assert len(rows) == 1 and rows[0]["window"] == "30d"


def test_a_part_not_declared_writes_a_second_row(dash: dict[str, Any]) -> None:
    h = _headers("visit-0001", parts="identity,overview")
    _section(dash["ana"], "identity", h)
    _section(dash["ana"], "attacks", h)  # not in the list: its own row at once
    _section(dash["ana"], "attacks", h)  # now covered
    rows = audit(dash, "dashboard.view")
    assert [r["shown"] for r in rows] == [["identity", "overview"], ["attacks"]]


def test_a_changed_source_scope_writes_a_new_row(dash: dict[str, Any]) -> None:
    _visit(dash["ana"], "visit-0001")
    dash["admin"].put(
        f"/api/groups/{dash['gid']}/sources",
        json={"source_ids": ["lin_auth", "win_dc"]},
        headers=dash["h"],
    )
    _section(dash["ana"], "identity", _headers("visit-0001"))
    rows = audit(dash, "dashboard.view")
    assert [r["sources_in_scope"] for r in rows] == [["lin_auth"], ["lin_auth", "win_dc"]]
    assert rows[1]["shown"] == ["attacks", "detections", "identity", "overview"]


def test_another_window_writes_a_new_row(dash: dict[str, Any]) -> None:
    _visit(dash["ana"], "visit-0001")
    _visit(dash["ana"], "visit-0001", window="24h")  # a new window: more was shown
    rows = audit(dash, "dashboard.view")
    assert [r["window"] for r in rows] == ["7d", "24h"]
    assert rows[1]["shown"] == ["attacks", "detections", "identity"]  # the Overview is the same


def test_nothing_is_pending_and_a_restart_loses_nothing(dash: dict[str, Any]) -> None:
    app = dash["app"]
    _visit(dash["ana"], "visit-0001")
    assert len(audit(dash, "dashboard.view")) == 1  # everything already written
    app.state.page_loads = PageLoadAudit(app.state.auth.audit)  # a restart: memory gone
    _visit(dash["ana"], "visit-0001")
    assert len(audit(dash, "dashboard.view")) == 2  # the same id simply writes a row again


def test_two_visits_write_two_rows(dash: dict[str, Any]) -> None:
    before = len(audit(dash, "dashboard.view"))
    _visit(dash["ana"], "visit-0001")
    _visit(dash["ana"], "visit-0002")
    assert len(audit(dash, "dashboard.view")) == before + 2


@pytest.mark.parametrize(
    "h",
    [
        {},
        {"X-Page-Load": "x", "X-Page-Load-Parts": DECLARED},  # not a valid id
        {"X-Page-Load": "visit-0001"},  # no parts list
        {"X-Page-Load": "visit-0001", "X-Page-Load-Parts": "identity,secrets"},
        {"X-Page-Load": "visit-0001", "X-Page-Load-Parts": DECLARED, "X-Page-Load-Window": "1y"},
    ],
)
def test_without_valid_headers_every_request_is_audited_as_before(
    dash: dict[str, Any], h: dict[str, str]
) -> None:
    sections = len(audit(dash, "dashboard.sections"))
    for _ in range(2):
        for part in PARTS:
            _section(dash["ana"], part, h)
    rows = audit(dash, "dashboard.sections")
    assert len(rows) == sections + 6
    assert {r["part"] for r in rows[-6:]} == set(PARTS)
    assert audit(dash, "dashboard.view") == []


def test_the_same_id_after_a_gap_writes_a_new_row(dash: dict[str, Any]) -> None:
    _visit(dash["ana"], "visit-0001")
    dash["now"][0] += page_loads.WINDOW_S
    _visit(dash["ana"], "visit-0001")  # a refetch a minute later: the same visit, skipped
    assert len(audit(dash, "dashboard.view")) == 1
    dash["now"][0] += page_loads.WINDOW_S + page_loads.JITTER_S + 1  # nothing for longer
    _visit(dash["ana"], "visit-0001")
    assert len(audit(dash, "dashboard.view")) == 2


def test_an_id_never_merges_two_users(dash: dict[str, Any]) -> None:
    _visit(dash["ana"], "visit-0001")
    _visit(dash["bob"], "visit-0001")
    assert len(audit(dash, "dashboard.view")) == 2


def test_named_ai_views_keep_their_own_row(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """ADR-0029 G3: AI Watch on the Dashboard still writes `ai.view_people` when it shows
    names, whatever headers the request carries; it is not merged into the visit's row."""
    h = _headers("visit-0001")

    def named() -> int:
        return len(audit(ai_lab, "ai.view_people"))

    before = named()
    res = ai_lab["admin"].get("/api/ai/watch/summary", params={"days": 7}, headers=h)
    assert res.status_code == 200
    assert named() == before + 1
    assert ai_lab["admin"].get("/api/alerts/lines", headers=h).status_code == 200
    assert named() == before + 2


def test_ai_watch_without_names_is_part_of_the_visit_row(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """Owner, 2026-11-12: one row per Dashboard visit. AI Watch that names no one (ana has
    no View people in AI usage) writes no `ai.view` row of its own; the visit's row lists
    it. Its refetches during the visit write nothing."""
    ana, h = ai_lab["ana"], _headers("visit-0002", WITH_AI)
    before = len(audit(ai_lab, "ai.view")), len(audit(ai_lab, "ai.view_people"))
    for _ in range(3):  # the first load and two refetches
        assert ana.get("/api/ai/watch/summary", params={"days": 7}, headers=h).status_code == 200
    assert (len(audit(ai_lab, "ai.view")), len(audit(ai_lab, "ai.view_people"))) == before
    rows = audit(ai_lab, "dashboard.view")
    assert len(rows) == 1 and "ai_watch" in rows[0]["shown"]
    assert rows[0]["sources_in_scope"] == ["claude", "dns"]


def test_ai_watch_with_names_writes_its_row_besides_the_visit_row(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    admin, h = ai_lab["admin"], _headers("visit-0003", WITH_AI)
    before = len(audit(ai_lab, "ai.view")), len(audit(ai_lab, "ai.view_people"))
    assert admin.get("/api/ai/watch/summary", params={"days": 7}, headers=h).status_code == 200
    assert len(audit(ai_lab, "ai.view")) == before[0]
    assert len(audit(ai_lab, "ai.view_people")) == before[1] + 1
    _section(admin, "identity", h)
    rows = audit(ai_lab, "dashboard.view")
    assert len(rows) == 1 and "ai_watch" in rows[0]["shown"]


def test_ai_watch_outside_a_dashboard_visit_keeps_its_ai_view_row(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """The CLI, a script, or a malformed header: audited on its own, as before."""
    ana = ai_lab["ana"]
    before = len(audit(ai_lab, "ai.view"))
    assert ana.get("/api/ai/watch/summary", params={"days": 7}).status_code == 200
    bad = {"X-Page-Load": "x", "X-Page-Load-Parts": "ai_watch"}
    assert ana.get("/api/ai/watch/summary", params={"days": 30}, headers=bad).status_code == 200
    assert len(audit(ai_lab, "ai.view")) == before + 2
    assert audit(ai_lab, "dashboard.view") == []


def test_ai_watch_for_another_range_than_the_visits_is_audited_on_its_own(
    ai_lab: dict[str, Any],  # noqa: F811
) -> None:
    """Review of #544: the visit's row says its window, so it may only cover AI Watch read
    for that window. Another `days`, or a visit that names no window, writes `ai.view` with
    its own `days`, every time, as before."""
    ana, h = ai_lab["ana"], _headers("visit-0004", WITH_AI)  # a 7d visit

    def get(days: int, headers: dict[str, str]) -> None:
        res = ana.get("/api/ai/watch/summary", params={"days": days}, headers=headers)
        assert res.status_code == 200, res.text

    before = len(audit(ai_lab, "ai.view"))
    get(7, h)
    assert len(audit(ai_lab, "ai.view")) == before and len(audit(ai_lab, "dashboard.view")) == 1
    for days in (30, 30, 3):  # not the visit's window; 3 days is no Dashboard window at all
        get(days, h)
    own = audit(ai_lab, "ai.view")[before:]
    assert [d["days"] for d in own] == [30, 30, 3]
    no_window = {k: v for k, v in _headers("visit-0005", WITH_AI).items() if "Window" not in k}
    get(7, no_window)
    assert len(audit(ai_lab, "ai.view")) == before + 4
    assert len(audit(ai_lab, "dashboard.view")) == 1  # nothing was added to a visit row


def test_ai_watch_follows_the_page_to_a_new_window(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """The viewer switches the Dashboard from 7 days to 30 days: the headers carry the new
    window, and the 30-day AI Watch gets its own visit row at once."""
    ana = ai_lab["ana"]
    for days, window in ((7, "7d"), (30, "30d"), (30, "30d")):
        h = _headers("visit-0006", WITH_AI, window)
        assert ana.get("/api/ai/watch/summary", params={"days": days}, headers=h).status_code == 200
    rows = audit(ai_lab, "dashboard.view")
    assert [r["window"] for r in rows] == ["7d", "30d"]
    assert all("ai_watch" in r["shown"] for r in rows)


def test_ai_watch_past_the_visit_cap_writes_ai_view(
    ai_lab: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.meta import page_loads

    monkeypatch.setattr(page_loads, "MAX_LOADS", 0)
    ana, before = ai_lab["ana"], len(audit(ai_lab, "ai.view"))
    h = _headers("visit-0007", WITH_AI)
    assert ana.get("/api/ai/watch/summary", params={"days": 7}, headers=h).status_code == 200
    row = audit(ai_lab, "ai.view")[before:]
    assert len(row) == 1 and row[0]["surface"] == "ai.watch.summary" and row[0]["days"] == 7
    assert row[0]["sources_in_scope"] == ["claude", "dns"]
    assert audit(ai_lab, "dashboard.view") == []


def test_a_whole_visit_without_names_is_one_row(ai_lab: dict[str, Any]) -> None:  # noqa: F811
    """Everything the Dashboard requests in one visit, for a viewer who sees no names:
    its sections, the Overview, and AI Watch, in the order a slow network might deliver
    them. One `dashboard.view` row lists all of it; nothing else is written."""
    ana, h = ai_lab["ana"], _headers("visit-0008", WITH_AI)
    before = len(audit(ai_lab, "ai.view"))
    assert ana.get("/api/ai/watch/summary", params={"days": 7}, headers=h).status_code == 200
    for part in PARTS:
        _section(ana, part, h)
    assert ana.get("/api/overview", headers=h).status_code == 200
    assert ana.get("/api/ai/watch/summary", params={"days": 7}, headers=h).status_code == 200
    rows = audit(ai_lab, "dashboard.view")
    assert len(rows) == 1, rows
    assert rows[0]["shown"] == sorted([*PARTS, "overview", "ai_watch"])
    assert len(audit(ai_lab, "ai.view")) == before
    assert audit(ai_lab, "dashboard.sections") == [] and audit(ai_lab, "overview.view") == []
