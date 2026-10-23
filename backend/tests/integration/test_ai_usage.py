"""AI usage page and AI watch end to end (ADR-0015 rows 1, 2, 6 to 9, 13)."""

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_schedules import NOW, make_lab

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "fixtures"))
from ai_telemetry import logs_payload, metrics_payload

DNS = [
    ("10.20.1.5", "chatgpt.com"),
    ("10.20.1.5", "chatgpt.com"),
    ("10.20.1.6", "api.openai.com"),
    ("10.20.1.6", "claude.ai"),
    ("10.20.1.7", "chat.deepseek.com."),
    ("10.20.1.7", "www.example.com"),
    ("10.20.1.8", "notchatgpt.com"),
    # An OpenAI ad tag loaded by some other website: not ChatGPT use (trial finding).
    ("10.20.1.9", "bzr.openai.com"),
    ("10.20.1.9", "bzrcdn.openai.com"),
]


def dns_line(i: int, client: str, name: str) -> str:
    return (
        f"<30>Oct 10 11:{i:02d}:00 ns1 named[800]: client 10.0.0.1#53 ({name}): "
        f"query: {name} IN A +E(0)K (10.20.0.53)"
    ).replace("client 10.0.0.1", f"client {client}")


@pytest.fixture
def lab(tmp_path: Path) -> Any:
    out = make_lab(tmp_path)
    a, h = out["admin"], out["h"]
    dns = tmp_path / "logs" / "dns"
    dns.mkdir()
    (dns / "q.log").write_text("\n".join(dns_line(i, c, n) for i, (c, n) in enumerate(DNS)) + "\n")
    body = {"source_id": "dns", "format": "syslog", "path": str(dns), "template_id": "dns_bind"}
    assert a.post("/api/sources", json=body, headers=h).status_code == 201
    res = a.post(
        "/api/sources",
        json={"source_id": "claude", "kind": "otlp", "format": "json", "template_id": "auto"},
        headers=h,
    )
    token = res.json()["otlp_token"]
    base = {"user.email": "alice@example.com", "session.id": "s-1"}
    params = json.dumps({"mcp_server_name": "paste-share", "mcp_tool_name": "upload"})
    t0 = NOW - timedelta(minutes=30)
    logs = logs_payload(
        [
            (
                t0,
                {
                    **base,
                    "event.name": "tool_result",
                    "tool_name": "mcp_tool",
                    "success": "true",
                    "tool_parameters": params,
                },
            ),
            (
                t0,
                {**base, "event.name": "user_prompt", "prompt": "deploy with AKIAABCDEFGHIJKLMNOP"},
            ),
        ],
        "ws-0042",
    )
    metrics = metrics_payload([(t0, "claude_code.cost.usage", "USD", 1.25, {**base, "model": "m"})])
    inventory = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "remnant-mcp-inventory"}}
                    ]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": str(int(t0.timestamp() * 1e9)),
                                "attributes": [
                                    {"key": k, "value": {"stringValue": v}}
                                    for k, v in {
                                        "event.name": "mcp_inventory",
                                        "host": "ws-0042",
                                        "os_user": "alice",
                                        "client": "cursor",
                                        "server": server,
                                        "transport": "stdio",
                                        "command": "npx",
                                    }.items()
                                ],
                            }
                            # paste-share is also used through telemetry by alice@example.com
                            for server in ("github", "paste-share", "My Notes Server")
                        ]
                    }
                ],
            }
        ]
    }
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for path, payload in (("logs", logs), ("metrics", metrics), ("logs", inventory)):
        r = a.post(f"/api/otlp/v1/{path}", content=json.dumps(payload).encode(), headers=hdr)
        assert r.status_code == 200, r.text
    out["app"].state.ingest.run_once()
    return out


def usage(client: Any) -> dict[str, Any]:
    res = client.get("/api/ai/usage")
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def test_services_from_dns_longest_domain_wins(lab: dict[str, Any]) -> None:
    got = {u["service"]["id"]: u for u in usage(lab["admin"])["services"]}
    assert set(got) == {
        "chatgpt",
        "openai_api",
        "claude",
        "deepseek",
    }  # not example.com or notchatgpt.com
    assert got["chatgpt"]["events"] == 2 and got["chatgpt"]["machines"] == 1
    assert got["openai_api"]["service"]["name"] == "OpenAI API"
    assert got["chatgpt"]["service"]["status"] == "unreviewed"


def test_vendor_tags_on_other_sites_are_shown_apart_not_counted(lab: dict[str, Any]) -> None:
    body = usage(lab["admin"])
    assert "openai_ad_tags" not in {u["service"]["id"] for u in body["services"]}
    (tags,) = body["non_usage"]
    assert tags["service"]["id"] == "openai_ad_tags" and tags["service"]["kind"] == "non_usage"
    assert tags["events"] == 2 and tags["machines"] == 1


