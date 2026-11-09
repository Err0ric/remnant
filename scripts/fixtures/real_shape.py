"""A real-shaped week for People and devices (owner item 2, 2026-11-08), written straight
into a lake folder as Parquet: Windows domain controller sign-ins and Windows DNS queries
in the proportions of a busy office (about 1.9 million sign-ins and 5.7 million DNS
queries over 7 days at `--scale 1`), with many distinct people, machine accounts, hosts,
addresses, and names, plus a few Claude Code hook events.

    cd backend && uv run python ../scripts/fixtures/real_shape.py --lake <lake> --scale 1

Sign-ins (NXLog records of about 1.5 KB): 400 people (bare names and user@example.com
forms), 3,000 machine accounts (WS-0001$), logons and log offs on two domain controllers
and the workstations, 4% failed (a spray of nobody's names from outside among them).
DNS: 3,500 clients asking two servers for 20,000 names (a third with a daily hashed
label, as CDNs use), queries and responses. Synthetic only: RFC 1918 and documentation
addresses, .internal hosts, example.com/.org/.net and .test names. Deterministic. Prints
the rows written. Writes about 2.7 GB at `--scale 1`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from app.core.schema import duckdb_create_table_sql

AUTH_PER_DAY, DNS_PER_DAY = 271_500, 814_500
PEOPLE, MACHINES, CLIENTS, NAMES = 400, 3000, 3500, 20_000
SPRAY = "['root','admin','ubuntu','oracle','test','guest','backup','scanner','ftp','sql']"
AT = "TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * {span} // {n})::BIGINT)"
COLUMNS = """event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, activity_id, status_id, severity_id, actor_user_name, src_endpoint_ip,
  src_endpoint_hostname, dst_endpoint_ip, device_hostname, message, unmapped, raw,
  raw_bytes_invalid, parse_status, classification, owner_id"""

# Per row i of a day: r is a stable pseudo-random number, so busy people stay busy.
AUTH = """
SELECT '{date}-a' || i, 'win_auth', 'windows_nxlog_json', '1.0.0', {t}, {t}, 3002,
  CASE WHEN r % 10 < 3 THEN 2 ELSE 1 END,
  CASE WHEN r % 100 < 4 THEN 2 ELSE 1 END, 1,
  CASE WHEN r % 100 < 1 THEN {spray}[r % 10 + 1]
       WHEN r % 10 < 4 THEN 'WS-' || lpad((r % {machines})::VARCHAR, 4, '0') || '$'
       WHEN r % 2 = 0 THEN 'user' || lpad(((r // 7) % {people})::VARCHAR, 4, '0')
       ELSE 'user' || lpad(((r // 7) % {people})::VARCHAR, 4, '0') || '@example.com' END,
  CASE WHEN r % 100 < 1 THEN '203.0.113.' || (r % 254 + 1)
       ELSE '10.30.' || ((r // 3) % {clients} // 250) || '.' || ((r // 3) % 250 + 1) END,
  'ws-' || lpad(((r // 3) % {machines})::VARCHAR, 4, '0') || '.corp.internal',
  NULL,
  CASE WHEN r % 5 = 0 THEN 'ws-' || lpad(((r // 3) % {machines})::VARCHAR, 4, '0')
         || '.corp.internal' ELSE 'dc0' || (r % 2 + 1) || '.corp.internal' END,
  CASE WHEN r % 100 < 4 THEN 'An account failed to log on.'
       WHEN r % 10 < 3 THEN 'An account was logged off.'
       ELSE 'An account was successfully logged on.' END,
  '{{"EventID":' || CASE WHEN r % 100 < 4 THEN 4625 WHEN r % 10 < 3 THEN 4634 ELSE 4624 END
    || ',"LogonType":' || (r % 3 + 2) || ',' || {extra} || '}}',
  '{{"EventTime":"{date}","Hostname":"dc01.corp.internal","EventID":4624,"Record":'
    || i || ',' || {extra} || '}}',
  false, 'ok', 'local_only', 'system'
FROM (SELECT i, (hash(i, '{date}') % 1000000007)::BIGINT AS r FROM range({n}) t(i))"""

DNS = """
SELECT '{date}-d' || i, 'win_dns', 'dns_windows', '1.0.0', {t}, {t}, 4003,
  CASE WHEN i % 2 = 0 THEN 1 ELSE 2 END,
  CASE WHEN i % 2 = 0 THEN NULL WHEN r % 50 = 0 THEN 2 ELSE 1 END, 1, NULL,
  CASE WHEN i % 2 = 0 THEN {client} END, NULL,
  CASE WHEN i % 2 = 1 THEN {client} END,
  'dns0' || (r % 2 + 1) || '.corp.internal',
  {name}, NULL,
  '{date} 10:00:00 0E5C PACKET  000001D3' || substr(md5(i::VARCHAR), 1, 8)
    || ' UDP ' || CASE WHEN i % 2 = 0 THEN 'Rcv' ELSE 'Snd' END || ' ' || {client}
    || ' ' || substr(md5(r::VARCHAR), 1, 4) || ' Q [0001   D   NOERROR] A      ' || {name},
  false, 'ok', 'local_only', 'system'
FROM (SELECT i, (hash(i // 2, '{date}') % 1000000007)::BIGINT AS r FROM range({n}) t(i))"""

HOOKS = """
SELECT '{date}-h' || i, 'hooks', 'claude_hooks', '1.0.0', {t}, {t}, 6003, 1, 1, 1,
  'user' || lpad((i % 40)::VARCHAR, 4, '0') || '@example.com', NULL, NULL, NULL,
  'ws-' || lpad((i % 40)::VARCHAR, 4, '0') || '.corp.internal',
  CASE WHEN i % 30 = 0 THEN 'claude_hooks.post_tool_use_failure'
       ELSE 'claude_hooks.pre_tool_use' END,
  '{{"attr":{{"tool_name":"Bash","claude_account_email":"user'
    || lpad((i % 40)::VARCHAR, 4, '0') || '@example.com"}}}}',
  'hook ' || i, false, 'ok', 'local_only', 'system'
FROM range({n}) t(i)"""


def write(lake: Path, scale: float = 1.0, days: int = 7, end: datetime | None = None) -> int:
    """One Parquet file per source and day, the last day being `end`'s (now by default)."""
    end = end or datetime.now(UTC)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    client = f"'10.30.' || ((r // 3) % {CLIENTS} // 250) || '.' || ((r // 3) % 250 + 1)"
    # Most queries go to a few thousand names; a third carry a daily hashed label.
    name = (
        "CASE WHEN r % 3 = 0 THEN 'x' || substr(md5((r % 997)::VARCHAR || '{date}'), 1, 10)"
        " || '.cdn.example.net' WHEN r % 7 = 0 THEN 'host' || (r % 500) || '.corp.test'"
        f" ELSE 'app' || ((r // 11) % {NAMES}) || '.example.org' END"
    )
    # The rest of an NXLog record (about 1.5 KB: every field it sends stays in unmapped).
    extra = " || ',' || ".join(
        f"'\"F{k}\":\"' || md5(i::VARCHAR || '{k}') || '\"'" for k in range(36)
    )
    plan = (
        ("win_auth", AUTH, int(AUTH_PER_DAY * scale)),
        ("win_dns", DNS, int(DNS_PER_DAY * scale)),
        ("hooks", HOOKS, 300),
    )
    total = 0
    for back in range(days - 1, -1, -1):
        date = (end - timedelta(days=back)).strftime("%Y-%m-%d")
        # Rows up to `end`, never ahead of it: today's are spread over today so far.
        midnight = datetime.fromisoformat(date).replace(tzinfo=UTC)
        span = int(min(86400.0, (end - midnight).total_seconds() - 1) * 1_000_000)
        for source, sql, n in plan:
            out = lake / f"source={source}" / f"day={date}"
            out.mkdir(parents=True, exist_ok=True)
            con.execute("DELETE FROM e")
            body = sql.format(
                date=date, n=n, t=AT.format(date=date, n=n, span=span), spray=SPRAY, people=PEOPLE,
                machines=MACHINES, clients=CLIENTS, client=client,
                name=name.format(date=date), extra=extra,
            )  # fmt: skip
            con.execute(f"INSERT INTO e ({COLUMNS}) {body}")  # synthetic data, fixed text
            total += n
            con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet, COMPRESSION zstd)")
    return total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lake", type=Path, required=True, help="lake folder to write into")
    ap.add_argument("--scale", type=float, default=1.0, help="1 = about 7.6 million rows")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args(argv)
    print(write(args.lake, args.scale, args.days))
    return 0


if __name__ == "__main__":
    sys.exit(main())
