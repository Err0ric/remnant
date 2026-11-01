"""D135: the Dashboard's Attacks and access section reads closed days from the auth rollup
and today from events, with the same numbers events give."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.engine.duckdb import QueryScope
from app.enrich.networks import Places
from app.search.dashboard import sections
from app.search.entities import to_json
from app.search.m365_rollup import AuthRollup
from tests.integration.test_schedules import make_lab
from tests.scale_lake import write_identity


def test_attacks_from_the_rollup_match_events(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    app = lab["app"]
    engine = app.state.engine
    now = datetime.now(UTC)
    write_identity(engine._lake, days=20, end=now, hosts=40, logons_per_day=300)
    # A few failures from outside, so the section has something to show.
    import duckdb

    from app.core.schema import duckdb_create_table_sql

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    for back in range(20):
        day = (now - timedelta(days=back)).strftime("%Y-%m-%d")
        out = engine._lake / "source=sshd" / f"day={day}"
        out.mkdir(parents=True, exist_ok=True)
        con.execute("DELETE FROM e")
        con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, src_endpoint_ip, device_hostname, actor_user_name, message, raw,
  raw_bytes_invalid, parse_status, classification, owner_id)
SELECT '{day}-' || i, 'sshd', 'linux_sshd', '1.0.0',
  TIMESTAMPTZ '{day} 00:00:00+00' + INTERVAL (i * 7) MINUTE,
  TIMESTAMPTZ '{day} 00:00:00+00' + INTERVAL (i * 7) MINUTE,
  3002, 2, '203.0.113.' || (i % 9), 'bastion-' || (i % 3), 'root', 'Failed password', 'x',
  false, 'ok', 'local_only', 'system'
FROM range(150) t(i)""")  # test data
        con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet)")
    root = tmp_path / "rollup-auth"
    from app.engine.duckdb import AUTH_ROLLUP_COLUMNS

    engine.add_rollup("auth_rollup", root, AUTH_ROLLUP_COLUMNS)
    srcs = [("sshd", "file", "linux_sshd"), ("linux_auth", "file", "linux_sshd")]
    rollup = AuthRollup(
        engine, engine._lake, root, lambda: [s for s, _, _ in srcs], max_days_per_run=500
    )
    assert rollup.run().built > 0
    places = Places((), (), False, None)
    meta = app.state.meta

    def geo(ips: list[str]) -> dict[str, object]:
        return {}

    for window in ("24h", "7d", "30d"):
        live = sections(engine, meta, None, srcs, places, geo, window, now, parts=("attacks",))
        rolled = sections(
            engine, meta, None, srcs, places, geo, window, now, parts=("attacks",),
            auth_rollup=rollup,
        )  # fmt: skip
        assert live.attacks is not None
        assert to_json(rolled.attacks) == to_json(live.attacks), window
    # Today so far from the rollup, later rows from events: still the same numbers.
    assert rollup.refresh_today() > 0
    assert rollup.refresh_today() == 0  # not again within 5 minutes
    part = rollup.today(QueryScope(None, now - timedelta(days=1), now))
    assert part is not None and "sshd" in part[1]
    for window in ("24h", "7d"):
        live = sections(engine, meta, None, srcs, places, geo, window, now, parts=("attacks",))
        rolled = sections(
            engine, meta, None, srcs, places, geo, window, now, parts=("attacks",),
            auth_rollup=rollup,
        )  # fmt: skip
        assert to_json(rolled.attacks) == to_json(live.attacks), f"{window} with today"
