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


def write_dns(lake: Path, per_day: int, days: int, end: datetime, source: str = "dns") -> int:
    """One Parquet file per day, the last day being `end`'s. Returns the rows written."""
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
        name = f"CASE WHEN i % 50 = 0 THEN {pick} ELSE 'q' || (hash(i * 7) % 90000) || '.cdn.example.org' END"
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
