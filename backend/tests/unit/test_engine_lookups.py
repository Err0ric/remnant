"""ip_country, ip_asn, ip_org, and is_internal (ADR-0039 row 4)."""

import ipaddress

import duckdb

from app.engine.guard import guard
from app.engine.lookups import FUNCTIONS, Lookups, register
from app.enrich.networks import is_internal

PLACES = {"198.51.100.7": ("NL", 64500, "Example Net"), "192.0.2.5": ("US", None, None)}


def _con(calls: list[str]) -> duckdb.DuckDBPyConnection:
    def geo(value: str) -> tuple[str | None, int | None, str | None] | None:
        calls.append(value)
        return PLACES.get(value)

    nets = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("203.0.113.0/24")]
    con = duckdb.connect(":memory:")
    register(con, Lookups(geo=geo, internal=lambda: lambda v: is_internal(v, nets)))
    con.execute(
        "CREATE TABLE events AS SELECT * FROM (VALUES ('198.51.100.7'), ('198.51.100.7'),"
        " ('192.0.2.5'), ('10.1.2.3'), ('203.0.113.9'), ('host-17'), (NULL)) t(ip)"
    )
    return con


def test_lookups_answer_from_local_data_and_cache_per_query() -> None:
    calls: list[str] = []
    rows = (
        _con(calls)
        .execute("SELECT ip, ip_country(ip), ip_asn(ip), ip_org(ip), is_internal(ip) FROM events")
        .fetchall()
    )
    assert rows[0] == ("198.51.100.7", "NL", 64500, "Example Net", False)
    assert rows[2] == ("192.0.2.5", "US", None, None, False)
    assert rows[3][4] is True and rows[4][4] is True  # private and a public office range
    assert rows[5] == ("host-17", None, None, None, False)  # not an address
    assert rows[6] == (None, None, None, None, None)
    assert calls.count("198.51.100.7") == 1  # cached for the query


def test_the_guard_allows_them_in_a_where_clause() -> None:
    for name in FUNCTIONS:
        guard(f"SELECT * FROM events WHERE {name}(src_endpoint_ip) IS NOT NULL", ["events"])
    sql = (
        "SELECT * FROM events WHERE NOT is_internal(src_endpoint_ip)"
        " AND ip_country(src_endpoint_ip) = 'NL' AND ip_asn(src_endpoint_ip) = 64500"
    )
    con = _con([])
    assert con.execute(sql.replace("src_endpoint_ip", "ip")).fetchall() == [
        ("198.51.100.7",),
        ("198.51.100.7",),
    ]