def test_mcp_and_people(lab: dict[str, Any]) -> None:
    body = usage(lab["admin"])
    mcp = {m["name"]: m for m in body["mcp"]}
    assert mcp["paste-share"]["calls"] == 1
    assert mcp["paste-share"]["sources"] == ["inventory", "telemetry"]
    assert mcp["github"]["installs"] == 1 and mcp["github"]["clients"] == ["cursor"]
    (alice,) = body["people"]
    assert alice["person"] == "alice@example.com"
    assert alice["cost_usd"] == 1.25 and alice["sensitive"] == 1 and alice["tool_calls"] == 1


def test_review_is_admin_only_audited_and_applied(lab: dict[str, Any]) -> None:
    a, h = lab["admin"], lab["h"]
    assert (
        lab["ana"].put("/api/ai/services/chatgpt/status", json={"status": "approved"}).status_code
        == 403
    )
    res = a.put("/api/ai/services/chatgpt/status", json={"status": "not_approved"}, headers=h)
    assert res.status_code == 200 and res.json()["status"] == "not_approved"
    rules = a.put(
        "/api/ai/mcp-rules", json={"pattern": "git*", "status": "approved"}, headers=h
    ).json()
    assert rules[0]["pattern"] == "git*"
    body = usage(a)
    assert {u["service"]["id"]: u["service"]["status"] for u in body["services"]}[
        "chatgpt"
    ] == "not_approved"
    assert {m["name"]: m["status"] for m in body["mcp"]} == {
        "github": "approved",
        "paste-share": "unreviewed",
        "My Notes Server": "unreviewed",
    }
    added = a.post(
        "/api/ai/services",
        json={
            "id": "internal_llm",
            "name": "Internal LLM",
            "kind": "chat",
            "domains": ["example.com"],
        },
        headers=h,
    )
    assert added.status_code == 201 and added.json()["custom"] is True
    assert "internal_llm" in {u["service"]["id"] for u in usage(a)["services"]}
    bad = a.post(
        "/api/ai/services",
        json={"id": "x1", "name": "X", "kind": "chat", "domains": ["a' OR 1=1 --"]},
        headers=h,
    )
    assert bad.status_code == 422
    with lab["app"].state.meta.connect() as con:
        actions = [
            r[0]
            for r in con.execute(
                "SELECT action FROM audit_log WHERE action LIKE 'ai.%' ORDER BY audit_id"
            )
        ]
    assert (
        actions.count("ai.service_change") == 2
        and "ai.mcp_change" in actions
        and "ai.view" in actions
    )


def test_scope_follows_source_groups(lab: dict[str, Any]) -> None:
    body = usage(lab["ana"])  # ana reads only the Linux group
    assert body["services"] == [] and body["mcp"] == [] and body["people"] == []


def test_watch_alerts_once_per_first_sighting_and_on_sensitive_data(lab: dict[str, Any]) -> None:
    app, a, h = lab["app"], lab["admin"], lab["h"]
    app.state.ai_watch._clock = lambda: NOW - timedelta(days=1)  # cursor before the data
    res = a.put("/api/ai/watch", json={"enabled": True, "include_unreviewed": True}, headers=h)
    assert res.status_code == 200 and res.json()["enabled"] is True
    assert app.state.ai_watch.tick() == 2  # new AI use, and sensitive data
    assert app.state.ai_watch.tick() == 0  # nothing new
    with app.state.meta.connect() as con:
        rows = {
            r[0]: json.loads(r[1])
            for r in con.execute(
                "SELECT action, detail FROM audit_log WHERE action IN ('ai.sighting', 'ai.sensitive')"
            )
        }
    items = " ".join(rows["ai.sighting"]["items"])
    assert "ChatGPT by 10.20.1.5" in items and "MCP paste-share by alice@example.com" in items
    assert "10.20.1.9" not in items  # the ad tag host is not a sighting
    assert rows["ai.sensitive"]["items"] == ["alice@example.com: aws_access_key x1"]
    assert "AKIA" not in json.dumps(rows)
    assert lab["ana"].get("/api/ai/watch").status_code == 403


