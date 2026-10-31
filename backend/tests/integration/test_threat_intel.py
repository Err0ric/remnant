"""Threat intel lists (ADR-0023 rows 1 and 7): parsing, storage, the threat_intel table,
Simple search, facets, result markers, and updates. Synthetic indicators only."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.errors import QueryRejectedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.enrich import intel
from app.enrich.feeds import FeedStore
from app.enrich.updater import FeedUpdater
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)

FEODO = b"""################################################################
# abuse.ch Feodo Tracker Botnet C2 IP Blocklist (CSV)          #
################################################################
#
# "first_seen_utc","dst_ip","dst_port","c2_status","last_online","malware"
"2026-10-01 10:00:00","203.0.113.66","443","online","2026-10-16","QakBot"
"2026-10-02 11:00:00","198.51.100.23","8080","offline","2026-10-10","Emotet"
# END 2 entries
"""

THREATFOX = {
    "query_status": "ok",
    "data": [
        {
            "ioc": "192.0.2.77:4444",
            "ioc_type": "ip:port",
            "threat_type": "botnet_cc",
            "malware_printable": "Cobalt Strike",
            "first_seen": "2026-10-16 08:00:00 UTC",
            "last_seen": None,
        },
        {
            "ioc": "bad-domain.example",
            "ioc_type": "domain",
            "threat_type": "payload_delivery",
            "malware_printable": "AsyncRAT",
            "first_seen": "2026-10-16 09:00:00 UTC",
            "last_seen": None,
        },
        {"ioc": "not valid", "ioc_type": "domain"},
    ],
}


def test_parsers_normalize_and_count_bad_lines() -> None:
    rows, bad = intel.parse_feodo(FEODO)
    assert bad == 0 and [(r.indicator, r.threat) for r in rows] == [
        ("203.0.113.66", "QakBot botnet C2"),
        ("198.51.100.23", "Emotet botnet C2"),
    ]
    rows, bad = intel.parse_threatfox(json.dumps(THREATFOX).encode())
    assert bad == 1
    assert [(r.indicator, r.type) for r in rows] == [
        ("192.0.2.77", "ip"),
        ("bad-domain.example", "domain"),
    ]
    assert rows[0].threat == "Cobalt Strike (botnet C2)"
    custom = b"# ours\n192.0.2.10,Old VPN exit\nEVIL.Example.\nhttps://bad.example/x\n" + (
        b"d41d8cd98f00b204e9800998ecf8427e\n10.0.0.0/8\n"
    )
    rows, bad = intel.parse_custom(custom)
    assert bad == 1  # CIDR ranges are not matched exactly
    assert [(r.indicator, r.type, r.threat) for r in rows] == [
        ("192.0.2.10", "ip", "Old VPN exit"),
        ("evil.example", "domain", "Your list"),
        ("https://bad.example/x", "url", "Your list"),
        ("d41d8cd98f00b204e9800998ecf8427e", "md5", "Your list"),
    ]
    with pytest.raises(ValueError, match="refused the Auth-Key"):
        intel.parse_threatfox(b'{"query_status": "unknown_auth_key"}')


def test_rolling_window_drops_old_listings() -> None:
    old = intel.Indicator("192.0.2.1", "ip", "threatfox", "x", "2026-06-01T00:00:00+00:00")
    kept = intel.Indicator("192.0.2.2", "ip", "threatfox", "x", "2026-10-01T00:00:00+00:00")
    new = intel.Indicator("192.0.2.2", "ip", "threatfox", "y", "2026-10-16T00:00:00+00:00")
    merged = intel.merge_recent([old, kept], [new], NOW)
    assert [(m.indicator, m.threat) for m in merged] == [("192.0.2.2", "y")]


@pytest.fixture
def store(tmp_path: Path) -> FeedStore:
    return FeedStore(MetaDB(tmp_path / "meta.sqlite"), tmp_path, clock=lambda: NOW)


def test_lists_combine_and_switch_off(store: FeedStore, tmp_path: Path) -> None:
    store.install("intel_feodo", FEODO, "upload")
    store.install("intel_custom", b"192.0.2.10,Old VPN exit\n", "upload")
    with pytest.raises(Exception, match="not an address"):
        store.install("intel_custom", b"192.0.2.11\nnope\nalso nope\n", "upload")
    assert store.state("intel_custom").entries == 1  # the bad upload changed nothing
    engine = QueryEngine(tmp_path / "lake", intel_file=store.intel_file)
    count = "SELECT count(*) FROM threat_intel"
    assert engine.run(count, QueryScope(None)).rows == [[3]]
    store.set_enabled("intel_feodo", False)
    assert engine.run(count, QueryScope(None)).rows == [[1]]
    matcher = intel.ThreatIntel(store.intel_file)
    found = matcher.match(["192.0.2.10", "203.0.113.66", "x"])
    assert list(found) == ["192.0.2.10"] and found["192.0.2.10"][0].feed == "Your list"


def test_models_never_read_the_lists(store: FeedStore, tmp_path: Path) -> None:
    engine = QueryEngine(tmp_path / "lake", intel_file=store.intel_file)
    assert engine.run("SELECT count(*) FROM threat_intel", QueryScope(None)).rows == [[0]]
    with pytest.raises(QueryRejectedError):
        engine.run("SELECT * FROM threat_intel", QueryScope(None), intel=False)


def test_feodo_uses_conditional_requests(store: FeedStore, tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=FEODO, headers={"etag": '"v1"'})

    up = FeedUpdater(
        store,
        AuditLog(MetaDB(tmp_path / "meta.sqlite")),
        client=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )
    st = up.update("intel_feodo", None)
    assert st.entries == 2 and st.etag == '"v1"'
    assert str(seen[0].url) == "https://feodotracker.abuse.ch/downloads/ipblocklist.csv"
    st = up.update("intel_feodo", None)
    assert seen[1].headers["if-none-match"] == '"v1"' and st.entries == 2


def test_threatfox_needs_a_key_and_sends_it_only_to_abuse_ch(
    store: FeedStore, tmp_path: Path
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=THREATFOX)

    meta = MetaDB(tmp_path / "meta.sqlite")
    keys: dict[str, str] = {}
    up = FeedUpdater(
        store,
        AuditLog(meta),
        client=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
        key=keys.get,
    )
    st = up.update("intel_threatfox", None)
    assert "Auth-Key" in (st.error or "") and not seen
    store.set_key("intel_threatfox", "sealed-value")
    keys["intel_threatfox"] = "secret-key-123"
    st = up.update("intel_threatfox", "admin1")
    assert st.entries == 2 and st.error is None
    req = seen[0]
    assert str(req.url) == "https://threatfox-api.abuse.ch/api/v1/"
    assert req.headers["auth-key"] == "secret-key-123"
    assert json.loads(req.content) == {"query": "get_iocs", "days": 7}
    up.update("intel_threatfox", None)
    assert json.loads(seen[1].content)["days"] == 1  # recent: only the last day's additions
    with meta.connect() as con:
        trail = " ".join(str(r[0]) for r in con.execute("SELECT detail FROM audit_log"))
    assert "secret-key-123" not in trail


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def _listed_ip(lab: dict[str, Any]) -> str:
    rows = (
        lab["admin"]
        .post(
            "/api/query",
            json={
                "sql": "SELECT DISTINCT src_endpoint_ip FROM events WHERE src_endpoint_ip IS NOT NULL"
            },
            headers=lab["h"],
        )
        .json()["rows"]
    )
    assert rows, "the lab needs events with a source address"
    return str(rows[0][0])


def test_search_marks_and_facets(lab: dict[str, Any]) -> None:
    ip = _listed_ip(lab)
    h = lab["h"]
    up = lab["admin"].post(
        "/api/enrichment/feeds/intel_custom/upload", content=f"{ip},Lab test listing\n", headers=h
    )
    assert up.status_code == 200, up.text
    assert up.json()["kind"] == "intel" and up.json()["entries"] == 1
    compiled = lab["admin"].post("/api/search/compile", json={"text": "intel:listed"}, headers=h)
    assert compiled.status_code == 200, compiled.text
    sql = compiled.json()["sql"]
    params = compiled.json().get("params", {})
    res = lab["admin"].post("/api/query", json={"sql": sql, "params": params}, headers=h).json()
    assert res["rows"], res
    sql2 = f"SELECT src_endpoint_ip FROM events WHERE src_endpoint_ip = '{ip}' LIMIT 1"
    res2 = lab["admin"].post("/api/query", json={"sql": sql2}, headers=h).json()
    assert res2["intel"][ip][0] == {
        "feed": "Your list",
        "type": "ip",
        "threat": "Lab test listing",
        "last_seen": None,
    }
    facets = (
        lab["admin"]
        .post("/api/search/facets", json={"text": "intel:listed"}, headers=h)
        .json()["facets"]
    )
    intel_facet = next(f for f in facets if f["field"] == "intel")
    assert intel_facet["values"][0]["value"] == "Lab test listing"
    narrowed = (
        lab["admin"]
        .post("/api/search/compile", json={"text": 'intel:"lab test"'}, headers=h)
        .json()
    )
    assert narrowed["sql"]


def test_feed_settings_roles_and_key_never_returned(lab: dict[str, Any]) -> None:
    h = lab["h"]
    assert (
        lab["ana"].put("/api/enrichment/feeds/intel_threatfox", json={"key": "abc"}).status_code
        == 403
    )
    res = lab["admin"].put(
        "/api/enrichment/feeds/intel_threatfox", json={"key": "abc-123"}, headers=h
    )
    assert res.status_code == 200 and res.json()["has_key"] is True
    assert "abc-123" not in res.text
    assert "abc-123" not in lab["admin"].get("/api/enrichment").text
    bad = lab["admin"].put("/api/enrichment/feeds/geoip_asn", json={"enabled": False}, headers=h)
    assert bad.status_code == 400
    off = lab["admin"].put("/api/enrichment/feeds/intel_feodo", json={"enabled": False}, headers=h)
    assert off.json()["enabled"] is False
    events = lab["aud"].get("/api/audit/events", params={"action": "enrichment.feed"}).json()
    assert events and all("abc-123" not in json.dumps(e) for e in events)


def test_an_unchanged_list_is_current_as_of_the_check(store: FeedStore, tmp_path: Path) -> None:
    """F67: a 304 after eight days means the list is current now, not eight days old; a
    404 says so on the row and is never counted as current."""
    from datetime import timedelta

    later = [NOW]
    answer = {"code": 200}

    def handler(req: httpx.Request) -> httpx.Response:
        if answer["code"] != 200:
            return httpx.Response(answer["code"])
        return httpx.Response(200, content=FEODO, headers={"etag": '"v1"'})

    up = FeedUpdater(
        store,
        AuditLog(MetaDB(tmp_path / "meta.sqlite")),
        client=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: later[0],
    )
    up.update("intel_feodo", None)
    store._clock = lambda: later[0]  # type: ignore[method-assign]  # the store judges age now
    later[0] = NOW + timedelta(days=8)
    assert store.level(store.state("intel_feodo")) == "unhealthy"
    answer["code"] = 304
    st = up.update("intel_feodo", None)
    assert st.confirmed_at == later[0].isoformat() and st.error is None
    assert store.level(st) == "healthy" and st.installed_at == NOW.isoformat()
    later[0] = NOW + timedelta(days=17)
    answer["code"] = 404
    st = up.update("intel_feodo", None)
    assert st.error == "The feed server answered HTTP 404"
    assert st.confirmed_at == (NOW + timedelta(days=8)).isoformat()
