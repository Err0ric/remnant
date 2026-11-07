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


# Conditional Access results as Graph writes them in each sign-in: most of a real record's
# length, which every read of `raw` has to parse.
_POLICIES = ",".join(
    f'{{"id":"0a1b2c3d-0000-4000-8000-0000000{n:05d}","displayName":"Lab policy {n}",'
    '"enforcedGrantControls":["Mfa"],"enforcedSessionControls":[],"result":"notApplied"}'
    for n in range(12)
)


def write_m365(
    lake: Path,
    signins_per_day: int,
    activity_per_day: int,
    days: int,
    end: datetime,
    source: str = "m365",
) -> int:
    """Microsoft 365 in one source, as the owner's install has it (ADR-0041): Graph
    sign-ins with full-size records (about 3 KB each: errorCode and failureReason are read
    from `raw`), Management Activity operations, and a few directory changes and consents
    a day. Synthetic: RFC 5737 addresses, example.com people. Returns the rows written."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    ops = "['FileDownloaded','FileAccessed','CopilotInteraction','DLPRuleMatch','New-InboxRule','AnonymousLinkCreated','MailItemsAccessed','FileModified']"
    total = 0
    for back in range(days - 1, -1, -1):
        date = (end - timedelta(days=back)).strftime("%Y-%m-%d")
        out = lake / f"source={source}" / f"day={date}"
        out.mkdir(parents=True, exist_ok=True)
        con.execute("DELETE FROM e")
        at = f"TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * 86400000000 // {{n}})::BIGINT)"
        code = "CASE i % 20 WHEN 0 THEN 50126 WHEN 1 THEN 50074 WHEN 2 THEN 50140 WHEN 3 THEN 50053 ELSE 0 END"
        con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, severity_id, actor_user_name, resource_name, message,
  src_endpoint_ip, status_detail, raw, raw_bytes_invalid, parse_status, classification,
  owner_id)
SELECT '{date}-s' || i, '{source}', 'm365_signin', '1.1.0', {at.format(n=signins_per_day)},
  {at.format(n=signins_per_day)}, 3002,
  CASE WHEN {code} = 0 THEN 1 ELSE 2 END, CASE WHEN i % 97 = 0 THEN 3 ELSE 1 END,
  'user' || (i % 300) || '@example.com', ['Outlook','Teams','SharePoint','OneDrive'][i % 4 + 1],
  ['Outlook','Teams','SharePoint','OneDrive'][i % 4 + 1],
  -- each person signs in from their office address, and one in 7 also from home
  CASE WHEN i % 7 = 0 THEN '198.51.100.' ELSE '203.0.113.' END || (i % 300 % 250),
  NULL,
  '{{"id":"' || md5(i::VARCHAR || '{date}') || '","createdDateTime":"{date}T00:00:00Z",'
    || '"userPrincipalName":"user' || (i % 300) || '@example.com","appDisplayName":"Outlook",'
    || '"ipAddress":"203.0.113.' || (i % 300 % 250) || '","status":{{"errorCode":' || {code}
    || ',"failureReason":"' || CASE WHEN {code} = 0 THEN 'Other.' ELSE 'Lab reason ' || {code} END
    || '"}},"deviceDetail":{{"deviceId":"' || md5(i::VARCHAR) || '","operatingSystem":"Windows10"}},'
    || '"appliedConditionalAccessPolicies":[{_POLICIES}]}}',
  false, 'ok', 'local_only', 'system'
FROM range({signins_per_day}) t(i)""")  # test data
        con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, actor_user_name, message, src_endpoint_ip, metadata_correlation_uid,
  raw, raw_bytes_invalid, parse_status, classification, owner_id)
SELECT '{date}-a' || i, '{source}', 'm365_management_activity', '1.0.0',
  {at.format(n=activity_per_day)}, {at.format(n=activity_per_day)}, 6001, 1,
  'user' || (i % 300) || '@example.com', {ops}[i % 8 + 1], '203.0.113.' || (i % 250),
  md5(i::VARCHAR || '{date}a'),
  '{{"Id":"' || md5(i::VARCHAR || '{date}a') || '","Operation":"' || {ops}[i % 8 + 1]
    || '","Workload":"SharePoint","UserId":"user' || (i % 300) || '@example.com"}}',
  false, 'ok', 'local_only', 'system'
FROM range({activity_per_day}) t(i)""")  # test data
        # A role grant and a consent a day, from both feeds (one correlation id each).
        con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, actor_user_name, message, metadata_correlation_uid, raw,
  raw_bytes_invalid, parse_status, classification, owner_id)
SELECT '{date}-c' || i || f, '{source}',
  CASE WHEN f = 0 THEN 'm365_directory_audit' ELSE 'm365_management_activity' END, '1.0.0',
  TIMESTAMPTZ '{date} 09:00:00+00' + INTERVAL (i) MINUTE + INTERVAL (f) SECOND,
  TIMESTAMPTZ '{date} 09:00:00+00' + INTERVAL (i) MINUTE + INTERVAL (f) SECOND, 3001, 1,
  'admin@example.com', CASE WHEN i = 0 THEN 'Add member to role' ELSE 'Consent to application' END,
  '{date}-corr-' || i, '{{}}', false, 'ok', 'local_only', 'system'
FROM range(2) a(i), range(2) b(f)""")  # test data
        total += con.execute("SELECT count(*) FROM e").fetchone()[0]  # type: ignore[index]  # one row
        con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet, COMPRESSION zstd)")
    return total


