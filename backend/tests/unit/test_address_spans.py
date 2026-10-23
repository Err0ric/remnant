"""Who had an address as spans (ADR-0029 / D107): ends, labelled caps, precedence, DHCP
as machines only, and the chain from a machine to its person through a sign-in."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb
import pytest

from app.search.addresses import OBS_SQL, address_ctes

T0 = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
COLS = (
    "template_id VARCHAR, class_uid INTEGER, status_id INTEGER, activity_id INTEGER,"
    " src_endpoint_ip VARCHAR, src_endpoint_hostname VARCHAR, device_hostname VARCHAR,"
    " actor_user_name VARCHAR, message VARCHAR, unmapped VARCHAR, source_id VARCHAR,"
    " time TIMESTAMPTZ, time_observed TIMESTAMPTZ"
)


def ev(minutes: float, template: str, **f: Any) -> dict[str, Any]:
    t = T0 + timedelta(minutes=minutes)
    return {
        "template_id": template,
        "class_uid": f.get("class_uid", 3002),
        "status_id": f.get("status_id", 1),
        "activity_id": f.get("activity_id", 1),
        "src_endpoint_ip": f.get("ip"),
        "src_endpoint_hostname": f.get("host"),
        "device_hostname": f.get("device"),
        "actor_user_name": f.get("user"),
        "message": f.get("message"),
        "unmapped": json.dumps(f.get("unmapped", {})),
        "source_id": f.get("source", template),
        "time": t,
        "time_observed": t,
    }


def vpn(m: float, ip: str, user: str, laptop: str, logout: bool = False) -> dict[str, Any]:
    return ev(
        m, "paloalto_globalprotect", user=user, host=laptop, activity_id=2 if logout else 1,
        unmapped={"private_ip": ip},
    )  # fmt: skip


def dhcp(m: float, ip: str, host: str) -> dict[str, Any]:
    return ev(
        m, "paloalto_system", class_uid=0, unmapped={"subtype": "dhcp"},
        message=f"DHCP lease started ip {ip} --> mac 00:00:5e:00:53:0a - hostname {host}, "
        "interface ethernet1/2",
    )  # fmt: skip


def signin(m: float, user: str, device: str, ok: bool = True) -> dict[str, Any]:
    return ev(
        m, "m365_signin", user=user, device=device, ip="203.0.113.10", status_id=1 if ok else 2
    )


def resolve(events: list[dict[str, Any]], ip: str, minutes: float) -> dict[str, Any]:
    con = duckdb.connect()
    con.execute(f"CREATE TABLE events ({COLS})")
    for e in events:
        con.execute(
            f"INSERT INTO events VALUES ({', '.join('?' * len(e))})", list(e.values())
        )  # test table
    at = T0 + timedelta(minutes=minutes)
    sql = f"""WITH {OBS_SQL},
need AS (SELECT ?::VARCHAR AS ip, ?::TIMESTAMPTZ AS t),
{address_ctes("need", obs=False)}
SELECT rwho, rhost, rwho_how, rwho_capped, rhost_how, rhost_capped, rwho_dev FROM addr"""
    row = con.execute(sql, [ip, at]).fetchone()
    keys = ("who", "host", "who_how", "who_capped", "host_how", "host_capped", "dev")
    return dict(zip(keys, row or (None,) * 7, strict=True))


def test_a_vpn_session_ends_at_logout_and_the_next_holder_takes_over() -> None:
    evs = [
        vpn(0, "10.30.0.5", "alice", "LAPTOP-A"),
        vpn(120, "10.30.0.5", "alice", "LAPTOP-A", logout=True),
        vpn(300, "10.30.0.5", "bob", "LAPTOP-B"),
    ]
    assert resolve(evs, "10.30.0.5", 60)["who"] == "alice"
    # After her logout, and before bob: nobody (the old rule kept alice for 12 hours).
    assert resolve(evs, "10.30.0.5", 190)["who"] is None
    after = resolve(evs, "10.30.0.5", 330)
    assert (after["who"], after["who_how"], after["who_capped"]) == ("bob", "vpn", True)


def test_a_session_with_no_end_is_capped_and_says_so() -> None:
    evs = [vpn(0, "10.30.0.7", "carol", "LAPTOP-C")]
    inside = resolve(evs, "10.30.0.7", 23 * 60)
    assert (inside["who"], inside["who_capped"]) == ("carol", True)  # assumed, labelled
    assert resolve(evs, "10.30.0.7", 25 * 60)["who"] is None  # past the 24 h cap


def test_dhcp_names_a_machine_never_a_person() -> None:
    evs = [dhcp(0, "10.20.1.5", "WS-0042")]
    r = resolve(evs, "10.20.1.5", 30)
    assert (r["who"], r["host"], r["host_how"]) == (None, "WS-0042", "dhcp")


def test_a_sign_in_on_the_dhcp_machine_names_its_person_in_two_steps() -> None:
    evs = [dhcp(0, "10.20.1.5", "WS-0042"), signin(10, "alice@example.com", "WS-0042")]
    r = resolve(evs, "10.20.1.5", 30)
    assert (r["who"], r["who_how"], r["host"], r["dev"]) == (
        "alice@example.com", "signin", "WS-0042", "WS-0042",
    )  # fmt: skip


def test_two_people_on_one_machine_name_nobody() -> None:
    evs = [
        dhcp(0, "10.20.1.5", "WS-0042"),
        signin(5, "alice@example.com", "WS-0042"),
        signin(20, "bob@example.com", "WS-0042"),
    ]
    r = resolve(evs, "10.20.1.5", 30)
    assert (r["who"], r["who_how"]) == (None, "several")


def test_a_failed_sign_in_or_a_sign_in_address_names_nobody() -> None:
    evs = [dhcp(0, "10.20.1.5", "WS-0042"), signin(10, "eve@example.com", "WS-0042", ok=False)]
    assert resolve(evs, "10.20.1.5", 30)["who"] is None
    # The sign-in's own address is the office's public egress: never resolved to a person.
    assert resolve([signin(10, "alice@example.com", "WS-0042")], "203.0.113.10", 30)["who"] is None


@pytest.mark.parametrize(
    ("events", "who", "how"),
    [
        # VPN wins over a logon at the same time; a logon wins over nothing.
        (
            [vpn(0, "10.30.0.9", "dana", "LAPTOP-D"),
             ev(5, "windows_nxlog_json", ip="10.30.0.9", user="svc_backup", host="SRV1")],
            "dana", "vpn",
        ),
        ([ev(5, "windows_nxlog_json", ip="10.30.0.9", user="erin", host="WS-7")], "erin", "logon"),
    ],
)  # fmt: skip
def test_precedence(events: list[dict[str, Any]], who: str, how: str) -> None:
    r = resolve(events, "10.30.0.9", 30)
    assert (r["who"], r["who_how"]) == (who, how)
