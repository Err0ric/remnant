"""Simple search end to end (ADR-0009): compile, then run through /query with params."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_schedules import make_lab


@pytest.fixture(scope="module")
def lab(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return make_lab(tmp_path_factory.mktemp("simple"))


def search(client: TestClient, text: str, h: dict[str, str] | None = None, **extra: Any) -> Any:
    c = client.post("/api/search/compile", json={"text": text, **extra}, headers=h or {})
    assert c.status_code == 200, c.text
    body = {"sql": c.json()["sql"], "params": c.json()["params"]}
    res = client.post("/api/query", json=body, headers=h or {})
    assert res.status_code == 200, res.text
    return res.json()


def count(lab: dict[str, Any], where: str) -> int:
    res = lab["admin"].post(
        "/api/query", json={"sql": f"SELECT count(*) FROM events WHERE {where}"}, headers=lab["h"]
    )
    return int(res.json()["rows"][0][0])


def test_words_phrases_and_fields_match_the_same_rows_as_hand_written_sql(
    lab: dict[str, Any],
) -> None:
    a, h = lab["admin"], lab["h"]
    phrase = search(a, '"failed password"', h)
    assert phrase["row_count"] == count(lab, "raw ILIKE '%failed password%'") > 0
    both = search(a, 'sshd "invalid user" -src_ip:203.0.113.9', h)
    expected = count(
        lab,
        "raw ILIKE '%sshd%' AND raw ILIKE '%invalid user%'"
        " AND coalesce(src_endpoint_ip <> '203.0.113.9', true)",
    )
    assert both["row_count"] == expected > 0
    wild = search(a, "src_ip:198.51.100.*", h)
    assert wild["row_count"] == count(lab, "src_endpoint_ip LIKE '198.51.100.%'") > 0


def test_sigma_field_names_read_unmapped_like_rules(lab: dict[str, Any]) -> None:
    res = search(lab["admin"], "EventID:4625", lab["h"])
    assert res["row_count"] == 6  # the rule in make_lab matches the same six events


def test_wildcard_characters_in_values_are_literal(lab: dict[str, Any]) -> None:
    assert search(lab["admin"], "100%", lab["h"])["row_count"] == 0
    assert search(lab["admin"], "zz_zz", lab["h"])["row_count"] == 0


def test_injection_attempts_are_just_values(lab: dict[str, Any]) -> None:
    res = search(lab["admin"], 'user:"x\') OR 1=1 --"', lab["h"])
    assert res["row_count"] == 0


def test_top_values_and_scope(lab: dict[str, Any]) -> None:
    top = search(lab["admin"], "", lab["h"], top="source")
    assert top["columns"] == ["source_id", "events"]
    assert {r[0] for r in top["rows"]} == {"lin_auth", "win_dc"}
    mine = search(lab["ana"], "", top="source")  # ana reads lin_auth only
    assert [r[0] for r in mine["rows"]] == ["lin_auth"]
    assert search(lab["ana"], "EventID:4625")["row_count"] == 0


def test_bad_searches_and_params_are_refused(lab: dict[str, Any]) -> None:
    res = lab["aud"].post("/api/search/compile", json={"text": "(a"})
    assert res.status_code == 400 and "never closed" in res.json()["detail"]
    res = lab["admin"].post(
        "/api/query",
        json={"sql": "SELECT 1", "params": {"Bad-Name": 1}},
        headers=lab["h"],
    )
    assert res.status_code == 422
