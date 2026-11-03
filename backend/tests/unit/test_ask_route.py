"""ADR-0042 slice 1b: routing in code, before any model. Time phrases, entities, library
ranking, and the SQL that runs with the question's filters as bound parameters."""

from datetime import UTC, datetime

import pytest

from app.engine.guard import guard
from app.search.ask_route import Entity, find_entities, parse_time, plan, rank, words
from app.search.identity import IdentityMap
from app.search.library import LIBRARY_DIR, Library, load_dir
from app.search.params import compile_sql

# A Wednesday, 15:30 UTC.
NOW = datetime(2026, 11, 4, 15, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "label", "start", "end"),
    [
        ("failed logins today", "today", "2026-11-04T00:00", "2026-11-04T15:30"),
        ("what happened yesterday", "yesterday", "2026-11-03T00:00", "2026-11-04T00:00"),
        ("in the last 6 hours", "the last 6 hours", "2026-11-04T09:30", "2026-11-04T15:30"),
        ("past 24 hours", "the last 24 hours", "2026-11-03T15:30", "2026-11-04T15:30"),
        ("anything this week", "this week", "2026-11-02T00:00", "2026-11-04T15:30"),
        ("last week", "last week", "2026-10-26T00:00", "2026-11-02T00:00"),
        ("since Monday", "since Monday", "2026-11-02T00:00", "2026-11-04T15:30"),
        ("last 3 days", "the last 3 days", "2026-11-01T15:30", "2026-11-04T15:30"),
    ],
)
def test_time_phrases(text: str, label: str, start: str, end: str) -> None:
    span = parse_time(text, NOW)
    assert span is not None and span.label == label
    assert span.start.strftime("%Y-%m-%dT%H:%M") == start
    assert span.end.strftime("%Y-%m-%dT%H:%M") == end


def test_today_is_the_askers_day() -> None:
    # 15:30 UTC is 07:30 in Los Angeles: "today" starts at local midnight (08:00 UTC).
    span = parse_time("today", NOW, "America/Los_Angeles")
    assert span is not None and span.start.astimezone(UTC).hour == 8
    assert parse_time("failed logins by source", NOW) is None
    assert parse_time("today", NOW, "Not/AZone") is not None  # unknown zone: UTC


def test_entities_in_a_question() -> None:
    q = r"did dana@example.com or CORP\erin log in to ws-0042 from 203.0.113.9 or 2001:db8::7?"
    got = find_entities(q)
    assert got == [
        Entity("user", "dana@example.com"),
        Entity("user", r"CORP\erin"),
        Entity("host", "ws-0042"),
        Entity("ip", "203.0.113.9"),
        Entity("ip", "2001:db8::7"),
    ]
    assert find_entities("anything weird with frank this week", {"frank"}) == [
        Entity("user", "frank")
    ]
    assert find_entities("failed logins by source address") == []  # plain words


def test_library_ranking_offers_only_what_the_viewer_has() -> None:
    lib = Library(load_dir(LIBRARY_DIR))
    top = rank("which addresses had the most failed SSH logins today?", lib, {"linux_sshd"})
    assert top and top[0].ref == "linux_auth/ssh_failures_by_source"
    assert all(c.pack.id == "linux_auth" or not c.query.requires for c in top)
    assert rank("who is using copilot", lib, {"linux_sshd"}) == []  # no Microsoft 365 data
    m365 = rank("who is using copilot", lib, {"m365_management_activity"})
    assert m365[0].ref == "m365/m365_copilot_activity"
    assert words("Failed logons") == {"failure", "signin"}


def test_every_library_query_has_example_questions() -> None:
    for pack in load_dir(LIBRARY_DIR):
        for q in pack.queries:
            assert 2 <= len(q.ask) <= 5, f"{pack.id}/{q.id} needs 2 to 5 ask phrasings"


def test_a_plan_filters_on_the_named_entities_with_bound_values() -> None:
    lib = Library(load_dir(LIBRARY_DIR))
    found = lib.find("linux_auth", "ssh_logins")
    assert found is not None
    _, q = found
    ident = IdentityMap(domains=["example.com"], aliases={"dana.k": "dana"})
    entities = [
        Entity("user", "dana@example.com"),
        Entity("ip", "203.0.113.9"),
        Entity("host", "ws-1"),
    ]
    p = plan(q, ["user", "client", "result", "attempts"], entities, {}, ident)
    assert p.filters == ["user = dana@example.com (also dana, dana.k)", "client = 203.0.113.9"]
    assert p.unused == [Entity("host", "ws-1")]  # the query has no host column: said, not hidden
    assert "dana" not in p.sql and "203.0.113.9" not in p.sql  # values are parameters
    assert sorted(v for k, v in p.params.items() if k.startswith("ask_user")) == ["dana", "dana.k"]
    assert p.params["ask_ip_1"] == "203.0.113.9"
    guard(compile_sql(p.sql), ["events"])  # the guard accepts the wrapped SQL
