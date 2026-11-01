"""The Dashboard's Attacks and access facts (owner, 2026-10-31; SPEC D135).

Failed sign-ins outside Microsoft 365 (SSH, Windows, VPN, and the rest) and VPN logins,
reduced to one row per hour, address, and host. Closed days come from the auth rollup
(`app.search.m365_rollup.AuthRollup`), today from events, with this same SQL, so both give
the numbers the events would. "External" is still decided in Python from the internal
networks, and countries from the local GeoIP files, at read time.
"""

from __future__ import annotations

from app.search.buckets import bucket_sql

TS = "coalesce(time, time_observed)"
HOST = "coalesce(nullif(device_hostname, ''), nullif(dst_endpoint_hostname, ''))"
VPN_TEMPLATES = ("paloalto_globalprotect", "openvpn_server")
# Addresses read per window: every one on a busy install (it was 5,000, which undercounted
# addresses and failures on the owner's data); past this many the counts are of the top.
MAX_IPS = 100_000
COLUMNS = "kind, source_id, t, ip, host, n"

FACTS: dict[str, str] = {
    "fail": f"""
SELECT 'fail' AS kind, source_id, date_trunc('hour', {TS}) AS t, src_endpoint_ip AS ip,
       coalesce({HOST}, '(no host)') AS host, count(*) AS n
FROM events
WHERE class_uid = 3002 AND status_id = 2 AND template_id NOT LIKE 'm365_%'
  AND nullif(src_endpoint_ip, '') IS NOT NULL
GROUP BY ALL""",  # noqa: S608  # fixed SQL text
    # Successful VPN logins per address: the outside-countries card for VPNs.
    "vpn": f"""
SELECT 'vpn' AS kind, source_id, date_trunc('hour', {TS}) AS t, src_endpoint_ip AS ip,
       CAST(NULL AS VARCHAR) AS host, count(*) AS n
FROM events
WHERE list_contains({list(VPN_TEMPLATES)}, template_id) AND activity_id IS DISTINCT FROM 2
  AND status_id = 1 AND nullif(src_endpoint_ip, '') IS NOT NULL
GROUP BY ALL""",  # noqa: S608  # fixed SQL text
}
BUILD_SQL = "\nUNION ALL\n".join(f"({sql.strip()})" for sql in FACTS.values())


def facts(kind: str, rollup: bool) -> str:
    live = FACTS[kind].strip()
    if not rollup:
        return live
    return (
        f"({live})\nUNION ALL\nSELECT {COLUMNS} FROM auth_rollup\n"
        f"WHERE kind = '{kind}' AND (source_id || '|' || day) IN (SELECT unnest($covered))"
        " AND t >= $fact_lo AND t <= $fact_hi"
    )


_BY_IP = f"""
SELECT ip, coalesce(sum(n) FILTER (WHERE t >= $start), 0) AS now,
       coalesce(sum(n) FILTER (WHERE t < $start), 0) AS before
FROM f GROUP BY 1 ORDER BY now + before DESC LIMIT {MAX_IPS}"""  # noqa: S608  # fixed SQL text
# The outside addresses' failures per host and bucket, and the sources they came from, in
# one pass over the facts (they were two, each reading the window again).
_DETAIL = """
, g AS MATERIALIZED (SELECT * FROM f WHERE t >= $start AND ip IN (SELECT unnest($ips)))
SELECT 'host' AS part, host AS k, {BUCKET} AS b, sum(n) AS n FROM g GROUP BY 1, 2, 3
UNION ALL
SELECT 'source', source_id, NULL, NULL FROM g GROUP BY 1, 2""".replace("{BUCKET}", bucket_sql())

# Query -> (fact kind, body reading `f`).
QUERIES: dict[str, tuple[str, str]] = {
    "fail_by_ip": ("fail", _BY_IP),
    "fail_detail": ("fail", _DETAIL),
    "vpn_by_ip": ("vpn", _BY_IP),
}


def query(name: str, rollup: bool) -> str:
    kind, body = QUERIES[name]
    head = f"WITH f AS (\n{facts(kind, rollup)}\n)"
    return head + body if body.startswith("\n,") else f"{head}\n{body.strip()}"
