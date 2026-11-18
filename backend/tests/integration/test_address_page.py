"""The address page's sections (owner P4, fix batch of 2026-11-17): four library queries on
the caller's view, each said plainly when the caller has no source for it."""

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_ask_routing import lab as routing_lab  # noqa: F401  # fixture
from tests.integration.test_schedules import FIX

IP = "10.20.2.14"
RANGE = {"start": "2026-10-09T00:00:00Z", "end": "2026-10-11T00:00:00Z"}
DNS = [("chatgpt.com", 3), ("www.example.com", 2), ("updates.example.net.", 1)]


MANY = 55
GUEST = "10.20.7.7"


def lease(i: int) -> str:
    at = f"2026/10/10 {i // 60:02d}:{i % 60:02d}:00"
    return (
        f"<14>1 2026-10-10T{i // 60:02d}:{i % 60:02d}:00Z pa-fw01 - - - - 1,{at},012345678901,"
        f'SYSTEM,dhcp,,{at},vsys1,lease-start,,,,general,informational,"DHCP lease started ip'
        f' {GUEST} --> mac 00:00:5e:00:53:{i:02x} - hostname ws-7{i:03d}, interface ae0.120"'
        ",,,,,,,,pa-fw01\n"
    )


def dns_line(i: int, client: str, name: str) -> str:
    return (
        f"<30>Oct 10 11:{i:02d}:00 ns1 named[800]: client {client}#53 ({name}): "
        f"query: {name} IN A +E(0)K (10.20.0.53)"
    )


@pytest.fixture
def lab(routing_lab: dict[str, Any], tmp_path: Path) -> dict[str, Any]:  # noqa: F811  # fixture
    """The routing lab (ana and bob read only lin_auth) plus DNS, Palo Alto DHCP, and
    Palo Alto traffic sources only the admin reads."""
    a, h = routing_lab["admin"], routing_lab["h"]
    logs = tmp_path / "logs"
    lines = [dns_line(i, IP, n) for i, n in enumerate(n for n, k in DNS for _ in range(k))]
    lines.append(dns_line(50, "10.20.1.9", "other.example.org"))  # another client's
    (logs / "dns").mkdir()
    (logs / "dns" / "q.log").write_text("\n".join(lines) + "\n")
    for sub, tid in (("pa_sys", "paloalto_system"), ("pa_traffic", "paloalto_traffic")):
        (logs / sub).mkdir()
        shutil.copy(FIX / tid / "sample.log", logs / sub / "a.log")
    # 55 holders of one guest address in a day: more leases than the section shows.
    (logs / "pa_sys" / "guests.log").write_text("".join(lease(i) for i in range(MANY)))
    for sid, tid in (("dns", "dns_bind"), ("pa_sys", "paloalto_system"), ("pa_traffic", "paloalto_traffic")):  # fmt: skip
        body = {"source_id": sid, "format": "syslog", "path": str(logs / sid), "template_id": tid}
        assert a.post("/api/sources", json=body, headers=h).status_code == 201, sid
    routing_lab["app"].state.ingest.run_once()
    return routing_lab


def section(client: Any, name: str, ip: str = IP) -> dict[str, Any]:
    res = client.get(f"/api/addresses/{ip}/sections/{name}", params=RANGE)
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def rows(s: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(s["columns"], r, strict=True)) for r in s["rows"]]


def test_dhcp_history_is_the_who_had_ip_library_query(lab: dict[str, Any]) -> None:
    s = section(lab["admin"], "dhcp")
    assert s["state"] == "ok" and s["library"].startswith("paloalto/who_had_ip@")
    assert s["read"] == ["pa_sys"] and s["title"] == "DHCP and VPN history"
    (lease,) = rows(s)
    assert (lease["kind"], lease["device"], lease["mac"]) == (
        "DHCP lease",
        "ws-0214",
        "00:00:5e:00:53:14",
    )
    assert lease["person"] is None  # DHCP names a machine, never a person (ADR-0048 S6)
    assert s["count"] == 1 and s["count_words"] == "1 lease or tunnel"


