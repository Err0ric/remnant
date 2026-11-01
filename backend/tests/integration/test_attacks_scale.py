"""Attacks and access counts every outside address (it stopped at 5,000 and undercounted a
busy install), in two queries, with the rollup giving the same numbers as events."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from app.core.schema import duckdb_create_table_sql
from app.engine.duckdb import AUTH_ROLLUP_COLUMNS, QueryEngine
from app.enrich.networks import Places
from app.meta.db import MetaDB
from app.search import dashboard
from app.search.m365_rollup import AuthRollup

NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
SOURCES = [("ssh", "file", "linux_sshd")]


def _lake(lake: Path, per_day: int = 7000, days: int = 3) -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    for back in range(days):
        day = (NOW - timedelta(days=back)).date().isoformat()
        out = lake / "source=ssh" / f"day={day}"
        out.mkdir(parents=True)
        con.execute("DELETE FROM e")
        con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, src_endpoint_ip, device_hostname, raw, raw_bytes_invalid,
  parse_status, classification, owner_id)
SELECT '{day}-' || i, 'ssh', 'linux_sshd', '1', TIMESTAMPTZ '{day} 00:00:00+00'
  + to_microseconds((i * 8 * 3600000000 // {per_day})::BIGINT),
  TIMESTAMPTZ '{day} 00:00:00+00' + to_microseconds((i * 8 * 3600000000 // {per_day})::BIGINT),
  3002, 2, CASE WHEN i % 10 = 0 THEN '10.0.0.' || (i % 200) ELSE
  '198.51.' || (i // 250 % 100) || '.' || (i % 250) END, 'srv' || (i % 3), 'x', false, 'ok',
  'local_only', 'system'
FROM range({per_day}) t(i)""")  # test data, fixed text
        con.execute(f"COPY e TO '{out}/part-0.parquet' (FORMAT parquet)")


def _attacks(engine: QueryEngine, meta: MetaDB, rollup: AuthRollup | None) -> dashboard.Attacks:
    places = Places((), ("10.0.0.0/8",), True, None)
    s = dashboard.sections(engine, meta, None, SOURCES, places, lambda ips: {}, "24h", NOW,
                           parts=["attacks"], auth_rollup=rollup)  # fmt: skip
    assert s.attacks is not None
    return s.attacks


def test_every_outside_address_is_counted_from_events_and_rollup(tmp_path: Path) -> None:
    _lake(tmp_path / "lake")
    engine = QueryEngine(tmp_path / "lake")
    meta = MetaDB(tmp_path / "meta.sqlite")
    live = _attacks(engine, meta, None)
    # 7,000 rows a day, one in ten internal; 6,300 outside addresses in the last 24 hours.
    assert live.addresses.value > 5000
    root = tmp_path / "rollup"
    engine.add_rollup("auth_rollup", root, AUTH_ROLLUP_COLUMNS)
    rollup = AuthRollup(engine, tmp_path / "lake", root, sources=lambda: ["ssh"],
                        clock=lambda: NOW, max_days_per_run=10)  # fmt: skip
    rollup.run()
    rollup.refresh_today(max_age_s=0)
    rolled = _attacks(engine, meta, rollup)
    assert (rolled.addresses.value, rolled.failures.value) == (
        live.addresses.value, live.failures.value,
    )  # fmt: skip
    assert rolled.addresses.before == live.addresses.before
