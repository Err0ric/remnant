"""The query library entries that were the example saved searches (ADR-0033 row 10) save,
pass the guard, and answer on fixture data."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_config
from app.engine.duckdb import QueryScope
from app.main import create_app
from app.search.addresses import OBS_SQL
from app.search.library import LIBRARY_DIR, load_dir

ROOT = Path(__file__).resolve().parents[3]
FIX = Path(__file__).parent.parent / "fixtures" / "logs"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
RANGE = {"start": "2026-10-09T00:00:00Z", "end": "2026-10-10T00:00:00Z"}


def _pan_dhcp(
    t: str,
    ip: str,
    mac: str,
    host: str,
    iface: str = "ethernet1/2",
    ended: bool = False,
    day: int = 9,
) -> str:
    """A PAN-OS DHCP lease line. The description is one CSV cell, so a quoted interface
    name has its quotes doubled, as the firewall sends it."""
    event, word = ("lease-end", "ended") if ended else ("lease-start", "started")
    text = f"DHCP lease {word} ip {ip} --> mac {mac} - hostname {host}, interface {iface}"
    when = f"2026/10/{day:02d} {t}"
    return (
        f"<14>Oct {day:>2} {t} pa-fw01 1,{when},012345678901,SYSTEM,dhcp,,{when},vsys1,"
        f'{event},,,,general,informational,"{text.replace(chr(34), chr(34) * 2)}",,,,,,,,pa-fw01'
    )


def _gp(t: str, event: str, user: str, laptop: str, ip: str) -> str:
    """A GlobalProtect line giving `ip` to `user` on `laptop` (gateway-logout ends it)."""
    when = f"2026/10/09 {t}"
    return (
        f"<14>Oct  9 {t} pa-fw01 1,{when},012345678901,GLOBALPROTECT,0,,{when},vsys1,{event},"
        f"login,LDAP,SSL,{user},,{laptop},203.0.113.9,,{ip},,,,,,,,,,,success,,,,,gp-portal,"
        ",,,,,,,,,,,,,,pa-fw01"
    )


def _dns(t: str, client: str, name: str) -> str:
    return (
        f"<30>Oct  9 {t} ns1 named[812]: client {client}#53212 ({name}): "
        f"query: {name} IN A +E(0)K (10.20.0.53)"
    )


MS = "f8cdef31-a31e-4b4a-93e4-5f571e91255a"  # Microsoft's first-party tenant
OTHER = "0f0f0f0f-0000-4000-8000-00000000abcd"  # an invented app owner


def _dir(t: str, activity: str, by: str, who: str, owner: str) -> str:
    actor = (
        {"user": {"userPrincipalName": who, "ipAddress": "203.0.113.5"}}
        if by == "user"
        else {"app": {"displayName": who}}
    )
    return json.dumps(
        {
            "id": f"Directory_{t.replace(':', '')}",
            "category": "ApplicationManagement",
            "result": "success",
            "activityDisplayName": activity,
            "activityDateTime": f"2026-10-09T{t}Z",
            "loggedByService": "Core Directory",
            "operationType": "Add",
            "initiatedBy": actor,
            "targetResources": [
                {
                    "displayName": "Example App",
                    "type": "ServicePrincipal",
                    "modifiedProperties": [
                        {"displayName": "AppOwnerOrganizationId", "newValue": f'["{owner}"]'}
                    ],
                }
            ],
        },
        separators=(",", ":"),
    )


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("examples")
    logs = tmp / "logs"
    for sub in ("dns", "fw", "gp", "ssh", "m365"):
        (logs / sub).mkdir(parents=True)
    # 10.20.1.5 was LAPTOP-A until 12:00, then the address went to LAPTOP-B.
    (logs / "fw" / "system.log").write_text(
        "\n".join(
            [
                _pan_dhcp("08:00:00", "10.20.1.5", "00:00:5e:00:53:0a", "LAPTOP-A"),
                _pan_dhcp("12:00:00", "10.20.1.5", "00:00:5e:00:53:0b", "LAPTOP-B"),
                # 10.20.1.7: leased the evening before the range, ended inside it (quoted
                # interface). 10.20.1.8: started and ended inside it (unquoted, dotted).
                _pan_dhcp(
                    "22:00:00", "10.20.1.7", "00:00:5e:00:53:0c", "LAPTOP-C", '"vlan20"', day=8
                ),
                _pan_dhcp(
                    "06:00:00", "10.20.1.7", "00:00:5e:00:53:0c", "LAPTOP-C", '"vlan20"', True
                ),
                # 10.20.1.9: the same MAC again after its end line. 10.20.1.10: A, then
                # B, then A's end line late. 10.20.1.11: an empty hostname.
                _pan_dhcp("13:00:00", "10.20.1.9", "00:00:5e:00:53:0e", "LAPTOP-E"),
                _pan_dhcp("14:00:00", "10.20.1.9", "00:00:5e:00:53:0e", "LAPTOP-E", ended=True),
                _pan_dhcp("15:00:00", "10.20.1.9", "00:00:5e:00:53:0e", "LAPTOP-E"),
                _pan_dhcp("08:00:00", "10.20.1.10", "00:00:5e:00:53:a1", "HOST-A"),
                _pan_dhcp("12:00:00", "10.20.1.10", "00:00:5e:00:53:b1", "HOST-B"),
                _pan_dhcp("12:05:00", "10.20.1.10", "00:00:5e:00:53:a1", "HOST-A", ended=True),
                _pan_dhcp("09:00:00", "10.20.1.11", "00:00:5e:00:53:d1", ""),
                # 10.20.1.12: started and ended in the same second.
                _pan_dhcp("16:00:00", "10.20.1.12", "00:00:5e:00:53:e1", "HOST-E"),
                _pan_dhcp("16:00:00", "10.20.1.12", "00:00:5e:00:53:e1", "HOST-E", ended=True),
                _pan_dhcp("07:00:00", "10.20.1.8", "00:00:5e:00:53:0d", "LAPTOP-D", "ae0.120"),
                _pan_dhcp(
                    "09:30:00", "10.20.1.8", "00:00:5e:00:53:0d", "LAPTOP-D", "ae0.120", True
                ),
                *(FIX / "paloalto_system" / "sample.log").read_text().splitlines(),
            ]
        )
        + "\n"
    )
    (logs / "dns" / "q.log").write_text(
        "\n".join(
            [
                _dns("09:00:00", "10.20.1.5", "chatgpt.com"),
                _dns("09:30:00", "10.20.1.5", "api.openai.com"),
                _dns("13:00:00", "10.20.1.5", "claude.ai"),
                _dns("13:05:00", "10.20.1.6", "bzr.openai.com"),  # an ad tag, not use
                _dns("13:10:00", "10.20.1.6", "www.example.com"),
            ]
        )
        + "\n"
    )
    (logs / "gp" / "gp.log").write_text(
        (FIX / "paloalto_globalprotect" / "sample.log").read_text()
        + "\n".join(
            [  # 10.30.0.9: two tunnels for erin, a new one after gateway-logout
                _gp("08:00:00", "gateway-auth", "erin", "LAPTOP-ERIN", "10.30.0.9"),
                _gp("08:00:05", "gateway-connected", "erin", "LAPTOP-ERIN", "10.30.0.9"),
                _gp("09:00:00", "gateway-logout", "erin", "LAPTOP-ERIN", "10.30.0.9"),
                _gp("10:00:00", "gateway-auth", "erin", "LAPTOP-ERIN", "10.30.0.9"),
            ]
        )
        + "\n"
    )
    (logs / "ssh" / "auth.log").write_text((FIX / "linux_sshd" / "sample.log").read_text())
    # Directory audits: Microsoft's own provisioning (two ways), a real app, a consent.
    (logs / "m365" / "dir.jsonl").write_text(
        "\n".join(
            [
                _dir("10:00:00", "Add service principal", "app", "Azure Resource Manager", MS),
                _dir("10:05:00", "Add service principal", "user", "admin@example.com", MS),
                _dir("10:10:00", "Add service principal", "user", "admin@example.com", OTHER),
                _dir("10:20:00", "Consent to application", "user", "bob@example.com", OTHER),
            ]
        )
        + "\n"
    )
    config = load_config(
        Path("missing.yaml"),
        {"APP__PATHS__DATA_DIR": str(tmp / "data"), "APP__PATHS__ALLOWED_ROOTS": str(logs)},
    )
    app = create_app(config)
    app.state.ingest._clock = lambda: NOW
    c = TestClient(app, base_url="http://127.0.0.1")
    for sid, tid, sub in (
        ("dns", "dns_bind", "dns"),
        ("fw", "paloalto_system", "fw"),
        ("gp", "paloalto_globalprotect", "gp"),
        ("ssh", "linux_sshd", "ssh"),
        ("m365", "m365_directory_audit", "m365"),
    ):
        fmt = "json" if sid == "m365" else "syslog"
        body = {"source_id": sid, "format": fmt, "path": str(logs / sub), "template_id": tid}
        assert c.post("/api/sources", json=body).status_code == 201
    app.state.ingest.run_once()
    for pack in load_dir(LIBRARY_DIR):
        for q in pack.queries:
            body = q.spec(pack.origin(q)).model_dump()
            res = c.post("/api/searches", json=body)
            assert res.status_code == 201, (q.id, res.text)
    return c


def run(client: TestClient, search_id: str, **params: Any) -> dict[str, Any]:
    res = client.post(f"/api/searches/{search_id}/run", json={**RANGE, "params": params})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


def rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(body["columns"], r, strict=True)) for r in body["rows"]]


def test_every_library_query_is_documented(client: TestClient) -> None:
    doc = (ROOT / "docs" / "searching.md").read_text()
    for pack in load_dir(LIBRARY_DIR):
        for q in pack.queries:
            assert q.id in doc, f"{pack.id}/{q.id} is not in docs/searching.md"


def test_ai_services_from_dns(client: TestClient) -> None:
    got = {r["service"]: r for r in rows(run(client, "ai_services_dns"))}
    assert set(got) == {"ChatGPT", "OpenAI API", "Claude"}  # the ad tag is not use
    assert got["ChatGPT"]["queries"] == 1 and got["ChatGPT"]["clients"] == 1


def test_ai_services_by_device_follow_the_lease_at_the_time(client: TestClient) -> None:
    got = {(r["device"], r["service"]) for r in rows(run(client, "ai_services_by_device"))}
    assert got == {("LAPTOP-A", "ChatGPT"), ("LAPTOP-A", "OpenAI API"), ("LAPTOP-B", "Claude")}


def test_who_had_an_address(client: TestClient) -> None:
    """One row per lease, newest first: the address went from LAPTOP-A to LAPTOP-B, then to
    ws-0105 (the template fixture's lease, which started and ended)."""
    dhcp = [r for r in rows(run(client, "who_had_ip", ip="10.20.1.5")) if r["kind"] == "DHCP lease"]
    assert [r["device"] for r in dhcp] == ["ws-0105", "LAPTOP-B", "LAPTOP-A"]
    assert dhcp[0]["interface"] == "ae0.120" and dhcp[1]["interface"] == "ethernet1/2"
    assert dhcp[0]["first_seen"] < dhcp[0]["last_seen"]  # the start line and the end line
    vpn = rows(run(client, "who_had_ip", ip="10.30.0.5"))
    assert vpn and all(r["kind"] == "VPN tunnel" and r["person"] for r in vpn)


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_who_had_an_address_from_a_lease_that_started_before_the_range(
    client: TestClient,
) -> None:
    """Owner, 2026-11-17: a lease that started before the range still shows, from its
    "lease ended" line; the quoted interface name is read without its quotes."""
    (got,) = rows(run(client, "who_had_ip", ip="10.20.1.7"))
    assert (got["kind"], got["device"], got["mac"]) == (
        "DHCP lease",
        "LAPTOP-C",
        "00:00:5e:00:53:0c",
    )
    assert got["interface"] == "vlan20"
    assert _at(got["first_seen"]) == _at(got["last_seen"]) == datetime(2026, 10, 9, 6, tzinfo=UTC)


def test_who_had_an_address_from_its_start_and_end_lines(client: TestClient) -> None:
    (got,) = rows(run(client, "who_had_ip", ip="10.20.1.8"))
    assert (got["device"], got["interface"]) == ("LAPTOP-D", "ae0.120")
    assert _at(got["first_seen"]) == datetime(2026, 10, 9, 7, tzinfo=UTC)
    assert _at(got["last_seen"]) == datetime(2026, 10, 9, 9, 30, tzinfo=UTC)


def test_who_had_an_address_with_no_lease_is_empty(client: TestClient) -> None:
    assert rows(run(client, "who_had_ip", ip="10.20.9.9")) == []


@pytest.mark.parametrize("search_id", ["parser_mix", "ssh_logins", "firewall_maintenance"])
def test_summaries_return_rows(client: TestClient, search_id: str) -> None:
    assert run(client, search_id)["rows"], search_id


def test_new_service_principals_leave_out_microsofts_own(client: TestClient) -> None:
    got = rows(run(client, "m365_new_service_principals"))
    assert [(r["actor"], r["message"]) for r in got] == [
        ("admin@example.com", "Add service principal")
    ]
    assert OTHER in got[0]["raw"]


def test_user_consent(client: TestClient) -> None:
    got = rows(run(client, "m365_user_consent"))
    assert [r["user"] for r in got] == ["bob@example.com"]


def test_built_in_resolution_names_what_the_example_search_names(client: TestClient) -> None:
    """ADR-0029 reference test: the DHCP lease at each time, from the address lookup and
    from AI usage, matches the who_had_ip and ai_services_by_device example searches."""
    for at, device in (("2026-10-09T09:00:00Z", "LAPTOP-A"), ("2026-10-09T13:00:00Z", "LAPTOP-B")):
        res = client.get("/api/addresses/10.20.1.5", params={"at": at})
        assert res.status_code == 200, res.text
        spans = res.json()["spans"]
        dhcp = [s for s in spans if s["kind"] == "dhcp"]
        assert dhcp[0]["machine"] == device and dhcp[0]["person"] is None  # never a person
        assert dhcp[0]["mac"] and dhcp[0]["source"]
    usage = client.get("/api/ai/usage", params={"start": RANGE["start"], "end": RANGE["end"]})
    machines = {
        (u["service"]["id"], m) for u in usage.json()["services"] for m in u["top_machines"]
    }
    assert {("chatgpt", "LAPTOP-A"), ("claude", "LAPTOP-B")} <= machines


def test_who_had_an_address_starts_a_new_row_after_an_end_line(client: TestClient) -> None:
    got = rows(run(client, "who_had_ip", ip="10.20.1.9"))
    spans = [(_at(r["first_seen"]).hour, _at(r["last_seen"]).hour) for r in got]
    assert [r["mac"] for r in got] == ["00:00:5e:00:53:0e"] * 2 and spans == [(15, 15), (13, 14)]


def test_who_had_an_address_ends_a_row_at_the_next_holders_start(client: TestClient) -> None:
    """A's end line arrives after B took the address: A's row still ends at B's start, and
    B, the newest holder, comes first."""
    got = rows(run(client, "who_had_ip", ip="10.20.1.10"))
    assert [r["device"] for r in got] == ["HOST-B", "HOST-A"]
    a = got[1]
    assert _at(a["first_seen"]) == datetime(2026, 10, 9, 8, tzinfo=UTC)
    assert _at(a["last_seen"]) == datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_who_had_an_address_with_an_empty_hostname(client: TestClient) -> None:
    (got,) = rows(run(client, "who_had_ip", ip="10.20.1.11"))
    assert got["device"] is None and got["mac"] == "00:00:5e:00:53:d1"


def test_who_had_an_address_gives_one_row_per_vpn_tunnel(client: TestClient) -> None:
    got = rows(run(client, "who_had_ip", ip="10.30.0.9"))
    assert [(r["kind"], r["person"], r["device"]) for r in got] == [
        ("VPN tunnel", "erin", "LAPTOP-ERIN")
    ] * 2
    assert _at(got[0]["first_seen"]) == datetime(2026, 10, 9, 10, tzinfo=UTC)
    assert _at(got[1]["first_seen"]) == datetime(2026, 10, 9, 8, tzinfo=UTC)
    assert _at(got[1]["last_seen"]) == datetime(2026, 10, 9, 9, tzinfo=UTC)


BUILT_IN_DHCP = f"""WITH {OBS_SQL}
SELECT host, mac, start, stop, capped FROM addr_span
WHERE kind = 'dhcp' AND ip = $ip ORDER BY start"""  # fixed text


def test_built_in_resolution_and_who_had_ip_agree_on_dhcp_leases(client: TestClient) -> None:
    """Owner, 2026-11-17 (D278): over the same range, the built-in holds each address for
    the same machines, in the same order, as who_had_ip lists them, and over every line
    the library saw. A lease ended by its end line stops there in both; one cut short by
    the next holder stops at that start; one seen only by its end line runs up to it."""
    engine = client.app.state.engine  # type: ignore[attr-defined]  # the test app
    scope = QueryScope(["fw"], _at(RANGE["start"]), _at(RANGE["end"]))
    ips = ["10.20.1.5", "10.20.1.7", "10.20.1.8", "10.20.1.9", "10.20.1.10", "10.20.1.12"]
    ips.append("10.20.2.14")
    for ip in ips:
        lib = sorted(
            (r for r in rows(run(client, "who_had_ip", ip=ip)) if r["kind"] == "DHCP lease"),
            key=lambda r: r["first_seen"],
        )
        built = [
            (h, m, _at(str(a)), _at(str(b)), c)
            for h, m, a, b, c in engine.run(BUILT_IN_DHCP, scope, {"ip": ip}).rows
        ]
        assert [(r["device"], r["mac"]) for r in lib] == [(b[0], b[1]) for b in built], ip
        for i, (r, (_, _, start, stop, capped)) in enumerate(zip(lib, built, strict=True)):
            first, last = _at(r["first_seen"]), _at(r["last_seen"])
            assert start <= first and last <= stop, (ip, r)
            nxt = built[i + 1][2] if i + 1 < len(built) else None
            assert capped or stop in (last, nxt), (ip, r)
            assert start == first or (first == last == stop and not capped), (ip, r)
    # 10.20.1.7 started the evening before the range: the built-in names it until its end.
    ((host, _, start, stop, _),) = engine.run(BUILT_IN_DHCP, scope, {"ip": "10.20.1.7"}).rows
    assert host == "LAPTOP-C" and _at(str(start)) < datetime(2026, 10, 9, 5, tzinfo=UTC)
    assert _at(str(stop)) == datetime(2026, 10, 9, 6, tzinfo=UTC)
