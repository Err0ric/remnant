"""Who had an address at the time (ADR-0020 row 1).

Network logs often name only an address. Logs the server already has tie addresses to
people and machines: successful logons (Windows 4624 and other OCSF Authentication
events: the client address with the user and workstation), Palo Alto User-ID mappings,
and GlobalProtect sessions (the private address handed to a remote user). For an
address at an hour, the newest of those seen up to the end of that hour and no more
than MAX_AGE before it wins. Deterministic SQL over the caller's own events view, so a
person sees only mappings from sources they may read.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.identity import NOT_PEOPLE

MAX_AGE_HOURS = 12

_NOT_PEOPLE = ", ".join(f"'{n}'" for n in sorted(NOT_PEOPLE | {"-", "anonymous logon"}))
_ACTOR = "nullif(trim(actor_user_name), '')"
# Machine accounts (WS01$) name the computer, not a person.
_WHO = (
    f"CASE WHEN ends_with({_ACTOR}, '$') OR lower({_ACTOR}) IN ({_NOT_PEOPLE})"
    f" OR lower(regexp_replace({_ACTOR}, '^[^\\\\]*\\\\', '')) IN ({_NOT_PEOPLE})"
    f" THEN NULL ELSE {_ACTOR} END"
)
_HOST = (
    "coalesce(nullif(nullif(trim(src_endpoint_hostname), ''), '-'),"
    f" CASE WHEN ends_with({_ACTOR}, '$') THEN rtrim(regexp_replace({_ACTOR},"
    " '^[^\\\\]*\\\\', ''), '$') END)"
)
_BAD_IP = "('', '-', '127.0.0.1', '::1', '0.0.0.0')"

OBS_SQL = f"""addr_obs AS (
  SELECT src_endpoint_ip AS ip, coalesce(time, time_observed) AS t, {_WHO} AS who,
         {_HOST} AS host
  FROM events
  WHERE src_endpoint_ip IS NOT NULL AND src_endpoint_ip NOT IN {_BAD_IP}
    AND ((template_id = 'paloalto_userid' AND coalesce(activity_id, 1) <> 2)
         OR (class_uid = 3002 AND coalesce(status_id, 1) = 1
             AND coalesce(activity_id, 1) IN (1, 3)))
  UNION ALL
  SELECT json_extract_string(unmapped, '$.private_ip'), coalesce(time, time_observed),
         {_WHO}, nullif(trim(src_endpoint_hostname), '')
  FROM events
  WHERE template_id = 'paloalto_globalprotect'
    AND coalesce(json_extract_string(unmapped, '$.private_ip'), '') NOT IN {_BAD_IP}
),
addr_user AS (SELECT ip, t, who FROM addr_obs WHERE who IS NOT NULL),
addr_host AS (SELECT ip, t, host FROM addr_obs WHERE host IS NOT NULL)"""  # noqa: S608  # fixed text


def address_ctes(src: str, need: str = "true", obs: bool = True) -> str:
    """CTEs ending in `addr(ip, hr, rwho, rhost)`: the person and machine behind each
    address of `src` (a CTE with columns `ip` and `t`) in each hour, for rows where
    `need` holds. `obs=False` when OBS_SQL is already earlier in the same WITH. `src`
    and `need` are fixed text from the caller, never user input."""
    head = f"{OBS_SQL},\n" if obs else ""
    return f"""{head}addr_need AS (
  SELECT DISTINCT ip, date_trunc('hour', t) AS hr FROM {src}
  WHERE ip IS NOT NULL AND ({need})
),
addr AS (
  SELECT n.ip, n.hr,
         CASE WHEN n.hr + INTERVAL 1 HOUR - u.t <= INTERVAL {MAX_AGE_HOURS} HOUR
              THEN u.who END AS rwho,
         CASE WHEN n.hr + INTERVAL 1 HOUR - h.t <= INTERVAL {MAX_AGE_HOURS} HOUR
              THEN h.host END AS rhost
  FROM addr_need n
  ASOF LEFT JOIN addr_user u ON n.ip = u.ip AND n.hr + INTERVAL 1 HOUR >= u.t
  ASOF LEFT JOIN addr_host h ON n.ip = h.ip AND n.hr + INTERVAL 1 HOUR >= h.t
)"""  # noqa: S608  # fixed text from callers in this package


def join_addr(alias: str) -> str:
    """The join that adds `addr.rwho` and `addr.rhost` to rows of `alias`."""
    return f"LEFT JOIN addr ON {alias}.ip = addr.ip AND date_trunc('hour', {alias}.t) = addr.hr"


LOOKUP_SQL = f"""WITH {OBS_SQL}
SELECT 'user' AS kind, who AS name, max(t) AS last, count(*) AS n FROM addr_user
WHERE ip = $ip AND t <= $at AND t >= $at - INTERVAL {MAX_AGE_HOURS} HOUR GROUP BY 2
UNION ALL
SELECT 'host', host, max(t), count(*) FROM addr_host
WHERE ip = $ip AND t <= $at AND t >= $at - INTERVAL {MAX_AGE_HOURS} HOUR GROUP BY 2
ORDER BY 1, 3 DESC
LIMIT 20"""  # noqa: S608  # fixed text; the address and time are parameters


@dataclass(frozen=True, slots=True)
class AddressHolder:
    kind: str  # "user" or "host"
    name: str
    last_seen: str
    events: int


def lookup(engine: QueryEngine, scope: QueryScope, ip: str, at: datetime) -> list[AddressHolder]:
    """Who and which machine had `ip` in the MAX_AGE hours up to `at`, newest first."""
    try:
        clean = str(ipaddress.ip_address(ip.strip()))
    except ValueError as exc:
        raise ParamInvalidError("Give an IP address") from exc
    at = at.astimezone(UTC)
    window = QueryScope(scope.sources, at - timedelta(hours=MAX_AGE_HOURS), at)
    rows = engine.run(LOOKUP_SQL, window, {"ip": clean, "at": at}, timeout_s=20).rows
    out = []
    for kind, name, last, n in rows:
        t = last if isinstance(last, datetime) else datetime.fromisoformat(str(last))
        out.append(AddressHolder(str(kind), str(name), t.isoformat(), int(n)))
    return out
