"""Owner 2026-10-31: the top search listed "robin" and her organization email as two
people. Forms with one key merge, with the others listed; names on the same devices that
read as one person are suggested, never merged without an administrator."""

from app.search.identity import IdentityMap
from app.search.lookup import Hit, merge_people
from app.search.timeline import related


def test_forms_of_one_person_are_one_row() -> None:
    ident = IdentityMap(domains=["example.com"], aliases={"robin": "robin.okafor"})
    hits = [
        Hit("user", "robin.okafor@example.com", "robin.okafor@example.com", 40, "2026-10-30"),
        Hit("user", "ROBIN", "ROBIN", 5, "2026-10-31"),
        Hit("user", "CORP\\robin.okafor", "CORP\\robin.okafor", 2, None),
        Hit("user", "sam@example.com", "sam@example.com", 1, None),
        Hit("host", "ws-01", "ws-01", 3, None),
    ]
    out = merge_people(hits, ident)
    users = [h for h in out if h.kind == "user"]
    assert [h.value for h in users] == ["robin.okafor@example.com", "sam@example.com"]
    robin = users[0]
    assert robin.aliases == ["CORP\\robin.okafor", "ROBIN"]
    assert (robin.events, robin.last_seen) == (47, "2026-10-31")
    assert [h.kind for h in out].count("host") == 1


def test_likely_aliases() -> None:
    assert related("robin.okafor", "robin")
    assert related("robin", "robin.okafor@example.com")
    assert related("robin.okafor", "rokafor")
    assert not related("robin.okafor", "emma")
    assert not related("al.x", "al")  # too short to guess


def test_microsoft_service_addresses_are_counted_apart(tmp_path: object) -> None:
    """Owner 2026-10-31: 177 "seen addresses" in 7 days were mostly Exchange's own
    (2603:10b6::/32) on server-side records; those are counted apart."""
    from datetime import UTC, datetime
    from pathlib import Path

    from app.engine.duckdb import QueryEngine, QueryScope
    from app.ingest.normalizer import Normalizer, SourceSpec
    from app.ingest.records import DecodedLine
    from app.ingest.writer import LakeWriter
    from app.search.entity_summary import entity_summary

    now = datetime(2026, 10, 10, tzinfo=UTC)
    rows = []
    for ip in ("198.51.100.5", "198.51.100.6", "2603:10b6:208:1::5", "40.107.1.2"):
        norm = Normalizer(SourceSpec(source_id="m365", format="json"), clock=lambda: now)
        row = norm.normalize(DecodedLine('{"time": "2026-10-09T10:00:00Z"}', False, False))
        assert row is not None
        row["actor_user_name"], row["src_endpoint_ip"] = "dana@example.com", ip
        rows.append(row)
    lake = Path(str(tmp_path)) / "lake"
    LakeWriter(lake).write(rows)
    from app.engine.lookups import Lookups

    engine = QueryEngine(lake)
    engine.set_lookups(Lookups(geo=lambda v: None, internal=lambda: lambda v: False))
    s = entity_summary(engine, QueryScope(None), "user", "dana@example.com")
    assert (s.addresses, s.service_addresses) == (2, 2)
