"""The scoped Identities set is computed once and reused for a minute (T70, D219), never
across viewers, grants, or Identities changes, and never for a wider range than the one
it was computed for: a reused set is the same or smaller than a fresh one, so it never
binds an alias the caller's scope does not show."""

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.engine.duckdb import QueryScope
from app.search.identity import IdentityMap, ScopedIdentities

T0 = datetime(2026, 11, 1, tzinfo=UTC)
# Accounts each source shows, as keys (what the scan returns).
SEEN = {"linux": {"alice"}, "claude": {"dana", "dana2"}}


@dataclass
class Res:
    rows: list[list[Any]]


class FakeEngine:
    def __init__(self, delay: float = 0.0) -> None:
        self.calls: list[QueryScope] = []
        self.delay = delay
        self._lock = threading.Lock()

    def run(self, sql: str, scope: QueryScope, params: dict[str, Any], **kw: Any) -> Res:
        with self._lock:
            self.calls.append(scope)
        time.sleep(self.delay)
        sources = SEEN if scope.sources is None else {s: SEEN[s] for s in scope.sources}
        keys = set().union(*sources.values()) if sources else set()
        return Res([["k", k] for k in sorted(keys & set(params["seen_keys"]))])


def _map(**aliases: str) -> IdentityMap:
    return IdentityMap(domains=["example.com"], aliases=dict(aliases))


def _scope(*sources: str, days: int = 7, end: datetime | None = None) -> QueryScope:
    return QueryScope(sources=list(sources), start=T0 - timedelta(days=days), end=end)


def test_reused_for_the_same_viewer_scope_and_map() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana", alice2="alice")
    a = cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    b = cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    assert len(eng.calls) == 1
    assert a.aliases == b.aliases == {"dana2": "dana"}


