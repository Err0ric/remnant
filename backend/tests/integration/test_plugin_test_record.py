"""Owner 2026-11-02 (A7): Settings > Claude plugins can send one synthetic SessionStart per
deployment through the real receiver with that deployment's token, and shows the HTTP
result, so the server side is checked without a client."""

from typing import Any

from tests.integration.test_claude_hooks import lab  # noqa: F401  # the fixture


def _token(lab: dict[str, Any], name: str) -> str:  # noqa: F811
    made = lab["admin"].post(
        "/api/sources/claude/otlp-tokens", json={"name": name}, headers=lab["h"]
    )
    assert made.status_code == 200, made.text
    return str(made.json()["token_id"])


def test_a_live_token_is_accepted_and_the_record_lands(lab: dict[str, Any]) -> None:  # noqa: F811
    admin, h = lab["admin"], lab["h"]
    tid = _token(lab, "laptops")
    res = admin.post(f"/api/sources/claude/otlp-tokens/{tid}/test", headers=h)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["ok"] and out["status"] == 200 and out["session_id"].startswith("server-test-")
    lab["app"].state.ingest.run_once()
    got = {s["session_id"]: s for s in admin.get("/api/ai/sessions?days=1").json()}
    assert out["session_id"] in got and got[out["session_id"]]["tool_calls"] == 0
    # It names no one and no machine, so it is no agent and no device.
    assert admin.get("/api/ai/agents").json() == []  # the lab has no other Claude use
    laptops = next(t for t in admin.get("/api/plugins").json()["tokens"] if t["name"] == "laptops")
    assert laptops["devices"] == 0 and laptops["last_used_at"]
    log = admin.get("/api/audit/events", params={"action": "source.otlp_token"}).json()
    test = [e for e in log if e["detail"].get("change") == "test"]
    assert test and test[0]["detail"]["status"] == 200


def test_a_revoked_token_cannot_be_tested(lab: dict[str, Any]) -> None:  # noqa: F811
    admin, h = lab["admin"], lab["h"]
    tid = _token(lab, "old")
    assert admin.delete(f"/api/sources/claude/otlp-tokens/{tid}", headers=h).status_code == 200
    res = admin.post(f"/api/sources/claude/otlp-tokens/{tid}/test", headers=h)
    assert res.status_code == 404


def test_only_admins_send_test_records(lab: dict[str, Any]) -> None:  # noqa: F811
    tid = _token(lab, "laptops")
    res = lab["ana"].post(f"/api/sources/claude/otlp-tokens/{tid}/test", headers=lab["h"])
    assert res.status_code in (401, 403)
