"""GeoIP/ASN enrichment and the feed updater (ADR-0023). Synthetic databases only, built
with documentation addresses (RFC 5737), which a test predicate treats as public."""

import gzip
import ipaddress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from mmdb_writer import MMDBWriter
from netaddr import IPSet

from app.enrich.feeds import FEEDS, FeedStore, dbip_url
from app.enrich.geoip import GeoIP
from app.enrich.updater import FeedUpdater
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
TEST_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


def doc_public(addr: Any) -> bool:
    return any(addr in n for n in TEST_NETS)


def mmdb(tmp: Path, kind: str) -> bytes:
    if kind == "country":
        w = MMDBWriter(6, "DBIP-Country-Lite", ["en"], "test", ipv4_compatible=True)
        w.insert_network(
            IPSet(["203.0.113.0/24"]),
            {"country": {"iso_code": "NL", "names": {"en": "Netherlands"}}},
        )
        w.insert_network(
            IPSet(["198.51.100.0/24"]),
            {"country": {"iso_code": "US", "names": {"en": "United States"}}},
        )
    else:
        w = MMDBWriter(
            6, "DBIP-ASN-Lite (compat=GeoLite2-ASN)", ["en"], "test", ipv4_compatible=True
        )
        w.insert_network(
            IPSet(["203.0.113.0/24"]),
            {"autonomous_system_number": 64500, "autonomous_system_organization": "Example Net"},
        )
    path = tmp / f"{kind}.mmdb"
    w.to_db_file(str(path))
    return path.read_bytes()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Any]:
    meta = MetaDB(tmp_path / "meta.sqlite")
    store = FeedStore(meta, tmp_path, clock=lambda: NOW)
    return {"meta": meta, "store": store, "tmp": tmp_path}


def test_install_checks_kind_and_keeps_the_previous_file(env: dict[str, Any]) -> None:
    store: FeedStore = env["store"]
    country, asn = mmdb(env["tmp"], "country"), mmdb(env["tmp"], "asn")
    with pytest.raises(Exception, match="not GeoIP country"):
        store.install("geoip_country", asn, "upload")
    with pytest.raises(Exception, match="Not a MaxMind DB"):
        store.install("geoip_country", b"not a database" * 100, "upload")
    assert store.state("geoip_country").installed_at is None
    st = store.install("geoip_country", gzip.compress(country), "upload")  # .mmdb.gz as downloaded
    assert st.entries > 0 and st.source == "upload" and len(st.sha256 or "") == 64
    store.install("geoip_country", country, "upload")
    assert (store.path("geoip_country").parent / "previous.mmdb").is_file()


def test_lookups_are_local_and_skip_private_addresses(env: dict[str, Any]) -> None:
    store: FeedStore = env["store"]
    store.install("geoip_country", mmdb(env["tmp"], "country"), "upload")
    store.install("geoip_asn", mmdb(env["tmp"], "asn"), "upload")
    geo = GeoIP(store, public=doc_public)
    found = geo.enrich(["203.0.113.9", "10.0.0.5", "198.51.100.7", "not-an-ip", 42, "203.0.113.9"])
    assert set(found) == {"203.0.113.9", "198.51.100.7"}
    assert (found["203.0.113.9"].country, found["203.0.113.9"].asn) == ("NL", 64500)
    assert found["203.0.113.9"].org == "Example Net"
    assert found["198.51.100.7"].asn is None
    assert GeoIP(store).lookup("203.0.113.9") is None  # documentation addresses are not public


def test_age_levels_follow_the_edition(env: dict[str, Any], tmp_path: Path) -> None:
    store: FeedStore = env["store"]
    st = store.install("geoip_country", mmdb(env["tmp"], "country"), "download", version="2026-10")
    assert store.level(st) == "healthy"
    st.version = "2026-08"  # two editions behind
    assert store.level(st) == "attention"
    st.version = "2026-07"
    assert store.level(st) == "unhealthy"
    assert store.level(store.state("geoip_asn")) == "missing"


def _updater(env: dict[str, Any], handler: Any, seen: list[str]) -> FeedUpdater:
    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return handler(req)

    return FeedUpdater(
        env["store"],
        AuditLog(env["meta"]),
        client=lambda: httpx.Client(transport=httpx.MockTransport(wrapped)),
        clock=lambda: NOW,
    )


def test_updates_are_off_until_turned_on_then_download_once_a_month(env: dict[str, Any]) -> None:
    files = {
        "country": gzip.compress(mmdb(env["tmp"], "country")),
        "asn": gzip.compress(mmdb(env["tmp"], "asn")),
    }
    seen: list[str] = []
    up = _updater(
        env,
        lambda req: httpx.Response(
            200, content=files["country" if "country" in req.url.path else "asn"]
        ),
        seen,
    )
    assert up.run_due() == [] and seen == []  # a fresh install never calls out
    env["store"].set_auto_update(True, "admin1")
    done = up.run_due()
    assert [s.version for s in done if s.feed_id.startswith("geoip")] == ["2026-10", "2026-10"]
    seen[:] = [u for u in seen if "db-ip" in u]
    assert seen == [
        dbip_url(FEEDS["geoip_country"], "2026-10"),
        dbip_url(FEEDS["geoip_asn"], "2026-10"),
    ]
    assert all(u.startswith("https://download.db-ip.com/free/") for u in seen)
    assert up.run_due() == []  # checked a moment ago
    seen.clear()
    up.update("geoip_country", "admin1")
    assert seen == []  # this month's edition is installed: no request at all
    with env["meta"].connect() as con:
        actions = [r[0] for r in con.execute("SELECT action FROM audit_log")]
    assert actions.count("enrichment.update") >= 2