def test_new_and_no_longer_seen_compare_with_the_period_before(lab: dict[str, Any]) -> None:
    # DNS lookups are at 11:00 to 11:06, telemetry at 11:30. From 11:30 on, the services
    # were seen only in the half hour before: listed as no longer seen, with their status.
    start, end = (NOW - timedelta(minutes=30)).isoformat(), NOW.isoformat()
    res = lab["admin"].get("/api/ai/usage", params={"start": start, "end": end})
    body = res.json()
    assert body["compared_from"] == (NOW - timedelta(hours=1)).isoformat()
    gone = {(g["kind"], g["id"]): g for g in body["gone"]}
    assert ("service", "chatgpt") in gone and gone[("service", "chatgpt")]["status"] == "unreviewed"
    assert gone[("service", "chatgpt")]["last_seen"].startswith("2026-10-10T11:")
    assert "paste-share" in body["new_mcp"] and body["new_services"] == []
    # Over two hours nothing came before at all: no comparison, rather than all New (QA F10).
    start = (NOW - timedelta(hours=2)).isoformat()
    body = lab["admin"].get("/api/ai/usage", params={"start": start, "end": end}).json()
    assert body["compared_from"] is None and body["new_services"] == [] and body["gone"] == []
    # Without a start there is nothing to compare with.
    body = usage(lab["admin"])
    assert body["compared_from"] is None and body["new_services"] == [] and body["gone"] == []


def test_mcp_people_count_one_person_once(lab: dict[str, Any]) -> None:
    # QA F4: alice (inventory) and alice@example.com (telemetry) were counted as two.
    before = {m["name"]: m for m in usage(lab["admin"])["mcp"]}
    assert before["paste-share"]["people"] == 2  # no organization domain set yet
    res = lab["admin"].put(
        "/api/identities/domains", json={"domains": ["example.com"]}, headers=lab["h"]
    )
    assert res.status_code == 200, res.text
    after = {m["name"]: m for m in usage(lab["admin"])["mcp"]}
    assert after["paste-share"]["people"] == 1


def test_any_mcp_server_name_can_be_reviewed(lab: dict[str, Any]) -> None:
    # QA F3: a name with spaces could not be marked, so it stayed Unreviewed forever.
    for pattern, ok in (("My Notes Server", True), ("My *", True), ("a*b", False), ("*", False)):
        res = lab["admin"].put(
            "/api/ai/mcp-rules",
            json={"pattern": pattern, "status": "not_approved"},
            headers=lab["h"],
        )
        assert (res.status_code == 200) is ok, (pattern, res.status_code, res.text)
    mcp = {m["name"]: m for m in usage(lab["admin"])["mcp"]}
    assert mcp["My Notes Server"]["status"] == "not_approved"


def test_listed_domains_match_dns_query_names(lab: dict[str, Any]) -> None:
    # QA F6: DNS templates keep the name in unmapped, so intel:listed never matched.
    a, h = lab["admin"], lab["h"]
    up = a.post(
        "/api/enrichment/feeds/intel_custom/upload",
        content="chat.deepseek.com,Lab listing\n",
        headers=h,
    )
    assert up.status_code == 200, up.text
    compiled = a.post("/api/search/compile", json={"text": "intel:listed"}, headers=h).json()
    res = a.post(
        "/api/query", json={"sql": compiled["sql"], "params": compiled.get("params", {})}, headers=h
    ).json()
    assert len(res["rows"]) == 1, res


def _ai_items(client: Any, state: str = "open") -> dict[str, dict[str, Any]]:
    res = client.get(f"/api/alerts?state={state}")
    assert res.status_code == 200, res.text
    return {i["ref_id"]: i for i in res.json()["items"] if i["kind"] == "ai_watch"}