def test_concurrent_calls_share_one_scan() -> None:
    """The person page asks for summary, risk, and graph at once: one scan, not three."""
    eng, cache = FakeEngine(delay=0.2), ScopedIdentities()
    m = _map(dana2="dana")
    got: list[IdentityMap] = []

    def one() -> None:
        got.append(cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1"))

    threads = [threading.Thread(target=one) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(eng.calls) == 1 and [g.aliases for g in got] == [{"dana2": "dana"}] * 3


def test_never_served_to_another_viewer() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    admin = cache.get(m, eng, _scope("claude", "linux"), ["actor_user_name"], "admin")
    ana = cache.get(m, eng, _scope("linux"), ["actor_user_name"], "ana")
    assert admin.aliases == {"dana2": "dana"} and ana.aliases == {}
    # Even with the very same sources, another viewer gets a scan of their own.
    cache.get(m, eng, _scope("claude", "linux"), ["actor_user_name"], "ana")
    assert len(eng.calls) == 3


def test_a_grant_change_is_a_new_scan() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    before = cache.get(m, eng, _scope("linux", "claude"), ["actor_user_name"], "ana")
    after = cache.get(m, eng, _scope("linux"), ["actor_user_name"], "ana")
    assert before.aliases == {"dana2": "dana"} and after.aliases == {}
    assert len(eng.calls) == 2
    # All sources (an administrator, scope None) is its own entry too.
    every = QueryScope(sources=None, start=T0 - timedelta(days=7))
    assert cache.get(m, eng, every, ["actor_user_name"], "ana").aliases == {"dana2": "dana"}
    assert len(eng.calls) == 3


def test_an_identities_change_is_a_new_scan() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    first = cache.get(_map(dana2="dana"), eng, _scope("claude"), ["actor_user_name"], "u1")
    later = _map(dana2="dana", alice="carol")
    second = cache.get(later, eng, _scope("claude", "linux"), ["actor_user_name"], "u1")
    third = cache.get(later, eng, _scope("claude"), ["actor_user_name"], "u1")
    assert first.aliases == {"dana2": "dana"} and third.aliases == {"dana2": "dana"}
    assert second.aliases == {"dana2": "dana", "alice": "carol"}
    assert len(eng.calls) == 3
    domains = IdentityMap(domains=["example.org"], aliases={"dana2": "dana"})
    cache.get(domains, eng, _scope("claude"), ["actor_user_name"], "u1")
    assert len(eng.calls) == 4


def test_only_a_range_the_request_contains_is_reused() -> None:
    """A set for a range inside the requested one is a subset of the fresh answer (fewer
    events, fewer accounts): reused. A wider, earlier, or later range is not."""
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    cache.get(m, eng, _scope("claude", days=7, end=T0), ["actor_user_name"], "u1")
    for wider in (_scope("claude", days=8, end=T0), _scope("claude", days=7)):
        cache.get(m, eng, wider, ["actor_user_name"], "u1")
    assert len(eng.calls) == 1
    narrower = _scope("claude", days=6, end=T0)
    later = _scope("claude", days=7, end=T0 + timedelta(seconds=1))
    later = QueryScope(later.sources, T0 - timedelta(days=7) + timedelta(seconds=1), later.end)
    for scope in (later, narrower):  # neither holds a kept range
        cache.get(m, eng, scope, ["actor_user_name"], "u1")
    assert len(eng.calls) == 3
    # A set kept for an open range is not used for a bounded one.
    eng2, cache2 = FakeEngine(), ScopedIdentities()
    cache2.get(m, eng2, QueryScope(["claude"]), ["actor_user_name"], "u1")
    cache2.get(m, eng2, _scope("claude", days=7, end=T0), ["actor_user_name"], "u1")
    assert len(eng2.calls) == 2


def test_other_columns_are_their_own_entry() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    cache.get(m, eng, _scope("claude"), ["actor_user_name", "user_name"], "u1")
    assert len(eng.calls) == 2


def test_kept_for_a_minute_only() -> None:
    now = [100.0]
    eng, cache = FakeEngine(), ScopedIdentities(clock=lambda: now[0])
    m = _map(dana2="dana")
    cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    now[0] += 59
    cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    assert len(eng.calls) == 1
    now[0] += 2
    cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    assert len(eng.calls) == 2


def test_an_empty_map_costs_nothing() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    assert (
        cache.get(IdentityMap(), eng, _scope("claude"), ["actor_user_name"], "u1") == IdentityMap()
    )
    assert eng.calls == []


def test_a_caller_cannot_change_what_is_kept() -> None:
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    first = cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    first.aliases["mallory"] = "dana"
    first.domains.append("example.net")
    again = cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1")
    assert again.aliases == {"dana2": "dana"} and again.domains == []


def test_calls_seconds_apart_share_the_scan_of_the_whole_minutes_inside() -> None:
    """The top bar lookup asks for the last 30 days as each key is typed: the start and end
    move by seconds. The scan covers the whole minutes inside the asked range (never more),
    so calls within the same minute reuse it."""
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    for secs in (5, 20, 41):
        end = T0 + timedelta(seconds=secs)
        cache.get(
            m, eng, QueryScope(["claude"], end - timedelta(days=30), end), ["actor_user_name"], "u1"
        )
    assert len(eng.calls) == 1
    (scanned,) = eng.calls
    assert scanned.start == T0 - timedelta(days=30) + timedelta(minutes=1) and scanned.end == T0
    # A range shorter than a whole minute is scanned as asked.
    short = QueryScope(["claude"], T0 + timedelta(seconds=10), T0 + timedelta(seconds=50))
    cache.get(m, eng, short, ["actor_user_name"], "u2")
    assert eng.calls[-1] == short


def test_a_role_change_is_a_new_entry() -> None:
    """D223: the role is part of the key, so a set kept under one role never answers for
    another."""
    eng, cache = FakeEngine(), ScopedIdentities()
    m = _map(dana2="dana")
    cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1", "auditor")
    cache.get(m, eng, _scope("claude"), ["actor_user_name"], "u1", "analyst")
    assert len(eng.calls) == 2


def test_seen_in_keeps_only_what_the_names_show() -> None:
    """A page that holds the caller's rows narrows the map to their names, no scan: an
    alias or domain no name shows stays out, so no row is shown in a domain unseen."""
    m = IdentityMap(
        domains=["example.com", "example.net"], aliases={"dana2": "dana", "erin": "erin2"},
        email_people={"dana"},
    )  # fmt: skip
    got = m.seen_in(["DANA2", "frank@example.net"])
    assert got.domains == ["example.net"] and got.aliases == {"dana2": "dana"}
    assert got.display("frank", True) == "frank@example.net"
    assert IdentityMap(domains=["example.com"]).seen_in(["dana"]).display("dana", False) == "dana"
