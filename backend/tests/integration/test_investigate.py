"""Entity risk and the investigator graph (ADR-0016 rows 4, 5, 7): scores from rule matches,
scope per caller, lanes, AI flow, and attacker-controlled values kept as data."""

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.main import create_app

FIX = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
ADMIN_PW = "correct horse battery"
USER_PW = "another long passphrase"
BASE = "https://siem.example.internal"
RANGE = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-31T00:00:00Z"}

LINUX_ID = "11111111-1111-4111-8111-111111111111"
WIN_ID = "22222222-2222-4222-8222-222222222222"
LINUX = f"""title: SSH failed password
id: {LINUX_ID}
level: high
logsource: {{product: linux}}
detection:
  k: ['Failed password']
  condition: k
"""
WIN = f"""title: Failed logon
id: {WIN_ID}
level: medium
logsource: {{product: windows, service: security}}
detection:
  s: {{EventID: 4625}}
  condition: s
"""


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    logs = tmp_path / "logs"
    for sub, tid in (
        ("win", "windows_nxlog_json"),
        ("lin", "linux_sshd"),
        ("cc", "claude_code_otel"),
        ("inv", "mcp_inventory"),
    ):
        (logs / sub).mkdir(parents=True)
        shutil.copy(FIX / tid / "sample.log", logs / sub / "a.log")
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "lin.yml").write_text(LINUX)
    (rules / "win.yml").write_text(WIN)
    config = load_config(
        Path("missing.yaml"),
        {
            "APP__PATHS__DATA_DIR": str(tmp_path / "data"),
            "APP__PATHS__ALLOWED_ROOTS": str(logs),
            "APP__PATHS__RULE_ROOTS": str(rules),
            "APP__SERVER__HOST": "0.0.0.0",
        },
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    admin = TestClient(app, base_url=BASE)
    token = app.state.auth.setup_url("siem.example.internal", 8080).split("#", 1)[1]
    csrf = admin.post(
        "/api/setup", json={"token": token, "username": "admin", "password": ADMIN_PW}
    ).json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    for sid, tid, sub, fmt in (
        ("win_dc", "windows_nxlog_json", "win", "syslog"),
        ("lin_auth", "linux_sshd", "lin", "syslog"),
        ("claude", "claude_code_otel", "cc", "json"),
        ("mcp", "mcp_inventory", "inv", "json"),
    ):
        res = admin.post(
            "/api/sources",
            json={"source_id": sid, "format": fmt, "path": str(logs / sub), "template_id": tid},
            headers=h,
        )
        assert res.status_code == 201, res.text
    app.state.ingest.run_once()
    admin.post("/api/rules/import", json={"path": str(rules)}, headers=h)
    admin.post(
        "/api/rules/enabled", json={"rule_ids": [LINUX_ID, WIN_ID], "enabled": True}, headers=h
    )
    for rid in (LINUX_ID, WIN_ID):
        res = admin.post(f"/api/rules/{rid}/run", json=RANGE, headers=h)
        assert res.status_code == 200 and res.json()["match_count"] > 0, res.text
    res = admin.post("/api/users", json={"username": "ana", "role": "analyst"}, headers=h)
    ana_id = res.json()["user"]["user_id"]
    admin.post(
        "/api/account/password", json={"token": res.json()["invite_token"], "password": USER_PW}
    )
    login = TestClient(app, base_url=BASE).post(
        "/api/auth/login", json={"username": "ana", "password": USER_PW, "client": "cli"}
    )
    ana = TestClient(
        app, base_url=BASE, headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    gid = admin.post("/api/groups", json={"name": "Linux"}, headers=h).json()["group_id"]
    admin.put(f"/api/groups/{gid}/sources", json={"source_ids": ["lin_auth"]}, headers=h)
    admin.put(f"/api/groups/{gid}/members", json={"user_ids": [ana_id]}, headers=h)
    return {"app": app, "admin": admin, "h": h, "ana": ana}


def test_risk_ranks_entities_by_weighted_rule_matches(lab: dict[str, Any]) -> None:
    res = lab["admin"].get("/api/entities/risk", params=RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["matches_considered"] > 0
    top_ip = body["ips"][0]
    # High-level matches weigh 5 each; the parts are shown with the score.
    assert top_ip["score"] == 5 * top_ip["high"] + 2 * top_ip["medium"] + top_ip["low"]
    assert top_ip["high"] > 0 and "SSH failed password" in top_ip["rules"]
    assert [r["score"] for r in body["ips"]] == sorted(
        (r["score"] for r in body["ips"]), reverse=True
    )
    hosts = {r["value"] for r in body["hosts"]}
    assert hosts & {"bastion", "web-01", "db-01"}
    assert top_ip["search_sql"].startswith("SELECT") and top_ip["value"] in top_ip["search_sql"]


def test_risk_and_graph_only_count_the_callers_sources(lab: dict[str, Any]) -> None:
    admin = lab["admin"].get("/api/entities/risk", params=RANGE).json()
    ana = lab["ana"].get("/api/entities/risk", params=RANGE).json()
    assert ana["sources"] == ["lin_auth"]
    assert all("Failed logon" not in r["rules"] for r in ana["users"] + ana["ips"] + ana["hosts"])
    assert any("Failed logon" in r["rules"] for r in admin["users"] + admin["ips"] + admin["hosts"])
    win_host = next(r["value"] for r in admin["hosts"] if r["rules"] == ["Failed logon"])
    seen = (
        lab["admin"]
        .get(
            "/api/entities/graph",
            params={"mode": "entity", "kind": "host", "value": win_host, **RANGE},
        )
        .json()
    )
    assert any(c["label"] == "win_dc" for c in seen["cards"])
    g = (
        lab["ana"]
        .get(
            "/api/entities/graph",
            params={"mode": "entity", "kind": "host", "value": win_host, **RANGE},
        )
        .json()
    )
    assert [c for c in g["cards"] if c["lane"] > 0] == []
    assert all(c["events"] == 0 for c in g["cards"])


def test_entity_graph_has_lanes_cards_and_edges(lab: dict[str, Any]) -> None:
    top = lab["admin"].get("/api/entities/risk", params=RANGE).json()["ips"][0]["value"]
    res = lab["admin"].get(
        "/api/entities/graph", params={"mode": "entity", "kind": "ip", "value": top, **RANGE}
    )
    assert res.status_code == 200, res.text
    g = res.json()
    assert g["lanes"] == ["Entity", "Sources", "Activities", "Targets"]
    root = next(c for c in g["cards"] if c["lane"] == 0)
    assert root["label"] == top and root["sublabel"] == "IP address" and root["matches"] > 0
    assert any(c["lane"] == 1 and c["label"] == "lin_auth" for c in g["cards"])
    acts = [c for c in g["cards"] if c["lane"] == 2]
    assert acts and all(c["search_sql"] for c in acts)
    assert all(c["group"] == c["sublabel"] for c in acts)  # grouped by event class
    assert any("rule match" in b for c in acts for b in c["badges"])
    ids = {c["id"] for c in g["cards"]}
    assert g["edges"] and all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert sum(e["events"] for e in g["edges"] if e["source"] == root["id"]) == root["events"]


def test_attacker_controlled_values_stay_data(lab: dict[str, Any]) -> None:
    value = "x' OR 1=1 --<script>"
    res = lab["admin"].get(
        "/api/entities/graph", params={"mode": "entity", "kind": "user", "value": value, **RANGE}
    )
    assert res.status_code == 200, res.text
    root = res.json()["cards"][0]
    assert root["label"] == value and root["events"] == 0
    # Users are matched by their normalized name; the quote is doubled inside the literal.
    assert "'x'' or 1=1 --<script>'" in root["search_sql"]
    ran = lab["admin"].post("/api/query", json={"sql": root["search_sql"]}, headers=lab["h"])
    assert ran.status_code == 200 and ran.json()["row_count"] == 0


def test_ai_flow_links_people_clients_tools_and_destinations(lab: dict[str, Any]) -> None:
    lab["admin"].put(
        "/api/ai/mcp-rules",
        json={"pattern": "paste-share", "status": "not_approved"},
        headers=lab["h"],
    )
    res = lab["admin"].get("/api/entities/graph", params={"mode": "ai", **RANGE})
    assert res.status_code == 200, res.text
    g = res.json()
    assert g["lanes"] == ["People", "AI clients", "Tools and MCP servers", "Destinations"]
    labels = {(c["lane"], c["label"]) for c in g["cards"]}
    assert (0, "alice@example.com") in labels and (1, "Claude Code") in labels
    # Claude Code's API calls land on the catalog's Anthropic API card, not a raw host.
    assert (3, "api.anthropic.com") not in labels
    assert any(c["lane"] == 3 and c["id"] == "3:svc:anthropic_api" for c in g["cards"])
    clients = {c["label"] for c in g["cards"] if c["lane"] == 1}
    assert "Claude Desktop" in clients and "claude_code" not in clients
    paste = next(c for c in g["cards"] if c["lane"] == 2 and c["label"] == "paste-share")
    assert "Not approved" in paste["badges"]
    # Lanes are split into groups, as in the lane layout of ADR-0016.
    assert paste["group"] == "MCP servers"
    assert next(c for c in g["cards"] if c["id"] == "3:svc:anthropic_api")["group"] == "AI services"
    assert next(c for c in g["cards"] if c["label"] == "alice@example.com")["group"] == "People"
    assert {c["group"] for c in g["cards"] if c["lane"] == 1} == {""}
    one = (
        lab["admin"]
        .get(
            "/api/entities/graph",
            params={"mode": "ai", "kind": "user", "value": "alice@example.com", **RANGE},
        )
        .json()
    )
    assert {c["label"] for c in one["cards"] if c["lane"] == 0} == {"alice@example.com"}
    # Analysts without the AI sources see an empty flow, not other people's AI use.
    empty = lab["ana"].get("/api/entities/graph", params={"mode": "ai", **RANGE}).json()
    assert empty["cards"] == []


def test_bad_requests_are_refused_and_reads_are_audited(lab: dict[str, Any]) -> None:
    bad = lab["admin"].get("/api/entities/graph", params={"mode": "entity", "kind": "mcp"})
    assert bad.status_code == 400
    assert (
        lab["admin"]
        .get("/api/entities/graph", params={"mode": "ai", "kind": "ip", "value": "x"})
        .status_code
        == 400
    )
    lab["admin"].get("/api/entities/risk", params=RANGE)
    log = lab["admin"].get("/api/audit/events", params={"action": "investigate.risk"}).json()
    assert any(r["action"] == "investigate.risk" for r in log)


def test_identities_merge_names_by_domain_and_alias(lab: dict[str, Any]) -> None:
    admin, h = lab["admin"], lab["h"]
    before = admin.get("/api/entities/graph", params={"mode": "ai", **RANGE}).json()
    people = {c["label"] for c in before["cards"] if c["lane"] == 0}
    assert {"alice", "alice@example.com"} <= people
    # Suggestions: example.com is shared by bare names, and alice shares a machine.
    sug = admin.get("/api/identities").json()
    dom = next(d for d in sug["domain_suggestions"] if d["domain"] == "example.com")
    assert dom["shared"] >= 1 and "alice" in dom["examples"]
    assert any(
        a["alias"] == "alice" and a["person"] == "alice@example.com"
        for a in sug["alias_suggestions"]
    )
    # Accepting the domain merges them; the email form is shown.
    res = admin.put("/api/identities/domains", json={"domains": ["Example.com"]}, headers=h)
    assert res.json() == ["example.com"]
    after = admin.get("/api/entities/graph", params={"mode": "ai", **RANGE}).json()
    alice = [c for c in after["cards"] if c["lane"] == 0 and c["label"].startswith("alice")]
    assert [c["label"] for c in alice] == ["alice@example.com"]
    assert alice[0]["sublabel"] == "2 names"
    merged = next(c for c in before["cards"] if c["label"] == "alice@example.com")
    bare = next(c for c in before["cards"] if c["label"] == "alice")
    assert alice[0]["events"] == merged["events"] + bare["events"]
    one = admin.get(
        "/api/entities/graph",
        params={"mode": "ai", "kind": "user", "value": "alice", **RANGE},
    ).json()
    assert {c["label"] for c in one["cards"] if c["lane"] == 0} == {"alice@example.com"}
    ran = admin.post("/api/query", json={"sql": alice[0]["search_sql"]}, headers=h)
    assert ran.status_code == 200 and ran.json()["row_count"] > 0
    # An alias adds another login to a person; risk rows are added up.
    risk = admin.get("/api/entities/risk", params=RANGE).json()["users"]
    by = {r["value"]: r for r in risk}
    assert "bob" in by and "carol" in by
    admin.put("/api/identities/aliases", json={"alias": "bob", "person": "carol"}, headers=h)
    merged_risk = {
        r["value"]: r for r in admin.get("/api/entities/risk", params=RANGE).json()["users"]
    }
    assert "bob" not in merged_risk
    assert merged_risk["carol"]["score"] == by["carol"]["score"] + by["bob"]["score"]
    assert merged_risk["carol"]["names"] == ["bob", "carol"]
    # Removing the alias undoes it; nothing stored changed.
    admin.put("/api/identities/aliases", json={"alias": "bob", "person": None}, headers=h)
    again = {r["value"] for r in admin.get("/api/entities/risk", params=RANGE).json()["users"]}
    assert "bob" in again
    raw = admin.post(
        "/api/query",
        json={"sql": "SELECT count(*) FROM events WHERE actor_user_name = 'alice@example.com'"},
        headers=h,
    ).json()
    assert raw["rows"][0][0] > 0


def test_identities_are_admin_only_and_audited(lab: dict[str, Any]) -> None:
    assert lab["ana"].get("/api/identities").status_code == 403
    assert (
        lab["ana"].put("/api/identities/domains", json={"domains": ["example.com"]}).status_code
        == 403
    )
    bad = lab["admin"].put(
        "/api/identities/domains", json={"domains": ["not a domain"]}, headers=lab["h"]
    )
    assert bad.status_code == 400
    same = lab["admin"].put(
        "/api/identities/aliases", json={"alias": "Alice", "person": "alice"}, headers=lab["h"]
    )
    assert same.status_code == 400
    lab["admin"].put("/api/identities/domains", json={"domains": ["example.com"]}, headers=lab["h"])
    log = lab["admin"].get("/api/audit/events", params={"action": "identity.change"}).json()
    assert log and log[0]["action"] == "identity.change"


def test_entity_summary_counts_outcomes_targets_and_keeps_real_lines(lab: dict[str, Any]) -> None:
    """Product pass step 2: the entity page leads with numbers and real lines."""
    top = lab["admin"].get("/api/entities/risk", params=RANGE).json()["ips"][0]["value"]
    res = lab["admin"].get("/api/entities/summary", params={"kind": "ip", "value": top, **RANGE})
    assert res.status_code == 200, res.text
    s = res.json()
    assert s["events"] > 0 and "lin_auth" in s["sources"]
    assert s["failed"] > 0 and s["sign_ins"] >= s["failed"] + s["succeeded"]
    assert s["first_seen"] and s["last_seen"] and s["first_seen"] <= s["last_seen"]
    failed = [a for a in s["activities"] if a["outcome"] == "failed"]
    assert failed and failed[0]["kind"] == "Authentication"
    # Real values, not the number-masked pattern (groups tied on count may come in any order).
    named = next(a for a in failed if top in a["example"])
    assert "#.#.#.#" not in named["example"]
    ran = lab["admin"].post("/api/query", json={"sql": failed[0]["search_sql"]}, headers=lab["h"])
    assert ran.status_code == 200 and ran.json()["row_count"] == failed[0]["events"]
    assert any(t["kind"] in ("host", "user") for t in s["targets"])
    assert all(t["value"] != top for t in s["targets"])


def test_entity_summary_is_read_as_the_caller_and_audited(lab: dict[str, Any]) -> None:
    admin = lab["admin"].get("/api/entities/risk", params=RANGE).json()
    win_host = next(r["value"] for r in admin["hosts"] if r["rules"] == ["Failed logon"])
    params = {"kind": "host", "value": win_host, **RANGE}
    assert lab["admin"].get("/api/entities/summary", params=params).json()["events"] > 0
    ana = lab["ana"].get("/api/entities/summary", params=params).json()
    assert ana["events"] == 0 and ana["activities"] == [] and ana["targets"] == []
    rows = lab["admin"].get("/api/audit/events", params={"action": "investigate.summary"}).json()
    assert len(rows) >= 2
    bad = lab["admin"].get("/api/entities/summary", params={"kind": "mcp", "value": "x"})
    assert bad.status_code == 422


def test_lookup_finds_entities_only_in_the_callers_sources(lab: dict[str, Any]) -> None:
    admin = lab["admin"].get("/api/entities/risk", params=RANGE).json()
    ip = admin["ips"][0]["value"]
    prefix = ip.rsplit(".", 1)[0]
    res = lab["admin"].get("/api/entities/lookup", params={"q": prefix, **RANGE})
    assert res.status_code == 200, res.text
    hits = res.json()["hits"]
    assert any(h["kind"] == "ip" and h["value"] == ip and h["events"] > 0 for h in hits)
    assert all(h["value"].startswith(prefix) for h in hits if h["kind"] == "ip")
    # A Windows-only host is offered to the admin and never to the Linux-only analyst.
    win_host = next(r["value"] for r in admin["hosts"] if r["rules"] == ["Failed logon"])
    seen = lab["admin"].get("/api/entities/lookup", params={"q": win_host, **RANGE}).json()
    assert any(h["kind"] == "host" and h["value"] == win_host for h in seen["hits"])
    hidden = lab["ana"].get("/api/entities/lookup", params={"q": win_host, **RANGE}).json()
    assert not any(h["value"] == win_host for h in hidden["hits"])
    # AI services come from the catalog by name; the typed text is data, not SQL.
    ai = lab["ana"].get("/api/entities/lookup", params={"q": "claude", **RANGE}).json()
    assert any(h["kind"] == "service" for h in ai["hits"])
    odd = lab["ana"].get("/api/entities/lookup", params={"q": "x' OR 1=1 --", **RANGE})
    assert odd.status_code == 200 and odd.json()["hits"] == []
    assert lab["ana"].get("/api/entities/lookup", params={"q": "a"}).status_code == 422
    log = lab["admin"].get("/api/audit/events", params={"action": "investigate.lookup"}).json()
    mine = [e for e in log if (e.get("detail") or {}).get("q") == win_host]
    assert {tuple(e["detail"]["sources_in_scope"]) for e in mine} >= {("lin_auth",)}


def test_dashboard_sections_follow_the_callers_sources_and_networks(
    lab: dict[str, Any],
) -> None:
    app, admin, ana, h = lab["app"], lab["admin"], lab["ana"], lab["h"]
    app.state.ai_watch._clock = lambda: NOW
    full = admin.get("/api/dashboard/sections", params={"window": "30d"})
    assert full.status_code == 200, full.text
    body = full.json()
    assert len(body["buckets"]) == 30 and body["approved_set"] is False
    assert body["identity"] is None  # no Microsoft 365 source here
    attacks = body["attacks"]
    assert attacks["failures"]["value"] > 0 and attacks["addresses"]["value"] > 0
    assert all(len(s["counts"]) == 30 for s in attacks["by_host"])
    assert attacks["vpn_outside"] is None  # no approved countries, no VPN source
    assert set(attacks["history"]) == {"compared", "since"} and "geoip_date" in body
    det = body["detections"]
    assert det["matches"]["value"] > 0 and det["rules_matched"]["extra"] == 2
    assert {s["label"] for s in det["by_rule"]} == {"SSH failed password", "Failed logon"}

    # Every number has a drill-through that runs in Search and counts the same rows
    # (ADR-0039).
    def fill(sql: str, start: str, end: str) -> str:
        return sql.replace("{from}", start).replace("{to}", end)

    def count(sql: str) -> int:
        res = admin.post(
            "/api/query",
            json={"sql": f"SELECT count(*) AS n FROM ({sql})", "range": "all"},
            headers=h,
        )
        assert res.status_code == 200, (sql, res.text)
        return int(res.json()["rows"][0][0])

    win = (body["start"], body["end"])
    prev = (body["before"], body["start"])
    assert count(fill(attacks["failures"]["drill"], *win)) == attacks["failures"]["value"]
    assert count(fill(attacks["failures"]["drill"], *prev)) == attacks["failures"]["before"]
    assert count(fill(attacks["addresses"]["drill"], *win)) == attacks["addresses"]["value"]
    assert count(fill(det["matches"]["drill"], *win)) >= det["matches"]["value"]
    drills = [
        k["drill"]
        for k in (*attacks.values(), *det.values())
        if isinstance(k, dict) and "value" in k
    ]
    drills += [r["drill"] for r in attacks["top_sources"] + attacks["by_host"] + det["by_rule"]]
    assert all(drills)
    for sql in drills:
        count(fill(sql, *win))
    # The Linux-only analyst never sees the Windows rule or its hosts.
    mine = ana.get("/api/dashboard/sections", params={"window": "30d"}).json()
    assert {s["label"] for s in mine["detections"]["by_rule"]} == {"SSH failed password"}
    assert mine["attacks"]["failures"]["value"] <= attacks["failures"]["value"]
    # Addresses listed as internal are not attacks.
    everything = {"approved_countries": [], "internal_networks": ["0.0.0.0/0", "::/0"]}
    assert admin.put("/api/enrichment/places", json=everything, headers=h).status_code == 200
    quiet = admin.get("/api/dashboard/sections", params={"window": "30d"}).json()
    assert quiet["attacks"] is None
    # The lookups behind drill-throughs run in Search (ADR-0039 row 4): with every address
    # listed as internal, no failure is external.
    sql = (
        "SELECT count(*) AS n FROM events WHERE class_uid = 3002 AND status_id = 2"
        " AND NOT is_internal(src_endpoint_ip) AND ip_country(src_endpoint_ip) IS NULL"
    )
    ran = admin.post("/api/query", json={"sql": sql, "range": "all"}, headers=h)
    assert ran.status_code == 200, ran.text
    assert ran.json()["rows"] == [[0]]
    hourly = admin.get("/api/dashboard/sections", params={"window": "24h"}).json()
    assert len(hourly["buckets"]) == 24
    assert admin.get("/api/dashboard/sections", params={"window": "1y"}).status_code == 422
    log = admin.get("/api/audit/events", params={"action": "dashboard.sections"}).json()
    assert any(e["detail"]["window"] == "30d" for e in log)
