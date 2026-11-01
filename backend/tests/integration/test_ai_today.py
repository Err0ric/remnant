"""D136: AI pages read today so far from the AI rollup (rows observed by a cutoff) and
later rows from events, with the same results, including people found only through
DNS and DHCP (ADR-0029)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.engine.duckdb import QueryScope
from tests.integration.test_schedules import make_lab
from tests.scale_lake import write_dns, write_identity


def _services(usage, scope: QueryScope) -> dict[str, tuple[int, tuple[str, ...]]]:  # type: ignore[no-untyped-def]  # test helper
    found, _ = usage.all_services(scope)
    return {u.service.id: (u.events, tuple(sorted(u.top_people))) for u in found}


def test_today_so_far_matches_events(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    app = lab["app"]
    engine = app.state.engine
    now = datetime.now(UTC)
    lake = engine._lake
    # DNS from client addresses with no user, and DHCP leases plus sign-ins that name the
    # machine and person behind each address: AI use reaches people only through them.
    write_dns(lake, per_day=3_000, days=3, end=now)
    write_identity(lake, days=3, end=now, hosts=50)
    # Today's files as a running install has them: nothing observed after now.
    import duckdb

    day = now.strftime("%Y-%m-%d")
    con = duckdb.connect()
    for f in lake.glob(f"source=*/day={day}/*.parquet"):
        tmp = f.with_suffix(".tmp")
        con.execute(
            f"COPY (SELECT * FROM read_parquet('{f}') WHERE time_observed <= TIMESTAMPTZ"
            f" '{now.isoformat()}') TO '{tmp}' (FORMAT parquet)"
        )
        tmp.replace(f)
    usage = app.state.ai_usage
    rollup = app.state.ai_rollup
    rollup._clock = lambda: now
    # On the hour, as page windows start: hourly facts split exactly there.
    scope = QueryScope(
        None, (now - timedelta(hours=20)).replace(minute=0, second=0, microsecond=0), now
    )
    live = _services(usage, scope)
    odd = QueryScope(None, scope.start + timedelta(minutes=17), now)
    live_odd = _services(usage, odd)
    assert live and any(people for _, people in live.values()), "people through DHCP"
    assert rollup.refresh_today() > 0
    assert rollup.today(scope) is not None
    rolled = _services(usage, scope)
    assert rolled == live
    # A start inside an hour of today reads today from events, and still agrees.
    if odd.start is not None and odd.start.date() == now.date():
        assert rollup.today(odd) is None
    assert _services(usage, odd) == live_odd
    # The person timeline finds the same first AI use through the build.
    person = next(p for _, people in live.values() for p in people)
    t = lab["admin"].get(f"/api/people/{person}/timeline", params={"days": 1}).json()
    assert any(r["kind"] == "ai_first" for r in t["rows"])


def test_prefilter_keeps_every_form_of_a_name(tmp_path: Path) -> None:
    """The substring test before normalizing never drops a form the key matches."""
    import duckdb

    from app.search.identity import IdentityMap
    from app.search.timeline import _mine

    ident = IdentityMap(domains=["example.com"])
    keys = ident.keys_for("robin.okafor")
    names = ["robin.okafor", "ROBIN.OKAFOR@example.com", "CORP\\Robin.Okafor", " robin.okafor ",
             "robin.okafor@other.example", "robin", "okafor", None]  # fmt: skip
    con = duckdb.connect()
    con.execute("CREATE TABLE events (actor_user_name VARCHAR)")
    con.executemany("INSERT INTO events VALUES (?)", [(n,) for n in names])
    got = {
        r[0]
        for r in con.execute(
            f"SELECT actor_user_name FROM events WHERE {_mine(ident, keys)}"
        ).fetchall()
    }
    full = _mine(ident, keys).split(" AND ", 1)[1][:-1]
    want = {
        r[0] for r in con.execute(f"SELECT actor_user_name FROM events WHERE {full}").fetchall()
    }
    assert got == want and "CORP\\Robin.Okafor" in got and "robin" not in got
