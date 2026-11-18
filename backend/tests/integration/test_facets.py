"""Facet counts for the search on screen (ADR-0016 row 2)."""

from typing import Any

import pytest

from app.api import query as query_api
from app.core.errors import QueryTimeoutError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import facet_days
from tests.integration.test_schedules import make_lab


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return make_lab(tmp_path_factory.mktemp("facets"))


def facets(client: Any, body: dict[str, Any], h: dict[str, str] | None = None) -> Any:
    return client.post("/api/search/facets", json=body, headers=h or {})


def compiled(lab: dict[str, Any], text: str) -> dict[str, Any]:
    c = lab["admin"].post("/api/search/compile", json={"text": text}, headers=lab["h"]).json()
    return {"sql": c["sql"], "params": c["params"]}


def by_facet(res: Any) -> dict[str, dict[str | None, int]]:
    assert res.status_code == 200, res.text
    out: dict[str, dict[str | None, int]] = {}
    for f in res.json()["facets"]:
        out[f["field"]] = {v["value"]: v["count"] for v in f["values"]}
    return out


def test_counts_match_the_search_and_cover_the_whole_result(lab: dict[str, Any]) -> None:
    got = by_facet(facets(lab["admin"], {"text": ""}, lab["h"]))
    totals = (
        lab["admin"]
        .post(
            "/api/query",
            json={"sql": "SELECT source_id, count(*) FROM events GROUP BY 1"},
            headers=lab["h"],
        )
        .json()["rows"]
    )
    assert got["source_id"] == {str(s): int(n) for s, n in totals}
    assert "device_hostname" in got


def test_simple_search_filters_apply_over_every_facet_column(lab: dict[str, Any]) -> None:
    got = by_facet(facets(lab["admin"], {"text": "source:lin_auth"}, lab["h"]))
    assert list(got["source_id"]) == ["lin_auth"]
    assert 0 < len(got["src_endpoint_ip"]) <= 10  # not in the Simple result columns, still counted


def test_sql_mode_counts_only_known_columns_the_result_has(lab: dict[str, Any]) -> None:
    body = compiled(lab, "source:lin_auth")
    got = by_facet(
        facets(lab["admin"], {**body, "columns": ["source_id", "raw", "nope"]}, lab["h"])
    )
    assert set(got) == {"source_id"}  # raw and unknown names ignored


def test_sql_mode_counts_over_the_query(lab: dict[str, Any]) -> None:
    sql = "SELECT source_id, device_hostname FROM events WHERE source_id = 'win_dc';"
    got = by_facet(facets(lab["admin"], {"sql": sql, "columns": ["source_id"]}, lab["h"]))
    assert list(got["source_id"]) == ["win_dc"]


def test_guard_and_scope_still_apply(lab: dict[str, Any]) -> None:
    bad = facets(lab["admin"], {"sql": "DELETE FROM events", "columns": ["source_id"]}, lab["h"])
    assert bad.status_code == 400
    # ana may read only the Linux group: Windows events never show up in her counts.
    got = by_facet(facets(lab["ana"], {"sql": "SELECT * FROM events", "columns": ["source_id"]}))
    assert set(got["source_id"]) == {"lin_auth"}


def test_audited(lab: dict[str, Any]) -> None:
    facets(lab["admin"], {"sql": "SELECT * FROM events", "columns": ["source_id"]}, lab["h"])
    with lab["app"].state.meta.connect() as con:
        row = con.execute(
            "SELECT outcome FROM audit_log WHERE action = 'query.facets' ORDER BY rowid DESC"
        ).fetchone()
    assert row[0] == "success"


