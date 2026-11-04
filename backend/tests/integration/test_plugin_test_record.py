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
    # A test record is not use (owner, 2026-11-04): no session, no agent, no device.
    assert admin.get("/api/ai/sessions?days=1").json() == []
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


def _doctor(now_s: int) -> dict[str, Any]:
    """The installer's --doctor record, as install-local.sh sends it."""
    attrs = {
        "event_name": "claude_hooks.session_start", "role": "session",
        "session_id": f"doctor-{now_s}", "plugin_variant": "doctor", "test_record": "true",
    }  # fmt: skip
    rec = {
        "timeUnixNano": f"{now_s}000000000",
        "body": {"stringValue": "claude_hooks.session_start"},
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
    }
    res = {"attributes": [{"key": "service.name", "value": {"stringValue": "claude-hooks"}}]}
    scope = {"scope": {"name": "claude-hooks"}, "logRecords": [rec]}
    return {"resourceLogs": [{"resource": res, "scopeLogs": [scope]}]}


def test_test_records_add_nothing_to_any_count(lab: dict[str, Any]) -> None:  # noqa: F811
    """Owner, 2026-11-04: a doctor run and Send a test record were counted as a person with
    a blank name. Neither adds to Sessions, Agents, accounts, the Agents overview, AI usage,
    or AI watch."""
    import time

    admin, h = lab["admin"], lab["h"]
    tid = _token(lab, "laptops")
    plain = lab["app"].state.otlp_tokens.plain(tid)[1]
    assert admin.post(f"/api/sources/claude/otlp-tokens/{tid}/test", headers=h).json()["ok"]
    sent = admin.post(
        "/api/otlp/v1/logs", json=_doctor(int(time.time())),
        headers={"Authorization": f"Bearer {plain}"},
    )  # fmt: skip
    assert sent.status_code == 200, sent.text
    lab["app"].state.ingest.run_once()
    assert admin.get("/api/ai/sessions?days=1").json() == []
    assert admin.get("/api/ai/agents").json() == []
    accounts = admin.get("/api/agents/accounts").json()
    assert accounts["rows"] == [] and not any(accounts["counts"].values()), accounts
    o = admin.get("/api/agents/overview").json()
    for k in ("sessions", "people", "calls", "failed"):
        assert o[k] is None or o[k]["value"] == 0, (k, o[k])
    usage = admin.get("/api/ai/usage").json()
    assert usage["people"] == [], usage["people"]
