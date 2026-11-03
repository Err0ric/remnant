"""Owner 2026-11-02 (D170): Settings > Claude plugins shows, per deployment token, each
machine with its last seen time and the last reason the receiver refused that token; and
refused tokens that match none of this server's, by their first 8 characters only."""

from typing import Any

from tests.integration.test_claude_hooks import lab  # noqa: F401  # the fixture

LOGS = "/api/otlp/v1/logs"


def _made(lab: dict[str, Any], name: str) -> tuple[str, str]:  # noqa: F811
    made = lab["admin"].post(
        "/api/sources/claude/otlp-tokens", json={"name": name}, headers=lab["h"]
    )
    assert made.status_code == 200, made.text
    return str(made.json()["token_id"]), str(made.json()["token"])


def _body(host: str) -> dict[str, Any]:
    attrs = [{"key": "host.name", "value": {"stringValue": host}}]
    record = {"timeUnixNano": "1", "body": {"stringValue": "claude_hooks.session_start"}}
    return {"resourceLogs": [{"resource": {"attributes": attrs}, "scopeLogs": [
        {"scope": {"name": "claude-hooks"}, "logRecords": [record]}
    ]}]}  # fmt: skip


def _token(lab: dict[str, Any], name: str) -> dict[str, Any]:  # noqa: F811
    toks = lab["admin"].get("/api/plugins").json()["tokens"]
    return next(t for t in toks if t["name"] == name)


def test_machines_are_listed_with_last_seen(lab: dict[str, Any]) -> None:  # noqa: F811
    _, plain = _made(lab, "laptops")
    auth = {"Authorization": f"Bearer {plain}"}
    for host in ("wks-01.corp.internal", "wks-02.corp.internal"):
        assert lab["admin"].post(LOGS, json=_body(host), headers=auth).status_code == 200
    got = _token(lab, "laptops")
    hosts = {m["host"] for m in got["machines"]}
    assert hosts == {"wks-01.corp.internal", "wks-02.corp.internal"}
    assert all(m["last_seen"] for m in got["machines"])
    assert got["last_error"] is None


def test_a_bad_payload_is_recorded_on_the_token(lab: dict[str, Any]) -> None:  # noqa: F811
    _, plain = _made(lab, "desktops")
    res = lab["admin"].post(
        LOGS,
        content=b"not json",
        headers={"Authorization": f"Bearer {plain}", "Content-Type": "application/json"},
    )
    assert res.status_code >= 400
    got = _token(lab, "desktops")
    assert got["last_error"] and got["last_error"].startswith("Refused") and got["last_error_at"]
    assert plain not in got["last_error"]


def test_a_revoked_token_records_why(lab: dict[str, Any]) -> None:  # noqa: F811
    tid, plain = _made(lab, "old")
    assert (
        lab["admin"].delete(f"/api/sources/claude/otlp-tokens/{tid}", headers=lab["h"]).status_code
        == 200
    )
    res = lab["admin"].post(
        LOGS, json=_body("wks-03.corp.internal"), headers={"Authorization": f"Bearer {plain}"}
    )
    assert res.status_code == 401
    assert _token(lab, "old")["last_error"] == "Refused: the token was revoked"


def test_an_unknown_token_is_listed_by_prefix_only(lab: dict[str, Any]) -> None:  # noqa: F811
    fake = "rmt_" + "x" * 40
    res = lab["admin"].post(
        LOGS, json=_body("wks-04.corp.internal"), headers={"Authorization": f"Bearer {fake}"}
    )
    assert res.status_code == 401
    unknown = lab["admin"].get("/api/plugins").json()["unknown_tokens"]
    assert [u["prefix"] for u in unknown] == [fake[:8]]
    assert unknown[0]["count"] == 1
    assert fake not in str(unknown)
