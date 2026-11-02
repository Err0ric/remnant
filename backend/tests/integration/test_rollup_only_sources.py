"""Regression (owner, 2026-11-01): a source whose whole range is served from rollup days,
with no live files in range (nothing today), still counts. Template narrowing used to
drop such a source from the query, so its rollup rows were left out and the Dashboard,
Microsoft 365 Overview, and Attacks and access undercounted. Each page must give the same
numbers from the rollups as from events. Synthetic data."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from app.core.schema import duckdb_create_table_sql
from app.engine.duckdb import AUTH_ROLLUP_COLUMNS
from app.enrich.networks import Places
from app.ingest.writer import LakeWriter
from app.search.dashboard import sections
from app.search.entities import to_json
from app.search.m365 import overview, to_dict
from app.search.m365_rollup import AuthRollup
from tests.integration import test_m365_rollup as m365
from tests.integration.test_schedules import make_lab


def _no_today(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Every row before today, so the range's only files are closed, rolled-up days."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return [r for r in rows if (r["time"] or r["time_observed"]) < start]


def test_m365_overview_and_dashboard_identity_count_rollup_only_sources(tmp_path: Path) -> None:
    engine, rollup = m365._lab(tmp_path)
    now = m365.NOW
    LakeWriter(engine._lake).write(_no_today(m365._rows(40), now))
    assert rollup.run().built > 0
    for window in ("7d", "30d"):
        live = overview(engine, None, m365.SOURCES, m365.PLACES, window, now)
        rolled = overview(engine, None, m365.SOURCES, m365.PLACES, window, now, rollup)
        assert to_dict(rolled) == to_dict(live), window
        assert live.sign_ins is not None and live.sign_ins.value > 0
    meta = make_lab(tmp_path / "meta")["app"].state.meta

    def geo(ips: list[str]) -> dict[str, object]:
        return {}

    for window in ("7d", "30d"):
        args = (engine, meta, None, m365.SOURCES, m365.PLACES, geo, window, now)
        live_s = sections(*args, parts=("identity",))
        rolled_s = sections(*args, m365_rollup=rollup, parts=("identity",))
        assert live_s.identity is not None
        assert to_json(rolled_s.identity) == to_json(live_s.identity), window


def test_attacks_and_access_counts_a_rollup_only_source(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine = lab["app"].state.engine
    now = datetime.now(UTC)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    for back in range(1, 20):  # closed days only: nothing today
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
    engine.add_rollup("auth_rollup", root, AUTH_ROLLUP_COLUMNS)
    srcs = [("sshd", "file", "linux_sshd")]
    rollup = AuthRollup(engine, engine._lake, root, lambda: ["sshd"], max_days_per_run=500)
    assert rollup.run().built > 0
    meta = lab["app"].state.meta

    def geo(ips: list[str]) -> dict[str, object]:
        return {}

    places = Places((), (), False, None)
    for window in ("7d", "30d"):
        args = (engine, meta, None, srcs, places, geo, window, now)
        live = sections(*args, parts=("attacks",))
        rolled = sections(*args, parts=("attacks",), auth_rollup=rollup)
        assert live.attacks is not None
        assert to_json(rolled.attacks) == to_json(live.attacks), window
