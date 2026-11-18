"""People & devices speed (owner, 2026-11-17, P6 part 2): each faster read gives the answer
the slower one gave."""

from pathlib import Path

from app.engine.duckdb import QueryScope
from app.search.entities import quote, user_where
from app.search.identity import IdentityMap, key_sql
from tests.integration.test_schedules import make_lab

NAMES = [
    "alice", "ALICE@example.com", "CORP\\Alice", " alice ", "alice@example.org", "jdoe",
    "J.Doe", "malice", "bob", "Bob@Example.com", "userpass-alice", "CORP\\JDOE@example.com",
    "", "j.doe@example.com",
]  # fmt: skip


def test_a_persons_rows_are_found_by_name_before_the_key(tmp_path: Path) -> None:
    """The person graph and summary drop other people's rows with a substring test before
    the key test: the same rows as the key test alone, for every form of a name."""
    engine = make_lab(tmp_path)["app"].state.engine
    ident = IdentityMap(
        domains=["example.com"], aliases={"jdoe": "alice", "userpass-alice": "alice"}
    )
    rows = ", ".join(f"({quote(n)})" for n in NAMES) + ", (NULL)"
    for person in ("alice", "bob", "jdoe", "j.doe", "alice@example.org", "nobody"):
        keys = ident.keys_for(person)
        sql = (
            f"SELECT count(*) FILTER (WHERE {user_where(keys)}),"
            f" count(*) FILTER (WHERE list_contains($keys, {key_sql('actor_user_name')}))"
            f" FROM (VALUES {rows}) t(actor_user_name)"
        )
        fast, plain = engine.run(sql, QueryScope(None), {"keys": keys, **ident.params()}).rows[0]
        assert fast == plain, person
    keys = ident.keys_for("alice")
    sql = f"SELECT count(*) FROM (VALUES {rows}) t(actor_user_name) WHERE {user_where(keys)}"
    assert engine.run(sql, QueryScope(None), {"keys": keys, **ident.params()}).rows[0][0] == 7


def test_an_address_or_hosts_rows_are_read_in_two_arms_each_once(tmp_path: Path) -> None:
    """An address or host page reads its rows as two arms (one per side of the event) so
    each test is pushed into the scan: the same rows as the one OR, none twice."""
    from app.search.entities import WHERE
    from app.search.entity_summary import either_rows

    engine = make_lab(tmp_path)["app"].state.engine  # Windows and Linux sign-ins
    scope = QueryScope(None)
    pairs = engine.run(
        "SELECT DISTINCT src_endpoint_ip, dst_endpoint_ip, device_hostname, src_endpoint_hostname"
        " FROM events",
        scope,
    ).rows
    values = {
        "ip": {v for p in pairs for v in p[:2] if v},
        "host": {v for p in pairs for v in p[2:] if v},
    }
    assert values["ip"] and values["host"]
    for kind, found in values.items():
        for v in sorted(found):
            two = f"SELECT count(*), sum(hash(event_id)) FROM {either_rows(kind)}"
            one = f"SELECT count(*), sum(hash(event_id)) FROM events WHERE {WHERE[kind]}"
            assert engine.run(two, scope, {"v": v}).rows == engine.run(one, scope, {"v": v}).rows, v