def test_review_items_on_alerts_without_alert_messages(lab: dict[str, Any]) -> None:
    """ADR-0035 row 11, ADR-0037 row 13: every check raises review items, whether or not
    the watch's messages are on; Approve and Not approved answer them, audited."""
    app, a, h = lab["app"], lab["admin"], lab["h"]
    app.state.ai_watch._clock = lambda: NOW - timedelta(days=1)  # cursor before the data
    assert app.state.ai_watch.tick() == 0  # messages are off by default
    items = _ai_items(a)
    chatgpt = items["service:chatgpt"]
    assert chatgpt["title"] == "New AI service: ChatGPT" and chatgpt["why"] == "Not reviewed yet"
    assert chatgpt["sources"] == ["dns"] and chatgpt["severity"] == "medium"
    # DNS names no person: the addresses are devices, apart, never counted as people.
    assert chatgpt["count"] == 0
    assert chatgpt["detail"] == "1 device not matched to a person: 10.20.1.5"
    assert "service:bzr" not in " ".join(items)  # an ad tag is not AI use
    sens = next(i for r, i in items.items() if r.startswith("sensitive:alice@example.com:"))
    assert sens["severity"] == "high" and sens["why"] == "aws_access_key x1"
    assert "AKIA" not in json.dumps(sens)
    assert "mcp:paste-share" in items
    # Ana reads Linux only: the AI items are restricted for her, counted, not described.
    ana = lab["ana"].get("/api/alerts").json()
    assert not [i for i in ana["items"] if i["kind"] == "ai_watch"] and ana["restricted"] >= 3
    # A second check adds nothing.
    before = len(items)
    app.state.ai_watch.tick()
    assert len(_ai_items(a)) == before
    # Marking ChatGPT not approved answers its item; an MCP rule answers the MCP item.
    put = a.put("/api/ai/services/chatgpt/status", json={"status": "not_approved"}, headers=h)
    assert put.status_code == 200, put.text
    rule = a.put(
        "/api/ai/mcp-rules", json={"pattern": "paste-share", "status": "approved"}, headers=h
    )
    assert rule.status_code == 200, rule.text
    closed = _ai_items(a, "closed")
    assert closed["service:chatgpt"]["close_reason"] == "true_positive"
    assert closed["service:chatgpt"]["note"] == "Marked not approved"
    assert closed["mcp:paste-share"]["note"] == "Approved"
    assert "service:chatgpt" not in _ai_items(a)
    # The hourly agent check raises one item per new agent, scoped to telemetry sources.
    app.state.ai_watch._clock = lambda: NOW
    app.state.ai_watch.tick()
    agent = next(i for r, i in _ai_items(a).items() if r.startswith("agent:"))
    assert agent["title"].startswith("New AI agent: ") and agent["sources"] == ["claude"]


def test_ai_watch_summary_cards_chart_and_top(lab: dict[str, Any]) -> None:
    """ADR-0035 rows 10, 12, 13, 15: counted on the caller's view, with what is missing named."""
    app, a = lab["app"], lab["admin"]
    app.state.ai_watch._clock = lambda: NOW + timedelta(hours=1)
    res = a.get("/api/ai/watch/summary?days=7")
    assert res.status_code == 200, res.text
    s = res.json()
    cards = {c["key"]: c for c in s["cards"]}
    assert list(cards) == ["services", "people", "agents", "consent", "sensitive"]
    assert cards["services"]["value"] >= 3 and cards["services"]["previous"] == 0
    assert "not reviewed yet" in cards["services"]["context"]
    # DNS names no person: 0 people, and 10.20.1.5, .6, .7 as devices apart (never added in);
    # the ad tag host is not use.
    assert cards["people"]["value"] == 0 and cards["people"]["devices"] == 3
    assert cards["consent"]["value"] is None
    assert cards["consent"]["needs"] == "a Microsoft 365 source"
    assert cards["sensitive"]["value"] == 1 and "alice@example.com" in cards["sensitive"]["context"]
    assert len(s["chart"]) == 30 and s["chart"][-1]["day"] == NOW.date().isoformat()
    assert s["chart"][-1]["unreviewed"] > 0 and s["chart"][-1]["approved"] == 0
    assert {t["service_id"] for t in s["top"]} >= {"chatgpt", "deepseek"}
    assert "bzr" not in json.dumps(s["top"])
    # Ana reads Linux only: no AI use, and the telemetry cards are restricted for her.
    ana = {c["key"]: c for c in lab["ana"].get("/api/ai/watch/summary").json()["cards"]}
    assert ana["services"]["value"] == 0 and ana["sensitive"]["restricted"] is True
    assert ana["agents"]["restricted"] is True


def test_cards_know_telemetry_and_m365_read_from_files() -> None:
    """A file read with the Claude Code or an M365 template counts as that source, so the
    cards do not say a source is missing when it is only collected another way."""
    from app.ai.watch_summary import source_classes

    got = source_classes(
        [
            ("cc", "file", "claude_code_otel"),
            ("inv", "file", "mcp_inventory"),
            ("otel", "otlp", "auto"),
            ("aud", "file", "m365_directory_audit"),
            ("m365", "m365", None),
            ("dns", "file", "dns_bind"),
        ]
    )
    assert got == {"telemetry": ["cc", "inv", "otel"], "m365": ["aud", "m365"]}


def test_ai_flow_shows_devices_apart_from_people(lab: dict[str, Any]) -> None:
    """Owner, 2026-10-22: a device or address with no person named is never a person."""
    rng = {
        "start": (NOW - timedelta(days=1)).isoformat(),
        "end": (NOW + timedelta(hours=1)).isoformat(),
    }
    g = lab["admin"].get("/api/entities/graph", params={"mode": "ai", **rng}).json()
    lane0 = {c["label"]: c["group"] for c in g["cards"] if c["lane"] == 0}
    assert lane0["alice@example.com"] == "People"
    assert lane0["10.20.1.5"] == "Addresses"  # an address with no person stays apart
    assert lane0.get("ws-0042") in (None, "Devices not matched to a person")