# Brute-force names a password spray tries (nobody's accounts), and a few IPv6 attackers.
_SPRAY = "['root','admin','ubuntu','oracle','test','minecraft','postgres','git','ftp','guest']"


def write_people(lake: Path, days: int, end: datetime, per_day: int = 100_000) -> int:
    """What People and devices reads on a small office (owner, 2026-11-07): firewall
    traffic as busy as the DNS beside it (a third of it probes from many outside IPv6
    addresses, as an exposed firewall sees), Linux sign-ins on 40 servers with a password
    spray from outside (IPv4 and IPv6), Windows logons for 300 people on their
    workstations, and Claude Code hook events. Synthetic: RFC 1918 and documentation
    addresses, .internal hosts, example.com people. Returns the rows written."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(duckdb_create_table_sql("e"))
    at = "TIMESTAMPTZ '{date} 00:00:00+00' + to_microseconds((i * 86400000000 // {n})::BIGINT)"
    outside = (
        "CASE WHEN i % 11 = 0 THEN '2001:db8:' || to_hex(i % 4096) || '::' || to_hex(i % 97 + 1)"
        " WHEN i % 2 = 0 THEN '203.0.113.' || (i % 254 + 1)"
        " ELSE '198.51.100.' || (i % 254 + 1) END"
    )
    sources = (
        # source, template, rows a day, class, status, user, src ip, host, dst ip, message, unmapped
        ("fw", "paloalto_traffic", per_day, "4001", "1", "NULL",
         # one row in 3 is a probe from outside, from a wide spread of addresses
         "CASE WHEN i % 3 = 0 THEN '2001:db8:' || to_hex(hash(i, '{date}') % 65536) || '::'"
         " || to_hex(i % 65521) ELSE '10.20.' || (i % 4) || '.' || (i % 250 + 1) END",
         "'pa-01.corp.internal'",
         "'198.51.100.' || (i % 200 + 1)", "'end'", "'{}'"),
        ("lin_auth", "linux_sshd", per_day // 5, "3002", "CASE WHEN i % 4 = 0 THEN 1 ELSE 2 END",
         f"CASE WHEN i % 4 = 0 THEN 'user' || (i % 300) ELSE {_SPRAY}[i % 10 + 1] END",
         f"CASE WHEN i % 4 = 0 THEN '10.20.1.' || (i % 250 + 1) ELSE {outside} END",
         "'srv' || lpad((i % 40)::VARCHAR, 2, '0') || '.corp.internal'", "NULL",
         "CASE WHEN i % 4 = 0 THEN 'Accepted publickey' ELSE 'Failed password' END", "'{}'"),
        ("win", "windows_nxlog_json", per_day // 5, "3002", "CASE WHEN i % 25 = 0 THEN 2 ELSE 1 END",
         "'user' || (i % 300) || '@example.com'", "'10.30.' || (i % 4) || '.' || (i % 250 + 1)",
         "'ws-' || lpad((i % 300)::VARCHAR, 4, '0') || '.corp.internal'", "NULL",
         "'An account was logged on'", "'{}'"),
        ("hooks", "claude_hooks", per_day // 50, "6003", "1",
         "'user' || (i % 40) || '@example.com'", "NULL",
         "'ws-' || lpad((i % 40)::VARCHAR, 4, '0') || '.corp.internal'", "NULL",
         "CASE WHEN i % 30 = 0 THEN 'claude_hooks.post_tool_use_failure'"
         " ELSE 'claude_hooks.pre_tool_use' END",
         "'{\"attr\":{\"tool_name\":\"Bash\",\"claude_account_email\":\"user' || (i % 40)"
         " || CASE WHEN i % 40 = 7 THEN '@example.net' ELSE '@example.com' END || '\"'"
         " || CASE WHEN i % 13 = 0 THEN ',\"mcp_server_name\":\"wiki' || (i % 3) || '\"' ELSE '' END"
         " || '}}'"),
    )  # fmt: skip
    total = 0
    for back in range(days - 1, -1, -1):
        date = (end - timedelta(days=back)).strftime("%Y-%m-%d")
        for source, tpl, n, cls, status, user, ip, host, dst, msg, unmapped in sources:
            out = lake / f"source={source}" / f"day={date}"
            out.mkdir(parents=True, exist_ok=True)
            con.execute("DELETE FROM e")
            t = at.format(date=date, n=n)
            ip = ip.replace("{date}", date)  # each day its own probes
            con.execute(f"""
INSERT INTO e (event_id, source_id, template_id, template_version, time, time_observed,
  class_uid, status_id, activity_id, actor_user_name, src_endpoint_ip, device_hostname,
  dst_endpoint_ip, message, unmapped, raw, raw_bytes_invalid, parse_status,
  classification, owner_id)
SELECT '{date}-{source}-' || i, '{source}', '{tpl}', '1.0.0', {t}, {t}, {cls}, {status}, 1,
  {user}, {ip}, {host}, {dst}, {msg}, {unmapped}, 'line ' || i, false, 'ok', 'local_only',
  'system'
FROM range({n}) t(i)""")  # test data, fixed text
            total += con.execute("SELECT count(*) FROM e").fetchone()[0]  # type: ignore[index]  # one row
            con.execute(f"COPY e TO '{out}/part-0000.parquet' (FORMAT parquet, COMPRESSION zstd)")
    return total
