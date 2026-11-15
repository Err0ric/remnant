"""Alerts' people on a device, read once per host instead of once per host and record
(findings 2026-11, alerts load): `for_alerts` gives exactly the old answer for every alert,
host, range, shared host, and Identities join, for an administrator's whole map and for a
viewer's part of it."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.ai import host_people as hp
from app.search.identity import IdentityMap

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def old_for_alerts(
    engine: Any, sources: Any, ident: IdentityMap, whole_map: bool, asked: list[hp.Asked]
) -> dict[str, list[hp.DevicePerson]]:
    """The function as it was: every host of every alert matched against every record."""
    asked = [a for a in asked if a.hosts]
    if not asked or sources == []:
        return {}
    start = min(a.start for a in asked)
    end = max(a.end for a in asked)
    seen = hp.hooks_seen(engine, None, (h for a in asked for h in a.hosts), start, end)
    if not seen:
        return {}
    scoped = ident if whole_map else ident.seen_in(s.name for s in seen)
    out: dict[str, list[hp.DevicePerson]] = {}
    for a in asked:
        found = [hp.resolve(seen, scoped, h, a.start, a.end) for h in a.hosts]
        kept = [f for f in found if f is not None]
        if kept:
            out[a.key] = kept
    return out


def seen_rows(n_hosts: int, rng: random.Random) -> list[hp.Seen]:
    names = ["alice", "alice@example.com", "bob@example.com", "carol", "dave@example.com",
             "svc_backup", "erin@example.com"]  # fmt: skip
    out = []
    for h in range(n_hosts):
        host = f"ws-{h:04d}.corp.internal"
        for _ in range(rng.randint(0, 12)):
            at = NOW - timedelta(hours=rng.randint(0, 24 * 40))
            out.append(
                hp.Seen(host, rng.choice(names), at, at + timedelta(minutes=rng.randint(0, 59)))
            )
    rng.shuffle(out)
    return out


def asked_alerts(n: int, n_hosts: int, rng: random.Random) -> list[hp.Asked]:
    out = []
    for k in range(n):
        hosts = [
            f"ws-{rng.randrange(n_hosts):04d}.corp.internal" for _ in range(rng.randint(0, 20))
        ]
        hosts += ["WS-0001.CORP.INTERNAL ", "ws-9999.corp.internal"]  # case, spaces, unseen
        days = rng.choice((1, 7, 30))
        start = NOW - timedelta(days=days, hours=rng.randint(0, 5))
        out.append(hp.Asked(f"item-{k}", hosts, start, NOW - timedelta(hours=rng.randint(0, 3))))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("whole_map", [True, False])
def test_the_answer_is_the_old_one(
    monkeypatch: pytest.MonkeyPatch, seed: int, whole_map: bool
) -> None:
    rng = random.Random(seed)
    seen = seen_rows(150, rng)
    monkeypatch.setattr(hp, "hooks_seen", lambda *a, **k: list(seen))
    ident = IdentityMap(
        domains=["example.com"],
        aliases={"alice": "alice@example.com", "carol": "carol@example.com"},
    )
    asked = asked_alerts(200, 150, rng)
    want = old_for_alerts(None, None, ident, whole_map, asked)
    # Each host is matched against its own records only: the point of the index.
    calls: list[tuple[str, int]] = []
    resolve = hp.resolve

    def own_records(records: Any, scoped: Any, host: str, *rest: Any) -> Any:
        assert {r.host for r in records} <= {host.strip().lower()}
        calls.append((host, len(records)))
        return resolve(records, scoped, host, *rest)

    monkeypatch.setattr(hp, "resolve", own_records)
    got = hp.for_alerts(None, None, ident, whole_map, asked)  # type: ignore[arg-type]  # no lake here
    assert got == want
    assert calls and max(n for _, n in calls) < len(seen)
    # Not vacuous: shared hosts ("possible"), joined names, and alerts naming no one.
    levels = {d.level for ds in got.values() for d in ds}
    assert levels == {"attributed", "possible"}
    assert sum(map(len, got.values())) < sum(len(a.hosts) for a in asked)  # some name no one
    assert any(d.how == "hooks_identities" for ds in got.values() for d in ds)
