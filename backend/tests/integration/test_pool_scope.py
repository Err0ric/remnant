"""D146 scope (owner, 2026-11-01): with `server.query_pool` on, only Remnant's own
page-section SQL may use a kept DuckDB instance. Search, exports, facets, saved and
scheduled searches, and every Ask (model-written) query get a new instance limited to the
caller's source folders, because Ask runs SQL written by a model that reads untrusted log
content (ATLAS AML.T0051.001, AML.T0057)."""

from pathlib import Path
from typing import Any

from tests.integration import test_ask, test_schedules
from tests.integration.test_schedules import run_now, schedule


def _watch(app: Any) -> list[str]:
    """Turn the pool on and record every kept instance handed out."""
    engine = app.state.engine
    engine.pool = True
    taken: list[str] = []
    real = engine._take_kept

    def take() -> Any:
        taken.append("kept")
        return real()

    engine._take_kept = take
    return taken


def test_search_exports_facets_and_ask_never_use_a_kept_instance(tmp_path: Path) -> None:
    lab = test_ask.make_lab(tmp_path)
    taken = _watch(lab["app"])
    admin, h = lab["admin"], lab["h"]
    body = {"sql": test_ask.SQL}
    assert admin.post("/api/query", json=body, headers=h).status_code == 200
    assert admin.post("/api/query/export", json=body, headers=h).status_code == 200
    assert admin.post("/api/search/facets", json={"text": ""}, headers=h).status_code == 200
    # Ask: a preview tool call, then the answer; the self-check previews the final SQL too.
    lab["script"].replies = [
        test_ask.tool("preview_query", {"sql": "SELECT source_id FROM events"}),
        test_ask.answer(test_ask.SQL),
    ]
    res = test_ask.ask(test_ask.login(lab, "ana"))
    assert res.status_code == 200, res.text
    assert taken == []
    # A page section, the control: it does take one.
    assert admin.get("/api/ai/usage").status_code == 200
    assert taken


def test_saved_and_scheduled_searches_never_use_a_kept_instance(tmp_path: Path) -> None:
    lab = test_schedules.make_lab(tmp_path)
    taken = _watch(lab["app"])
    ran = lab["ana"].post(
        "/api/searches/failed_ssh/run",
        json={"params": {}, "start": "2026-10-01T00:00:00Z", "end": "2026-10-11T00:00:00Z"},
    )
    assert ran.status_code == 200, ran.text
    s = schedule(lab["ana"]).json()
    assert run_now(lab, lab["ana"], s["schedule_id"]).status_code == 200
    assert taken == []