def test_sql_mode_click_adds_a_quoted_filter_that_runs(lab: dict[str, Any]) -> None:
    sql = "SELECT time, source_id, message FROM events ORDER BY time DESC LIMIT 500"
    res = lab["admin"].post(
        "/api/query/refine",
        json={"sql": sql, "field": "source_id", "value": "lin_auth"},
        headers=lab["h"],
    )
    assert res.status_code == 200, res.text
    refined = res.json()["sql"]
    assert "source_id = 'lin_auth'" in refined and "LIMIT 500" in refined
    rows = lab["admin"].post("/api/query", json={"sql": refined}, headers=lab["h"]).json()["rows"]
    assert rows and {r[1] for r in rows} == {"lin_auth"}

    out = lab["admin"].post(
        "/api/query/refine",
        json={"sql": sql, "field": "actor_user_name", "value": "x' OR 1=1 --", "exclude": True},
        headers=lab["h"],
    )
    assert "IS DISTINCT FROM 'x'' OR 1=1 --'" in out.json()["sql"]  # a literal, never SQL


@pytest.mark.parametrize(
    "body",
    [
        {"sql": "SELECT * FROM events", "field": "raw", "value": "x"},
        {"sql": "SELECT 1 UNION SELECT 2", "field": "source_id", "value": "x"},
        {"sql": "SELECT * FROM events; SELECT 1", "field": "source_id", "value": "x"},
    ],
)
def test_refine_refuses_other_fields_and_shapes(lab: dict[str, Any], body: dict[str, Any]) -> None:
    res = lab["admin"].post("/api/query/refine", json=body, headers=lab["h"])
    assert res.status_code == 400


def test_a_whole_range_too_slow_to_count_is_counted_over_the_newest_days_with_matches(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner item P6 (2026-11-17) and the designer's finding on PR 662: the whole count
    stopped for time, so the answer is the newest days with matches, with how many days
    and items; a newer day without matches is passed over, never shown as nothing to
    count; the SQL on screen still fails as before."""
    engine: QueryEngine = lab["admin"].app.state.engine
    real = engine.run
    scopes: list[QueryScope] = []

    def slow_whole(sql: str, scope: QueryScope, *a: Any, **k: Any) -> Any:
        scopes.append(scope)
        if scope.files is None and "GROUPING SETS" in sql:
            raise QueryTimeoutError("Query exceeded 7s and was stopped")
        return real(sql, scope, *a, **k)

    def two_days(e: QueryEngine, sql: str, scope: QueryScope, p: Any, rows: int) -> Any:
        """The lab's events are all on one day: say the Windows files are the newest day
        and the Linux files the day before."""
        files = [f for f, _ in e.newest_files(sql, scope, p)]
        win = frozenset(f for f in files if "source=win_dc" in f)
        return [(win, 1), (frozenset(files) - win, 1)]

    monkeypatch.setattr(engine, "run", slow_whole)
    monkeypatch.setattr(facet_days, "day_batches", two_days)
    res = facets(lab["admin"], {"text": ""}, lab["h"])
    assert res.status_code == 200, res.text
    win = real("SELECT count(*) FROM events WHERE source_id = 'win_dc'", QueryScope(None))
    body = res.json()
    assert (body["sampled_days"], body["sampled_skipped"]) == (1, False)
    assert body["sampled_items"] == win.rows[0][0]
    assert {
        v["value"] for f in body["facets"] if f["field"] == "source_id" for v in f["values"]
    } == {"win_dc"}
    assert scopes[-1].files is not None
    # Every Linux line is on the older "day": the newer one is passed over.
    lin = facets(lab["admin"], {"text": "source:lin_auth"}, lab["h"]).json()
    assert lin["sampled_skipped"] is True and lin["sampled_items"] > 0
    assert {
        v["value"] for f in lin["facets"] if f["field"] == "source_id" for v in f["values"]
    } == {"lin_auth"}
    # No time left to check any day: counting took too long (the panel offers Retry).
    monkeypatch.setattr(query_api, "FACET_TIMEOUT_S", 0.0)
    assert facets(lab["admin"], {"text": "source:lin_auth"}, lab["h"]).status_code == 408
    sql_mode = {"sql": "SELECT * FROM events", "columns": ["source_id"]}
    assert facets(lab["admin"], sql_mode, lab["h"]).status_code == 408


def test_counts_of_the_whole_range_say_nothing_was_left_out(lab: dict[str, Any]) -> None:
    body = facets(lab["admin"], {"text": ""}, lab["h"]).json()
    assert body["sampled_days"] is None and body["sampled_items"] is None
