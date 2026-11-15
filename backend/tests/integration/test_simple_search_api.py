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


def test_the_logs_page_s_search_reads_newest_first_with_the_same_answer(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With its text, a Simple search reads newest day first (search/newest.py) and gives
    what the SQL alone gives; one audit row per search; SQL not compiled from the text
    sent, or typed SQL, runs as written."""
    from app.api import query as q_mod

    calls: list[str] = []
    real = q_mod.newest_first

    def spy(*a: Any, **k: Any) -> Any:
        calls.append(a[1])
        return real(*a, **k)

    monkeypatch.setattr(q_mod, "newest_first", spy)
    a, h = lab["admin"], lab["h"]
    c = a.post("/api/search/compile", json={"text": "failed"}, headers=h).json()
    body = {"sql": c["sql"], "params": c["params"], "start": "2020-01-01T00:00:00Z"}

    def audited() -> int:
        with lab["app"].state.meta.connect() as con:
            sql = "SELECT count(*) FROM audit_log WHERE action = 'query.run'"
            return int(con.execute(sql).fetchone()[0])

    before = audited()
    plain = a.post("/api/query", json=body, headers=h).json()
    assert calls == []
    stepped = a.post("/api/query", json={**body, "text": "failed"}, headers=h).json()
    assert calls == ["failed"]
    keys = ("columns", "row_count", "truncated", "executed_sql", "sources")
    assert {k: stepped[k] for k in keys} == {k: plain[k] for k in keys}
    assert sorted(map(str, stepped["rows"])) == sorted(map(str, plain["rows"]))
    assert plain["row_count"] > 0
    assert audited() == before + 2  # one row per search, not one per read
    other = a.post("/api/query", json={**body, "text": "accepted"}, headers=h)
    assert other.status_code == 200 and calls == ["failed"]
    edited = {**body, "sql": c["sql"] + " LIMIT 5", "text": "failed"}
    assert a.post("/api/query", json=edited, headers=h).json()["row_count"] <= 5
    assert calls == ["failed"]


def test_the_export_of_a_simple_search_reads_newest_first_with_the_same_rows(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import query as q_mod

    calls: list[str] = []
    real = q_mod.newest_first
    monkeypatch.setattr(
        q_mod, "newest_first", lambda *a, **k: (calls.append(a[1]), real(*a, **k))[1]
    )
    a, h = lab["admin"], lab["h"]
    c = a.post("/api/search/compile", json={"text": "failed"}, headers=h).json()
    body = {"sql": c["sql"], "params": c["params"], "start": "2020-01-01T00:00:00Z"}
    plain = a.post("/api/query/export", json=body, headers=h)
    stepped = a.post("/api/query/export", json={**body, "text": "failed"}, headers=h)
    assert plain.status_code == stepped.status_code == 200 and calls == ["failed"]
    lines = plain.text.splitlines()
    assert len(lines) > 1 and lines[0] == stepped.text.splitlines()[0]
    assert sorted(lines[1:]) == sorted(stepped.text.splitlines()[1:])


def _as_browser(value: Any) -> Any:
    """What JSON.stringify makes of a value: 100.0 goes out as 100."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


@pytest.mark.parametrize(
    "text",
    ["device_hostname:>100", "some_field:>=5", "device_hostname:>2.5", "severity:>-3",
     'user:"100"', "severity_id:>3", "failed"],
)  # fmt: skip
def test_values_posted_back_by_a_browser_still_read_newest_first(
    lab: dict[str, Any], monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    from app.api import query as q_mod

    calls: list[str] = []
    real = q_mod.newest_first
    monkeypatch.setattr(
        q_mod, "newest_first", lambda *a, **k: (calls.append(a[1]), real(*a, **k))[1]
    )
    a, h = lab["admin"], lab["h"]
    c = a.post("/api/search/compile", json={"text": text}, headers=h).json()
    params = {k: _as_browser(v) for k, v in c["params"].items()}
    body = {"sql": c["sql"], "params": params, "start": "2020-01-01T00:00:00Z"}
    plain = a.post("/api/query", json=body, headers=h).json()
    stepped = a.post("/api/query", json={**body, "text": text}, headers=h).json()
    assert calls == [text]
    assert stepped["row_count"] == plain["row_count"]
    assert sorted(map(str, stepped["rows"])) == sorted(map(str, plain["rows"]))


def test_a_posted_value_must_be_the_same_value() -> None:
    from app.api.query import _same_value

    assert _same_value(100.0, 100) and _same_value(-2.5, -2.5) and _same_value("100", "100")
    assert not _same_value(100.0, "100") and not _same_value("100", 100)
    assert not _same_value(1, True) and not _same_value(True, 1) and _same_value(True, True)
    assert not _same_value(float("nan"), float("nan"))
    assert not _same_value(float("inf"), float("inf")) and not _same_value(100.0, 100.5)
