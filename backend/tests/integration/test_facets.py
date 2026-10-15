"""Facet counts for the search on screen (ADR-0016 row 2)."""

from typing import Any

import pytest

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