def test_failures_and_unpublished_editions_keep_the_current_file(env: dict[str, Any]) -> None:
    store: FeedStore = env["store"]
    store.install("geoip_country", mmdb(env["tmp"], "country"), "download", version="2026-09")
    seen: list[str] = []
    up = _updater(env, lambda req: httpx.Response(404), seen)
    st = up.update("geoip_country", None)
    assert st.version == "2026-09" and st.error is None and len(seen) == 1
    up = _updater(env, lambda req: httpx.Response(200, content=b"garbage" * 50), seen)
    st = up.update("geoip_country", None)
    assert st.version == "2026-09" and "MaxMind" in (st.error or "")
    up = _updater(env, lambda req: (_ for _ in ()).throw(httpx.ConnectError("down")), seen)
    st = up.update("geoip_country", None)
    assert "Could not reach" in (st.error or "") and st.version == "2026-09"
    up = _updater(
        env,
        lambda req: httpx.Response(302, headers={"location": "https://elsewhere.example"}),
        seen,
    )
    st = up.update("geoip_country", None)
    assert "HTTP 302" in (st.error or "")
    assert not any("elsewhere" in u for u in seen)  # redirects are not followed


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    out = make_lab(tmp_path)
    app = out["app"]
    app.state.geoip = GeoIP(app.state.feeds, public=doc_public)
    out["tmp"] = tmp_path
    return out


def test_api_status_settings_and_upload(lab: dict[str, Any]) -> None:
    status = lab["ana"].get("/api/enrichment").json()
    assert status["auto_update"] is False
    assert {f["level"] for f in status["feeds"]} == {"missing"}
    assert status["attribution"] == "IP Geolocation by DB-IP"
    h = lab["h"]
    assert lab["ana"].put("/api/enrichment/settings", json={"auto_update": True}).status_code == 403
    on = lab["admin"].put("/api/enrichment/settings", json={"auto_update": True}, headers=h)
    assert on.status_code == 200 and on.json()["auto_update"] is True
    data = mmdb(lab["tmp"], "country")
    up = lab["admin"].post(
        "/api/enrichment/feeds/geoip_country/upload",
        content=data,
        headers=h | {"content-type": "application/octet-stream"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["source"] == "upload" and up.json()["level"] == "healthy"
    bad = lab["admin"].post(
        "/api/enrichment/feeds/geoip_country/upload",
        content=b"nope" * 100,
        headers=h | {"content-type": "application/octet-stream"},
    )
    assert bad.status_code == 400
    assert (
        lab["admin"].post("/api/enrichment/feeds/other/upload", content=b"x", headers=h).status_code
        == 404
    )
    actions = {
        r["action"]
        for r in lab["aud"].get("/api/audit/events", params={"action": "enrichment."}).json()
    }
    assert {"enrichment.settings", "enrichment.upload"} <= actions


def test_query_results_carry_geo_for_public_addresses(lab: dict[str, Any]) -> None:
    lab["app"].state.feeds.install("geoip_country", mmdb(lab["tmp"], "country"), "upload")
    lab["app"].state.feeds.install("geoip_asn", mmdb(lab["tmp"], "asn"), "upload")
    res = lab["admin"].post(
        "/api/query",
        json={"sql": "SELECT '203.0.113.9' AS a, '10.0.0.5' AS b, 'x' AS c FROM events LIMIT 1"},
        headers=lab["h"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["geo"] == {
        "203.0.113.9": {
            "country": "NL",
            "country_name": "Netherlands",
            "asn": 64500,
            "org": "Example Net",
        }
    }


def test_places_default_to_private_ranges_and_take_public_egress(lab: dict[str, Any]) -> None:
    from app.enrich import networks

    h = lab["h"]
    assert lab["ana"].get("/api/enrichment/places").status_code == 403
    first = lab["admin"].get("/api/enrichment/places").json()
    assert first["approved_countries"] == []
    assert first["internal_set"] is False and first["has_public"] is False
    assert "10.0.0.0/8" in first["internal_networks"] and "fc00::/7" in first["internal_networks"]
    body = {
        "approved_countries": ["us", "NL", "US"],
        "internal_networks": [*first["internal_networks"], "198.51.100.7", "203.0.113.9/24"],
    }
    assert lab["ana"].put("/api/enrichment/places", json=body).status_code == 403
    saved = lab["admin"].put("/api/enrichment/places", json=body, headers=h)
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["approved_countries"] == ["NL", "US"]
    assert (
        "198.51.100.7/32" in out["internal_networks"]
        and "203.0.113.0/24" in out["internal_networks"]
    )
    assert out["internal_set"] is True and out["has_public"] is True
    for bad in ({"approved_countries": ["USA"], "internal_networks": []},
                {"approved_countries": [], "internal_networks": ["10.0.0.0/33"]},
                {"approved_countries": [], "internal_networks": ["not an address"]}):  # fmt: skip
        assert lab["admin"].put("/api/enrichment/places", json=bad, headers=h).status_code == 422
    places = networks.load(lab["app"].state.meta)
    nets = places.networks()
    assert networks.is_internal("203.0.113.77", nets) and networks.is_internal("10.1.2.3", nets)
    assert not networks.is_internal("198.51.100.8", nets)
    assert not networks.is_internal("garbage", nets)
    log = lab["admin"].get("/api/audit/events", params={"action": "enrichment.places"}).json()
    assert log and log[0]["detail"]["approved_countries"] == ["NL", "US"]
