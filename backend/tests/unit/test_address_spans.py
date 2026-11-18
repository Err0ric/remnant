"""Who had an address as spans (ADR-0029 / D107): ends, labelled caps, precedence, DHCP
as machines only, and the chain from a machine to its person through a sign-in."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb
import pytest

from app.search.addresses import (
    DHCP_ENDED,
    DHCP_HOST,
    DHCP_IP,
    DHCP_MAC,
    LOOKUP_SQL,
    OBS_SQL,
    address_ctes,
)
from app.search.library import LIBRARY_DIR, load_dir

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


def dhcp(
    m: float, ip: str, host: str, ended: bool = False, mac: str = "00:00:5e:00:53:0a"
) -> dict[str, Any]:
    word = "ended" if ended else "started"
    return ev(
        m, "paloalto_system", class_uid=0, unmapped={"subtype": "dhcp"},
        message=f"DHCP lease {word} ip {ip} --> mac {mac} - hostname {host}, "
        "interface ethernet1/2",
    )  # fmt: skip


def signin(m: float, user: str, device: str, ok: bool = True) -> dict[str, Any]:
    return ev(
        m, "m365_signin", user=user, device=device, ip="203.0.113.10", status_id=1 if ok else 2
    )


def _table(events: list[dict[str, Any]]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"CREATE TABLE events ({COLS})")
    for e in events:
        con.execute(
            f"INSERT INTO events VALUES ({', '.join('?' * len(e))})", list(e.values())
        )  # test table
    return con


def resolve(events: list[dict[str, Any]], ip: str, minutes: float) -> dict[str, Any]:
    con = _table(events)
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


# Owner, 2026-11-17 (D278): the built-in reads "lease ended" lines with the rules of the
# library's who_had_ip. Machines on 10.20.1.6: A (MAC ...a1) and B (MAC ...b1).
A_MAC, B_MAC = "00:00:5e:00:53:a1", "00:00:5e:00:53:b1"


def test_a_lease_that_started_before_the_window_resolves_from_its_end_line() -> None:
    evs = [dhcp(300, "10.20.1.6", "HOST-A", ended=True, mac=A_MAC)]
    r = resolve(evs, "10.20.1.6", 120)
    assert (r["host"], r["host_how"], r["host_capped"]) == ("HOST-A", "dhcp", False)
    assert resolve(evs, "10.20.1.6", 360)["host"] is None  # after its end line


def test_a_lease_ends_at_its_end_line() -> None:
    evs = [dhcp(0, "10.20.1.6", "HOST-A", mac=A_MAC), dhcp(60, "10.20.1.6", "HOST-A", True, A_MAC)]
    assert resolve(evs, "10.20.1.6", 30)["host"] == "HOST-A"
    assert resolve(evs, "10.20.1.6", 150)["host"] is None  # was HOST-A for 24 hours


def test_a_late_end_line_neither_extends_its_lease_nor_ends_the_next() -> None:
    evs = [
        dhcp(0, "10.20.1.6", "HOST-A", mac=A_MAC),
        dhcp(60, "10.20.1.6", "HOST-B", mac=B_MAC),
        dhcp(130, "10.20.1.6", "HOST-A", ended=True, mac=A_MAC),
    ]
    assert resolve(evs, "10.20.1.6", 30)["host"] == "HOST-A"
    late = resolve(evs, "10.20.1.6", 200)  # A's lease ended at B's start
    assert (late["host"], late["host_capped"]) == ("HOST-B", True)


def test_an_empty_hostname_names_no_machine() -> None:
    assert resolve([dhcp(0, "10.20.1.6", "", mac=A_MAC)], "10.20.1.6", 30)["host"] is None


def test_the_library_lookup_reads_dhcp_lines_with_the_same_expressions() -> None:
    """One source for what a DHCP line says: who_had_ip embeds these verbatim."""
    (q,) = [q for p in load_dir(LIBRARY_DIR) for q in p.queries if q.id == "who_had_ip"]
    sql = " ".join(q.sql.split())
    for frag in (DHCP_IP, DHCP_HOST, DHCP_MAC, DHCP_ENDED):
        assert " ".join(frag.split()) in sql


def lookup(events: list[dict[str, Any]], ip: str, minutes: float) -> list[str]:
    """The machines the point lookup (`spans()`) names: it reads the lines 24 h each side."""
    at = T0 + timedelta(minutes=minutes)
    near = [e for e in events if abs(e["time"] - at) <= timedelta(hours=24)]
    rows = _table(near).execute(LOOKUP_SQL, {"ip": ip, "at": at}).fetchall()
    return [r[5] for r in rows if r[0] == "dhcp"]


def test_an_hour_resolves_the_same_whatever_the_range_or_the_lookup() -> None:
    """A 28-hour lease: 2 hours before its end line, it is HOST-A when the range holds its
    start line, when the range starts after it, and in the point lookup."""
    start = dhcp(0, "10.20.1.6", "HOST-A", mac=A_MAC)
    end = dhcp(28 * 60, "10.20.1.6", "HOST-A", ended=True, mac=A_MAC)
    assert resolve([start, end], "10.20.1.6", 26 * 60)["host"] == "HOST-A"
    assert resolve([end], "10.20.1.6", 26 * 60)["host"] == "HOST-A"
    assert lookup([start, end], "10.20.1.6", 26 * 60) == ["HOST-A"]


def test_a_start_and_end_in_the_same_second_hold_it_for_no_time() -> None:
    evs = [dhcp(0, "10.20.1.6", "HOST-A", mac=A_MAC), dhcp(0, "10.20.1.6", "HOST-A", True, A_MAC)]
    assert resolve(evs, "10.20.1.6", 300)["host"] is None  # was HOST-A for 24 hours


def test_a_lease_seen_only_by_its_end_line_reaches_back_to_the_previous_line() -> None:
    evs = [
        dhcp(120, "10.20.1.6", "HOST-B", ended=True, mac=B_MAC),
        dhcp(300, "10.20.1.6", "HOST-A", ended=True, mac=A_MAC),
    ]
    assert resolve(evs, "10.20.1.6", 30)["host"] == "HOST-B"  # not HOST-A: B's end came first
    assert resolve(evs, "10.20.1.6", 200)["host"] == "HOST-A"


def test_a_lease_seen_only_by_its_end_line_reaches_back_at_most_24_hours() -> None:
    evs = [dhcp(30 * 60, "10.20.1.6", "HOST-A", ended=True, mac=A_MAC)]
    assert resolve(evs, "10.20.1.6", 5 * 60)["host"] is None  # 25 hours before
    assert resolve(evs, "10.20.1.6", 7 * 60)["host"] == "HOST-A"  # 23 hours before
