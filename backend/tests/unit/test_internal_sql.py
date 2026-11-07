"""`internal_sql` gives the answer `is_internal` gives, for IPv4 and IPv6 text at the edges
of the ranges and for text that is not an address (owner, 2026-11-07)."""

import duckdb
import pytest

from app.enrich.networks import DEFAULT_INTERNAL, internal_sql, is_internal, parse_network

NETS = [parse_network(n) for n in (*DEFAULT_INTERNAL, "203.0.113.0/25", "2001:db8:10::/48")]
VALUES = [
    # IPv4 at the edges of the ranges
    "10.0.0.0", "10.255.255.255", "11.0.0.0", "9.255.255.255", "172.15.255.255",
    "172.16.0.0", "172.31.255.255", "172.32.0.0", "192.168.0.1", "192.169.0.1",
    "203.0.113.0", "203.0.113.127", "203.0.113.128", "198.51.100.7", "0.0.0.0",
    "255.255.255.255", "127.0.0.1", "169.254.1.1",
    # IPv4 that is not one: leading zeros, out of range, short, spaces, words
    "010.0.0.1", "10.0.0.256", "10.0.0", "10.0.0.1.5", " 10.0.0.1", "10.0.0.1 ",
    "10.0.0.1\n", "", "host-01", "10.0.0.1/8", "1e1.0.0.1",
    # IPv6 at the edges, compressed and full, either case
    "::1", "::2", "::", "fc00::", "fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", "fbff::1",
    "fe00::1", "FE80::1", "fe80:0000:0000:0000:0000:0000:0000:0001", "febf::ffff",
    "fec0::", "2001:db8:10::", "2001:db8:10:ffff:ffff:ffff:ffff:ffff", "2001:db8:11::",
    "2001:DB8:F::FFFF", "2001:0db8:0010:0000:0000:0000:0000:0001", "1:2:3:4:5:6:7::",
    "::2:3:4:5:6:7:8", "fd00:1:2:3:4:5:6:7",
    # IPv6 that is not one, or that only Python reads (zone, IPv4 tail)
    "1:2:3:4:5:6:7:8:9", "1:2:3:4::5:6:7:8", "fd00:::1", "fd00::1::2", "12345::",
    "fe80::1%eth0", "::ffff:10.0.0.1", "::ffff:198.51.100.7", "fd00::g", ":fd00::1",
    "fd00::1:", " ::1",
]  # fmt: skip


@pytest.fixture(scope="module")
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.create_function(
        "is_internal", lambda v: is_internal(v, NETS), ["VARCHAR"], "BOOLEAN", side_effects=False
    )
    return c


def test_sql_answers_as_python(con: duckdb.DuckDBPyConnection) -> None:
    rows = con.execute(
        f"SELECT v, {internal_sql('v', NETS)} FROM (SELECT unnest($v) AS v)", {"v": VALUES}
    ).fetchall()
    got = dict(rows)
    want = {v: is_internal(v, NETS) for v in VALUES}
    assert got == want
    assert sum(want.values()) > 15 and sum(not w for w in want.values()) > 20


def test_plain_addresses_never_reach_python() -> None:
    """Only odd text calls the Python function: here it raises, and plain text still works."""
    c = duckdb.connect()

    def boom(v: str) -> bool:
        raise AssertionError(v)

    c.create_function("is_internal", boom, ["VARCHAR"], "BOOLEAN", side_effects=False)
    plain = [v for v in VALUES[:18] + VALUES[29:48]]
    got = c.execute(
        f"SELECT {internal_sql('v', NETS)} FROM (SELECT unnest($v) AS v)", {"v": plain}
    ).fetchall()
    assert [g[0] for g in got] == [is_internal(v, NETS) for v in plain]


def test_no_networks_is_never_internal(con: duckdb.DuckDBPyConnection) -> None:
    got = con.execute(f"SELECT {internal_sql('v', [])} FROM (SELECT '10.0.0.1' AS v)").fetchone()
    assert got == (False,)
