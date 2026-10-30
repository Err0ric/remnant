"""Synthetic DNS events written straight into a lake folder, for scale tests (F46).

Shaped like busy BIND query logs read through Loki: half the rows carry the name only in
`unmapped` (the slow host path), every row has a distinct raw line, and one row in 50 is
an AI service. Synthetic only: RFC 1918 test addresses and .example names."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from app.core.schema import duckdb_create_table_sql

AI = (
    "chatgpt.com",
    "api.openai.com",
    "claude.ai",
    "api.anthropic.com",
    "gemini.google.com",
    "copilot.microsoft.com",
    "perplexity.ai",
    "chat.mistral.ai",
)


def write_dns(
    lake: Path,
    per_day: int,
    days: int,
    end: datetime,
    source: str = "dns",
    names: int = 90_000,
    daily_names: bool = False,
) -> int:
    """One Parquet file per day, the last day being `end`'s. Returns the rows written.
    `names` other names in all; with `daily_names`, each day has its own (CDN and
    telemetry hosts with hashed labels, as real resolvers see: F63)."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    ai = "[" + ", ".join(f"'{d}'" for d in AI) + "]"
    pick = f"{ai}[(i // 50) % {len(AI)} + 1]"
    for back in range(days - 1, -1, -1):
        date = (end - timedelta(days=back)).strftime("%Y-%m-%d")
        out = lake / f"source={source}" / f"day={date}"
        out.mkdir(parents=True, exist_ok=True)
        con.execute("DELETE FROM e")
        tag = f"d{back}" if daily_names else ""
        name = f"CASE WHEN i % 50 = 0 THEN {pick} ELSE 'q' || (hash(i * 7) % {names}) || '{tag}.cdn.example.org' END"
        con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, src_endpoint_ip, dst_endpoint_hostname, message, unmapped, raw,
  raw_bytes_invalid, parse_status, classification, owner_id)
SELECT '{date}-' || i, '{source}', 'dns_bind', '1.0.0',
  TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * 86400000000 // {per_day})::BIGINT),
  TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * 86400000000 // {per_day})::BIGINT),
  4003, '10.20.' || (i % 4) || '.' || (i % 250 + 1),
  CASE WHEN i % 2 = 0 THEN NULL ELSE {name} END,
  'query',
  '{{"query":"' || {name} || '","labels":{{"job":"dns","host":"ns1"}},"qtype":"A","rcode":"NOERROR"}}',
  '<30>Oct  9 10:00:00 ns1 named[812]: client @0x7f' || md5(i::VARCHAR) || ' 10.20.'
    || (i % 4) || '.' || (i % 250 + 1) || '#' || (i % 60000) || ': query: ' || {name}
    || ' IN A +E(0)K (10.20.0.53)',
  false, 'ok', 'local_only', 'system'
FROM range({per_day}) t(i)""")  # test data, fixed text
        con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet, COMPRESSION zstd)")
    return per_day * days


def write_identity(
    lake: Path, days: int, end: datetime, hosts: int = 1000, logons_per_day: int = 0
) -> int:
    """What an office adds beside DNS (F63): Palo Alto DHCP leases renewed every hour for
    each DNS client address, and a Microsoft 365 sign-in per machine every 4 hours, so
    the address and sign-in joins run at scale. Synthetic: RFC 1918 addresses, invented
    names. Returns the rows written."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    total = 0
    for back in range(days - 1, -1, -1):
        date = (end - timedelta(days=back)).strftime("%Y-%m-%d")
        for source, sql in (
            (
                "fw_system",
                f"""SELECT '{date}-d' || h || '-' || hr, 'fw_system', 'paloalto_system', '1.0.0',
  TIMESTAMPTZ '{date} 00:00:00+00' + INTERVAL (hr) HOUR + INTERVAL (h % 60) SECOND,
  TIMESTAMPTZ '{date} 00:00:00+00' + INTERVAL (hr) HOUR + INTERVAL (h % 60) SECOND,
  0, NULL, NULL, NULL,
  'DHCP lease started ip 10.20.' || (h % 4) || '.' || (h % 250 + 1) || ' --> mac 00:00:5e:00:'
    || lpad(to_hex(h % 256), 2, '0') || ':0a - hostname WS-' || lpad(h::VARCHAR, 4, '0')
    || ', interface ethernet1/2',
  '{{"subtype":"dhcp"}}'
FROM range({hosts}) a(h), range(24) b(hr)""",
            ),
            (
                "m365",
                f"""SELECT '{date}-s' || h || '-' || hr, 'm365', 'm365_signin', '1.0.0',
  TIMESTAMPTZ '{date} 00:00:00+00' + INTERVAL (hr * 4) HOUR,
  TIMESTAMPTZ '{date} 00:00:00+00' + INTERVAL (hr * 4) HOUR,
  3002, '203.0.113.10', 'WS-' || lpad(h::VARCHAR, 4, '0'), 'user' || h || '@example.com',
  'Claude', '{{}}'
FROM range({hosts}) a(h), range(6) b(hr)""",
            ),
            *(
                [
                    (
                        # Linux sign-ins (sshd, PAM) from the DNS client addresses, as on
                        # the install that found the #276 memory failure.
                        "linux_auth",
                        f"""SELECT '{date}-l' || i, 'linux_auth', 'linux_sshd', '1.0.0',
  TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * 86400000000 // {logons_per_day})::BIGINT),
  TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * 86400000000 // {logons_per_day})::BIGINT),
  3002, '10.20.' || (i % 4) || '.' || (i % 250 + 1), NULL, 'user' || (i % 300),
  'Accepted publickey', '{{}}'
FROM range({logons_per_day}) t(i)""",
                    )
                ]
                if logons_per_day
                else []
            ),
        ):
            out = lake / f"source={source}" / f"day={date}"
            out.mkdir(parents=True, exist_ok=True)
            con.execute("DELETE FROM e")
            con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, src_endpoint_ip, device_hostname, actor_user_name, message, unmapped, raw,
  raw_bytes_invalid, parse_status, classification, owner_id, status_id, activity_id)
SELECT *, 'x', false, 'ok', 'local_only', 'system', 1, 1 FROM ({sql})""")  # test data
            total += con.execute("SELECT count(*) FROM e").fetchone()[0]  # type: ignore[index]  # one row
            con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet, COMPRESSION zstd)")
    return total
