"""The faster People and devices signals (owner, 2026-11-07) rank exactly as before: the
same users, devices, and addresses, with the same scores, parts, and order, on a lake with
internal and external addresses at the edges of the ranges (IPv4 and IPv6) and text only
Python reads as an address."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from app.core.config import load_config
from app.core.schema import duckdb_create_table_sql
from app.engine.duckdb import QueryScope
from app.enrich import networks
from app.main import create_app
from app.search import entity_signals
from app.search.dashboard import EXTERNAL_FAILURE
from app.search.entities import entity_risk, to_json
from app.search.identity import IdentityMap
from tests.scale_lake import write_people

# The signals query before this change, kept here as the reference.
_a = entity_signals._a
_EMAIL = entity_signals._EMAIL
LEGACY_SEEN_SQL = f"""
WITH e AS (
  SELECT actor_user_name AS u, src_endpoint_ip AS ip, device_hostname AS h,
         class_uid = 3002 AND status_id = 2 AS fail,
         CASE WHEN message ILIKE 'Consent to application%'
              THEN coalesce(metadata_correlation_uid, CAST(event_id AS VARCHAR)) END AS consent,
         coalesce({EXTERNAL_FAILURE}, false) AS attack,
         template_id = 'claude_hooks' AND message = 'claude_hooks.post_tool_use_failure'
           AND {entity_signals.counted(_a("tool_name"))} AS blocked,
         template_id = 'claude_hooks' AND len($org) > 0 AND {_EMAIL} IS NOT NULL
           AND NOT list_contains($org, split_part({_EMAIL}, '@', 2)) AS personal
  FROM events
),
x AS (
  SELECT 'user' AS kind, u AS value, fail, consent, false AS attack, blocked, personal
  FROM e WHERE nullif(u, '') IS NOT NULL
  UNION ALL
  SELECT 'ip', ip, fail, NULL, attack, false, false FROM e WHERE nullif(ip, '') IS NOT NULL
  UNION ALL
  SELECT 'host', h, fail, NULL, attack, blocked, personal FROM e WHERE nullif(h, '') IS NOT NULL
)
SELECT kind, value, count(*) AS events,
       count(*) FILTER (WHERE fail) AS failed,
       count(DISTINCT consent) AS consents,
       count(*) FILTER (WHERE attack) AS attacks,
       count(*) FILTER (WHERE blocked) AS blocked,
       bool_or(personal) AS personal
FROM x GROUP BY 1, 2
QUALIFY row_number() OVER (PARTITION BY kind ORDER BY count(*) DESC, value) <= 1000
"""  # test reference SQL

INTERNAL = ["10.0.0.0/8", "172.16.0.0/12", "203.0.113.0/25", "fc00::/7", "2001:db8:10::/48"]
EDGES = [
    "10.0.0.0", "10.255.255.255", "11.0.0.0", "172.15.255.255", "172.31.255.255",
    "203.0.113.127", "203.0.113.128", "198.51.100.9", "fc00::", "fbff::1",
    "fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", "2001:db8:10:ffff:ffff:ffff:ffff:ffff",
    "2001:db8:11::", "2001:DB8:10::1", "fe80::1%eth0", "::ffff:10.0.0.1", " 10.0.0.1",
    "010.0.0.1", "not-an-address",
]  # fmt: skip
NOW = datetime.now(UTC)


def _edges(lake: Path) -> None:
    """Failed SSH sign-ins from each edge address, a different count each, on two hosts,
    and a consent recorded twice under one correlation id."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    day = NOW.strftime("%Y-%m-%d")
    out = lake / "source=edge" / f"day={day}"
    out.mkdir(parents=True)
    con.execute(
        """
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, activity_id, actor_user_name, src_endpoint_ip, device_hostname,
  message, metadata_correlation_uid, raw, raw_bytes_invalid, parse_status, classification,
  owner_id)
SELECT 'edge-' || k || '-' || i, 'edge', 'linux_sshd', '1.0.0', now(), now(), 3002, 2, 1,
  ['bob', 'carol', 'admin'][i % 3 + 1], $ips[k], ['edge-a.corp.internal', 'edge-b.corp.internal'][i % 2 + 1],
  'Failed password', NULL, 'x', false, 'ok', 'local_only', 'system'
FROM range(1, len($ips) + 1) a(k), range(0, 40) b(i) WHERE i < k * 2
UNION ALL
SELECT 'consent-' || i, 'edge', 'm365_management_activity', '1.0.0', now(), now(), 3001, 1,
  1, 'erin@example.com', '203.0.113.200', NULL, 'Consent to application.', 'corr-1', 'x',
  false, 'ok', 'local_only', 'system'
FROM range(2) t(i)""",  # test data
        {"ips": EDGES},
    )
    con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet)")


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp = tmp_path_factory.mktemp("same")
    config = load_config(Path("missing.yaml"), {"APP__PATHS__DATA_DIR": str(tmp / "data")})
    app = create_app(config)
    lake = app.state.engine._lake
    write_people(lake, days=3, end=NOW, per_day=500)
    _edges(lake)
    networks.save(app.state.meta, [], INTERNAL, "admin")
    return app


def _ranked(app: Any) -> dict[str, Any]:
    scope = QueryScope(None, NOW - timedelta(days=4), NOW + timedelta(hours=1))
    ranked, n, read, spl = entity_risk(
        app.state.engine, app.state.meta, None, scope,
        IdentityMap(domains=["example.com"]), app.state.ai_usage,
    )  # fmt: skip
    return {
        "ranked": {k: [to_json(r) for r in rs] for k, rs in ranked.items()},
        "n": n,
        "read": sorted(read),
        "targeted": [to_json(t) for t in spl.rows],
    }


def test_new_signals_rank_as_the_old(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    new = _ranked(app)
    monkeypatch.setattr(entity_signals, "seen_sql", lambda internal: LEGACY_SEEN_SQL)
    old = _ranked(app)
    assert new == old
    ips = {r["value"]: r for r in new["ranked"]["ip"]}
    # External edges counted as attacks, internal ones not; the odd text took Python's word.
    assert ips["11.0.0.0"]["attacks"] > 0 and ips["203.0.113.128"]["attacks"] > 0
    assert ips["2001:db8:11::"]["attacks"] > 0 and ips["fbff::1"]["attacks"] > 0
    assert ips["010.0.0.1"]["attacks"] > 0 and ips["not-an-address"]["attacks"] > 0
    for inside in ("10.255.255.255", "203.0.113.127", "2001:DB8:10::1", "fc00::"):
        assert ips[inside]["attacks"] == 0, inside
    # Not in the list saved above; a mapped IPv4 address is IPv6 to `ipaddress`.
    assert ips["fe80::1%eth0"]["attacks"] > 0 and ips["::ffff:10.0.0.1"]["attacks"] > 0
    users = {r["value"]: r for r in new["ranked"]["user"]}
    assert users["erin@example.com"]["consents"] == 1
    assert any(h["attacks"] for h in new["ranked"]["host"])
