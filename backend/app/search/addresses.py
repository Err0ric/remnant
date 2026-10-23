"""Who had an address at the time (ADR-0020 row 1, ADR-0029 / D107).

Network logs often name only an address. Logs the server already has tie addresses to
people and machines, as **spans** with a start and an end:

- vpn: a GlobalProtect login (its private address) gives the person and laptop; it ends
  at its logout or the next login on the address; cap 24 h.
- userid: a Palo Alto User-ID login gives the person; ends at its logout or the next
  mapping; cap 12 h.
- logon: a successful OCSF Authentication (Windows 4624 and others) gives the person and
  workstation; ends at the next logon on the address; cap 12 h.
- dhcp: a DHCP lease (Palo Alto system log, subtype dhcp) gives the machine and MAC; ends
  at the next lease of the address; cap 24 h.

A span that ran into its cap is marked `capped`: shown as "no logout seen (assumed until
...)", never as fact (D107 C1). DHCP names a machine, never a person (row 6). A machine
named by DHCP (or a logon) gets a person through a successful Microsoft 365 sign-in on
that machine in the 24 hours before, when only one person signed in on it (row 5a,
D107 C2): the match then shows both steps.

Precedence for the person: VPN, then User-ID, then logon, then a sign-in on the device;
for the machine: VPN laptop, then DHCP, then logon workstation (row 5). Microsoft 365
sign-ins never name an address: their address is the office's public egress.

Deterministic SQL over the caller's own events view, so a person sees only matches from
sources they may read (rule 13, D107 C4); matches are computed per query, so they age out
with the events they come from.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.identity import NOT_PEOPLE

MAX_AGE_HOURS = 24  # the longest cap: how far before a range a span may start
CAPS = {"vpn": 24, "userid": 12, "logon": 12, "dhcp": 24}
SIGNIN_HOURS = 24  # a sign-in on a device names its person for this long (row 5a)

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
_TS = "coalesce(time, time_observed)"
_DHCP_IP = "regexp_extract(message, 'lease started ip ([0-9a-fA-F.:]+)', 1)"
_DHCP_HOST = "nullif(regexp_extract(message, 'hostname ([^,\\s]+)', 1), '[Unavailable]')"
_DHCP_MAC = "nullif(regexp_extract(message, 'mac ([0-9A-Fa-f:]{17})', 1), '')"
_CAP = "CASE kind " + " ".join(f"WHEN '{k}' THEN INTERVAL {h} HOUR" for k, h in CAPS.items())
_CAP += " END"

# Every event that starts (`fin` false) or ends (`fin` true) a span on an address.
OBS_SQL = f"""addr_ev AS (
  SELECT 'logon' AS kind, src_endpoint_ip AS ip, {_TS} AS t, {_WHO} AS who, {_HOST} AS host,
         CAST(NULL AS VARCHAR) AS mac, false AS fin, source_id AS src
  FROM events
  WHERE class_uid = 3002 AND coalesce(status_id, 1) = 1 AND coalesce(activity_id, 1) IN (1, 3)
    AND src_endpoint_ip IS NOT NULL AND src_endpoint_ip NOT IN {_BAD_IP}
    AND template_id NOT IN ('paloalto_globalprotect', 'paloalto_userid')
    AND template_id NOT LIKE 'm365%'
  UNION ALL
  SELECT 'userid', src_endpoint_ip, {_TS}, {_WHO}, NULL, NULL,
         coalesce(activity_id, 1) = 2, source_id
  FROM events
  WHERE template_id = 'paloalto_userid' AND src_endpoint_ip IS NOT NULL
    AND src_endpoint_ip NOT IN {_BAD_IP}
  UNION ALL
  SELECT 'vpn', json_extract_string(unmapped, '$.private_ip'), {_TS}, {_WHO},
         nullif(trim(src_endpoint_hostname), ''), NULL, coalesce(activity_id, 1) = 2, source_id
  FROM events
  WHERE template_id = 'paloalto_globalprotect' AND coalesce(activity_id, 1) IN (1, 2)
    AND coalesce(json_extract_string(unmapped, '$.private_ip'), '') NOT IN {_BAD_IP}
  UNION ALL
  SELECT 'dhcp', {_DHCP_IP}, {_TS}, NULL, {_DHCP_HOST}, {_DHCP_MAC}, false, source_id
  FROM events
  WHERE template_id = 'paloalto_system' AND json_extract_string(unmapped, '$.subtype') = 'dhcp'
    AND {_DHCP_IP} <> ''
),
addr_span AS (
  SELECT kind, ip, t AS start, who, host, mac, src,
         least(coalesce(nxt, t + {_CAP}), t + {_CAP}) AS stop,
         nxt IS NULL OR nxt > t + {_CAP} AS capped
  FROM (
    SELECT *, lead(t) OVER (PARTITION BY kind, ip ORDER BY t, fin DESC) AS nxt FROM addr_ev
  ) WHERE NOT fin
),
addr_user AS (
  SELECT ip, start AS t, stop, who, kind, capped, src,
         CASE kind WHEN 'vpn' THEN 0 WHEN 'userid' THEN 1 ELSE 2 END AS rank
  FROM addr_span WHERE who IS NOT NULL
),
addr_host AS (
  SELECT ip, start AS t, stop, host, kind, capped, src,
         CASE kind WHEN 'vpn' THEN 0 WHEN 'dhcp' THEN 1 ELSE 2 END AS rank
  FROM addr_span WHERE host IS NOT NULL
),
dev_sign AS (
  SELECT lower(device_hostname) AS dev, {_TS} AS t, {_WHO} AS who, source_id AS src,
         lag({_WHO}) OVER (PARTITION BY lower(device_hostname) ORDER BY {_TS}) AS prev_who,
         lag({_TS}) OVER (PARTITION BY lower(device_hostname) ORDER BY {_TS}) AS prev_t
  FROM events
  WHERE template_id = 'm365_signin' AND coalesce(status_id, 1) = 1
    AND nullif(trim(device_hostname), '') IS NOT NULL AND {_WHO} IS NOT NULL
)"""  # noqa: S608  # fixed text


def address_ctes(src: str, need: str = "true", obs: bool = True) -> str:
    """CTEs ending in `addr(ip, hr, rwho, rhost, ...)`: the person and machine behind
    each address of `src` (a CTE with columns `ip` and `t`) in each hour, for rows where
    `need` holds, with how each was matched (D107 C1): `rwho_how`, `rwho_at`,
    `rwho_capped`, `rwho_src`, `rhost_how`, `rhost_at`, `rhost_capped`, `rhost_src`, and
    `rwho_dev` when the person came through a sign-in on the machine.

    `obs=False` when OBS_SQL is already earlier in the same WITH. `src` and `need` are
    fixed text from the caller, never user input."""
    head = f"{OBS_SQL},\n" if obs else ""
    return f"""{head}addr_need AS (
  SELECT DISTINCT ip, date_trunc('hour', t) AS hr FROM {src}
  WHERE ip IS NOT NULL AND ({need})
),
addr_u AS (
  SELECT n.ip, n.hr, arg_min(u.who, (u.rank, -epoch(u.t))) AS who,
         arg_min(u.kind, (u.rank, -epoch(u.t))) AS how,
         arg_min(u.t, (u.rank, -epoch(u.t))) AS at,
         arg_min(u.capped, (u.rank, -epoch(u.t))) AS capped,
         arg_min(u.src, (u.rank, -epoch(u.t))) AS src
  FROM addr_need n JOIN addr_user u
    ON n.ip = u.ip AND u.t < n.hr + INTERVAL 1 HOUR AND u.stop > n.hr
  GROUP BY 1, 2
),
addr_h AS (
  SELECT n.ip, n.hr, arg_min(h.host, (h.rank, -epoch(h.t))) AS host,
         arg_min(h.kind, (h.rank, -epoch(h.t))) AS how,
         arg_min(h.t, (h.rank, -epoch(h.t))) AS at,
         arg_min(h.capped, (h.rank, -epoch(h.t))) AS capped,
         arg_min(h.src, (h.rank, -epoch(h.t))) AS src
  FROM addr_need n JOIN addr_host h
    ON n.ip = h.ip AND h.t < n.hr + INTERVAL 1 HOUR AND h.stop > n.hr
  GROUP BY 1, 2
),
addr_d AS (
  SELECT h.ip, h.hr, arg_max(s.who, s.t) AS who, max(s.t) AS at, arg_max(s.src, s.t) AS src,
         count(DISTINCT lower(s.who)) AS people
  FROM addr_h h JOIN dev_sign s
    ON s.dev = lower(h.host) AND s.t < h.hr + INTERVAL 1 HOUR
   AND s.t >= h.hr + INTERVAL 1 HOUR - INTERVAL {SIGNIN_HOURS} HOUR
  GROUP BY 1, 2
),
addr AS (
  SELECT n.ip, n.hr,
         coalesce(u.who, CASE WHEN d.people = 1 THEN d.who END) AS rwho,
         h.host AS rhost,
         CASE WHEN u.who IS NOT NULL THEN u.how
              WHEN d.people = 1 THEN 'signin'
              WHEN d.people > 1 THEN 'several' END AS rwho_how,
         CASE WHEN u.who IS NOT NULL THEN u.at ELSE d.at END AS rwho_at,
         coalesce(u.capped, false) AND u.who IS NOT NULL AS rwho_capped,
         CASE WHEN u.who IS NOT NULL THEN u.src ELSE d.src END AS rwho_src,
         CASE WHEN u.who IS NULL AND d.people >= 1 THEN h.host END AS rwho_dev,
         h.how AS rhost_how, h.at AS rhost_at, coalesce(h.capped, false) AS rhost_capped,
         h.src AS rhost_src
  FROM addr_need n
  LEFT JOIN addr_u u ON u.ip = n.ip AND u.hr = n.hr
  LEFT JOIN addr_h h ON h.ip = n.ip AND h.hr = n.hr
  LEFT JOIN addr_d d ON d.ip = n.ip AND d.hr = n.hr
)"""  # noqa: S608  # fixed text from callers in this package


def join_addr(alias: str) -> str:
    """The join that adds `addr.rwho` and `addr.rhost` to rows of `alias`."""
    return f"LEFT JOIN addr ON {alias}.ip = addr.ip AND date_trunc('hour', {alias}.t) = addr.hr"


LOOKUP_SQL = f"""WITH {OBS_SQL}
SELECT kind, start, stop, capped, who, host, mac, src FROM addr_span
WHERE ip = $ip AND start <= $at AND stop > $at - INTERVAL 1 SECOND
ORDER BY start DESC
LIMIT 20"""  # noqa: S608  # fixed text; the address and time are parameters

SIGNIN_SQL = f"""WITH {OBS_SQL}
SELECT who, max(t) AS t, any_value(src) FROM dev_sign
WHERE dev = lower($host) AND t <= $at AND t >= $at - INTERVAL {SIGNIN_HOURS} HOUR
GROUP BY 1 ORDER BY 2 DESC LIMIT 5"""  # noqa: S608  # fixed text; parameters only


@dataclass(frozen=True, slots=True)
class Span:
    """One match that held the address at the time, as the lookup panel lists it."""

    kind: str  # vpn | userid | logon | dhcp | signin
    start: str
    end: str | None  # None: open (no end seen before the cap)
    capped: bool  # no end seen: assumed until `end` (the cap)
    person: str | None
    machine: str | None
    mac: str | None
    source: str


@dataclass(frozen=True, slots=True)
class AddressHolder:
    kind: str  # "user" or "host"
    name: str
    last_seen: str
    events: int


def _iso(v: object) -> str:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).isoformat()


def spans(engine: QueryEngine, scope: QueryScope, ip: str, at: datetime) -> list[Span]:
    """The spans that held `ip` at `at`, newest first, and for a machine one of them
    names, the sign-ins on it that can name its person (D107 C1, C2)."""
    try:
        clean = str(ipaddress.ip_address(ip.strip()))
    except ValueError as exc:
        raise ParamInvalidError("Give an IP address") from exc
    at = at.astimezone(UTC)
    window = QueryScope(scope.sources, at - timedelta(hours=MAX_AGE_HOURS), at)
    out: list[Span] = []
    hosts: list[str] = []
    for kind, start, stop, capped, who, host, mac, src in engine.run(
        LOOKUP_SQL, window, {"ip": clean, "at": at}, timeout_s=20
    ).rows:
        out.append(
            Span(
                str(kind),
                _iso(start),
                _iso(stop) if stop is not None else None,
                bool(capped),
                who,
                host,
                mac,
                str(src),
            )
        )
        if host and str(host) not in hosts:
            hosts.append(str(host))
    for host in hosts[:3]:
        for who, t, src in engine.run(
            SIGNIN_SQL, window, {"host": host, "at": at}, timeout_s=20
        ).rows:
            out.append(Span("signin", _iso(t), None, False, str(who), host, None, str(src)))
    return out


def lookup(engine: QueryEngine, scope: QueryScope, ip: str, at: datetime) -> list[AddressHolder]:
    """Who and which machine had `ip` at `at`, from the spans (kept for older callers)."""
    found: dict[tuple[str, str], AddressHolder] = {}
    for s in spans(engine, scope, ip, at):
        for kind, name in (("user", s.person), ("host", s.machine)):
            if name and (kind, name) not in found and not (kind == "user" and s.kind == "dhcp"):
                found[(kind, name)] = AddressHolder(kind, name, s.start, 1)
    return list(found.values())