def test_dns_names_with_counts_first_and_last_seen(lab: dict[str, Any]) -> None:
    s = section(lab["admin"], "dns")
    got = [(r["name"], r["queries"]) for r in rows(s)]
    assert got == [("chatgpt.com", 3), ("www.example.com", 2), ("updates.example.net", 1)]
    first = rows(s)[0]
    assert first["first_seen"] < first["last_seen"]
    assert s["count_words"] == "3 names" and s["read"] == ["dns"]
    # Each name opens its own events in Logs: server-built, the address written in, the
    # range left to Logs.
    assert all(link and "{{start}}" in link and f"'{IP}'" in link for link in s["links"])
    assert "other.example.org" not in json.dumps(s)


def test_access_counts_by_kind_and_outcome(lab: dict[str, Any]) -> None:
    s = section(lab["admin"], "access")
    by = {(r["kind"], r["outcome"]): r["events"] for r in rows(s)}
    # Traffic to or from the address, as the page's other counts read it.
    assert by[("Firewall", "allowed")] >= 11 and by[("Firewall", "denied")] >= 2
    assert any(k == "SSH" for k, _ in by)
    assert s["count"] == sum(by.values()) and set(s["read"]) >= {"pa_traffic", "lin_auth"}
    # Only the sources that returned rows, each by its kind.
    found = {(f["source_id"], f["kind"]) for f in s["found"]}
    assert {("pa_traffic", "firewall"), ("lin_auth", "identity")} <= found
    assert "dns" not in {f["source_id"] for f in s["found"]}  # read, but no rows
    newest = rows(s)[0]["newest"]
    assert isinstance(newest, str) and newest
    assert len(s["links"]) == len(s["rows"]) and all(s["links"])


def test_ai_services_seen_from_the_address(lab: dict[str, Any]) -> None:
    s = section(lab["admin"], "ai")
    (svc,) = rows(s)
    assert svc["service"] == "ChatGPT" and svc["events"] == 3
    assert s["library"] == "AI usage"  # AI usage's own count, not a library query
    assert s["count_words"] == "1 AI service" and "dns" in s["read"]
    assert [f["source_id"] for f in s["found"]] == ["dns"]
    # Its count opens its events in Logs: the three ChatGPT lookups from this address.
    (link,) = s["links"]
    res = lab["admin"].post("/api/query", json={"sql": link, **RANGE}, headers=lab["h"])
    assert res.status_code == 200, res.text
    assert len(res.json()["rows"]) == 3


def test_an_analyst_sees_only_their_sources_and_is_told_what_is_missing(
    lab: dict[str, Any],
) -> None:
    dhcp = section(lab["ana"], "dhcp")
    assert dhcp["state"] == "no_source" and dhcp["rows"] == [] and dhcp["read"] == []
    assert "Palo Alto" in " ".join(dhcp["needs"])
    dns = section(lab["ana"], "dns")
    assert dns["state"] == "no_source" and dns["rows"] == []
    access = section(lab["ana"], "access")
    assert access["read"] == ["lin_auth"] and access["restricted"] is True
    assert {r["kind"] for r in rows(access)} == {"SSH"}  # no firewall rows
    ai = section(lab["ana"], "ai")
    assert ai["state"] == "ok" and ai["rows"] == []
    db = sqlite3.connect(lab["db"])
    details = [
        json.loads(d)
        for (d,) in db.execute(
            "SELECT detail FROM audit_log WHERE action = 'address.section' AND user_id = ?",
            (lab["ids"]["ana"],),
        )
    ]
    assert {d["section"] for d in details} == {"dhcp", "dns", "access", "ai"}
    assert all(d["sources_in_scope"] == ["lin_auth"] for d in details)


def test_an_empty_section_found_nothing_but_says_what_it_read(lab: dict[str, Any]) -> None:
    s = section(lab["admin"], "dhcp", "10.20.9.99")
    assert s["state"] == "ok" and s["rows"] == [] and s["read"] == ["pa_sys"]
    assert s["found"] == []


def test_only_an_address_has_sections(lab: dict[str, Any]) -> None:
    res = lab["admin"].get("/api/addresses/ws-0214/sections/dns", params=RANGE)
    assert res.status_code == 400
    assert lab["admin"].get(f"/api/addresses/{IP}/sections/logons").status_code == 422


def test_what_it_did_reads_firewall_traffic_as_allowed_or_denied(lab: dict[str, Any]) -> None:
    res = lab["admin"].get("/api/entities/summary", params={"kind": "ip", "value": IP, **RANGE})
    acts = [a for a in res.json()["activities"] if a["kind"] == "Network activity"]
    assert {a["outcome"] for a in acts} >= {"allowed", "denied"}


def test_a_cut_section_says_its_true_total(lab: dict[str, Any]) -> None:
    s = section(lab["admin"], "dhcp", GUEST)
    assert len(s["rows"]) == 50  # who_had_ip shows the newest 50
    assert s["count"] == MANY and s["count_words"] == f"{MANY} leases or tunnels"


@pytest.mark.parametrize("bad", ["fe80::1%25eth0", "fe80::1%25'x", "10.20.2"])
def test_a_scope_id_or_a_non_address_is_refused(lab: dict[str, Any], bad: str) -> None:
    res = lab["admin"].get(f"/api/addresses/{bad}/sections/ai", params=RANGE)
    assert res.status_code == 400, res.text


def test_sign_outs_are_not_sign_ins(lab: dict[str, Any]) -> None:
    """sshd's "Disconnected from user" is a sign-out (activity 2): the summary, What it
    did, the lanes, and the access card count it apart from sign-in attempts."""
    summary = (
        lab["admin"]
        .get("/api/entities/summary", params={"kind": "ip", "value": IP, **RANGE})
        .json()
    )
    access = rows(section(lab["admin"], "access"))
    signins = sum(
        r["events"]
        for r in access
        if r["kind"] not in ("Firewall", "Access check") and r["outcome"] != "signed out"
    )
    assert summary["sign_ins"] == signins
    assert any(r["outcome"] == "signed out" for r in access)
    graph = (
        lab["admin"]
        .get("/api/entities/graph", params={"mode": "entity", "kind": "ip", "value": IP, **RANGE})
        .json()
    )
    auth = [c for c in graph["cards"] if c["lane"] == 2 and c["group"] == "Authentication"]
    labels = [c["label"] for c in auth]
    assert len(set(labels)) == len(labels)  # never a duplicate label
    assert not any("#" in label for label in labels)  # no masked text cut to pieces
    assert {"Sign-in succeeded", "Sign-out"} <= set(labels)
    ok = next(c for c in auth if c["label"] == "Sign-in succeeded")
    ssh_ok = sum(r["events"] for r in access if (r["kind"], r["outcome"]) == ("SSH", "succeeded"))
    # Every SSH sign-in that succeeded, and no more than the summary counts.
    assert ssh_ok <= ok["events"] <= summary["succeeded"] and ok["hint"]


def test_users_tried_counts_the_same_sign_ins_as_the_kpi(lab: dict[str, Any]) -> None:
    """One source per number: the users and their counts are sign-ins (SIGNIN), so the
    list adds up to the Sign-ins number and holds as many users as the Users number."""
    for kind, value in (("ip", IP), ("host", "web-01")):
        s = (
            lab["admin"]
            .get("/api/entities/summary", params={"kind": kind, "value": value, **RANGE})
            .json()
        )
        users = [t for t in s["targets"] if t["kind"] == "user"]
        assert s["sign_ins"] and sum(t["events"] for t in users) == s["sign_ins"], kind
        assert len(users) == s["users"], kind
