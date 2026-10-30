"""Dashboard sections (ADR-0038 edit 10): Identity, Attacks and access, and Detections, for
one page window (24 hours, 7 days, or 30 days) against the window before it.

Everything is read on the caller's view (rule 13): events through the per-session `events`
view and the guard, rule matches only on sources the caller may read. A section whose
source the viewer does not have is None, so the page hides it. Countries come from local
GeoIP (ADR-0023); "external" and "outside approved countries" use the install's lists
(`app.enrich.networks`). No model is called.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.ai import consents
from app.engine.duckdb import QueryEngine, QueryScope
from app.enrich.geoip import GeoInfo
from app.enrich.networks import Network, Places, is_internal
from app.meta.db import MetaDB

Window = Literal["24h", "7d", "30d"]
TIMEOUT_S = 20.0
TOP = 5
SMALL_MULTIPLES = 6
MAX_IPS = 5000
MAX_MATCHES = 5000
VPN_TEMPLATES = ("paloalto_globalprotect", "openvpn_server")
Lookup = Callable[[list[str]], dict[str, GeoInfo]]

_TS = "coalesce(time, time_observed)"
_BUCKET = f"date_trunc($unit, timezone('UTC', {_TS}))"
_WHO = "nullif(trim(actor_user_name), '')"
_HOST = "coalesce(nullif(device_hostname, ''), nullif(dst_endpoint_hostname, ''))"

SIGNIN_TOTALS_SQL = f"""
SELECT count(*) FILTER (WHERE {_TS} >= $start),
       count(*) FILTER (WHERE {_TS} >= $start AND status_id = 2),
       count(*) FILTER (WHERE {_TS} < $start AND status_id = 2)
FROM events WHERE template_id = 'm365_signin'"""  # noqa: S608  # fixed SQL text

SIGNIN_FAILED_BY_BUCKET_SQL = f"""
SELECT {_BUCKET} AS b, count(*) FROM events
WHERE template_id = 'm365_signin' AND status_id = 2 AND {_TS} >= $start
GROUP BY 1"""  # noqa: S608  # fixed SQL text

TOP_FAILING_SQL = f"""
SELECT {_WHO} AS who, count(*) AS n, max({_TS}) AS last FROM events
WHERE template_id = 'm365_signin' AND status_id = 2 AND {_TS} >= $start AND {_WHO} IS NOT NULL
GROUP BY 1 ORDER BY n DESC, who LIMIT {TOP}"""  # noqa: S608  # fixed SQL text

# Per address: successful and failed sign-ins now, successful before. Countries are looked
# up in Python, busiest addresses first.
SIGNIN_BY_IP_SQL = f"""
SELECT src_endpoint_ip AS ip,
       count(*) FILTER (WHERE {_TS} >= $start AND status_id = 1) AS ok_now,
       count(*) FILTER (WHERE {_TS} < $start AND status_id = 1) AS ok_before
FROM events
WHERE list_contains($templates, template_id) AND activity_id IS DISTINCT FROM 2
  AND nullif(src_endpoint_ip, '') IS NOT NULL
GROUP BY 1 ORDER BY ok_now + ok_before DESC LIMIT {MAX_IPS}"""  # noqa: S608  # fixed SQL text

# Risky Microsoft 365 changes, one row per operation (Graph and the Management Activity
# API report some of the same ones; the correlation id, else person and minute, joins them).
CHANGES_SQL = f"""
WITH r AS (
  SELECT {_TS} AS ts, lower(rtrim(trim(message), '.')) AS op, raw,
         coalesce(metadata_correlation_uid,
                  coalesce(lower(actor_user_name), '') || '|' || strftime({_TS}, '%Y-%m-%d %H:%M'))
           AS k
  FROM events
  WHERE template_id IN ('m365_directory_audit', 'm365_management_activity')
),
c AS (
  SELECT ts, k, op, CASE
    WHEN op IN ('new-inboxrule', 'set-inboxrule', 'updateinboxrules') THEN 'inbox'
    WHEN op = 'set-mailbox' AND raw ILIKE '%Forwarding%' THEN 'inbox'
    WHEN op IN ('add member to role', 'add eligible member to role') THEN 'role'
    WHEN op LIKE '%conditional access policy' THEN 'ca'
  END AS kind
  FROM r
),
one AS (SELECT kind, min(ts) AS ts FROM c WHERE kind IS NOT NULL GROUP BY kind, k, op)
SELECT kind, count(*) FILTER (WHERE ts >= $start), count(*) FILTER (WHERE ts < $start)
FROM one GROUP BY kind"""  # noqa: S608  # fixed SQL text

# Authentication failures outside Microsoft 365 (SSH, Windows, VPN, and the rest), per
# address; "external" is decided in Python from the internal networks.
AUTH_FAIL_BY_IP_SQL = f"""
SELECT src_endpoint_ip AS ip,
       count(*) FILTER (WHERE {_TS} >= $start) AS now,
       count(*) FILTER (WHERE {_TS} < $start) AS before
FROM events
WHERE class_uid = 3002 AND status_id = 2 AND template_id NOT LIKE 'm365_%'
  AND nullif(src_endpoint_ip, '') IS NOT NULL
GROUP BY 1 ORDER BY now + before DESC LIMIT {MAX_IPS}"""  # noqa: S608  # fixed SQL text

AUTH_FAIL_BY_HOST_SQL = f"""
SELECT coalesce({_HOST}, '(no host)') AS host, {_BUCKET} AS b, count(*) FROM events
WHERE class_uid = 3002 AND status_id = 2 AND template_id NOT LIKE 'm365_%'
  AND {_TS} >= $start AND list_contains($ips, src_endpoint_ip)
GROUP BY 1, 2"""  # noqa: S608  # fixed SQL text

INVOLVED_SQL = f"""
SELECT event_id, {_WHO} AS who, {_HOST} AS host FROM events
WHERE list_contains($ids, event_id)"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class Kpi:
    value: int
    before: int | None = None
    extra: int | None = None  # a second number the card states (blocked consents)


@dataclass(slots=True)
class Series:
    label: str
    counts: list[int]
    level: str | None = None  # a rule's level, for Detections


@dataclass(slots=True)
class Row:
    label: str
    count: int
    kind: str = ""
    detail: str = ""
    last: str | None = None


@dataclass(slots=True)
class Identity:
    failed: Kpi
    outside: Kpi | None  # None: approved countries not set
    inbox_rules: Kpi
    consents: Kpi
    role_grants: Kpi
    ca_edits: Kpi
    sign_ins: int
    failed_by_bucket: list[int]
    top_failing: list[Row]


@dataclass(slots=True)
class Attacks:
    failures: Kpi
    addresses: Kpi
    countries: Kpi | None  # None: no GeoIP file
    vpn_outside: Kpi | None  # None: approved countries not set or no VPN source
    has_vpn: bool
    by_host: list[Series]
    top_sources: list[Row]


@dataclass(slots=True)
class Detections:
    matches: Kpi
    rules_matched: Kpi  # extra: rules enabled
    hosts: Kpi
    users: Kpi
    by_rule: list[Series]
    involved: list[Row]


@dataclass(slots=True)
class Sections:
    window: str
    start: datetime
    end: datetime
    buckets: list[datetime]
    approved_set: bool
    has_public: bool
    identity: Identity | None = None
    attacks: Attacks | None = None
    detections: Detections | None = None
    read: list[str] = field(default_factory=list)


def bounds(window: Window, now: datetime) -> tuple[datetime, datetime, list[datetime]]:
    """Window start, the start of the window before, and the bucket starts (UTC hours for
    24 hours, UTC days otherwise; the last bucket holds now)."""
    if window == "24h":
        top = now.replace(minute=0, second=0, microsecond=0)
        buckets = [top - timedelta(hours=23 - i) for i in range(24)]
        start = buckets[0]
        return start, start - timedelta(hours=24), buckets
    days = 7 if window == "7d" else 30
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    buckets = [today - timedelta(days=days - 1 - i) for i in range(days)]
    start = buckets[0]
    return start, start - timedelta(days=days), buckets


def _utc(v: Any) -> datetime | None:
    """A timestamp from a result cell (the engine returns text) or a datetime, in UTC."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return None
    if not isinstance(v, datetime):
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def _iso(v: Any) -> str | None:
    t = _utc(v)
    return t.isoformat() if t else None


def _spread(rows: list[tuple[Any, int]], buckets: list[datetime]) -> list[int]:
    at = {b: i for i, b in enumerate(buckets)}
    out = [0] * len(buckets)
    for b, n in rows:
        t = _utc(b)
        if t is not None and t in at:
            out[at[t]] += int(n)
    return out


class _Run:
    """Runs fixed SQL on one scope and remembers the sources read."""

    def __init__(self, engine: QueryEngine, scope: QueryScope, params: dict[str, Any]) -> None:
        self.engine, self.scope, self.params = engine, scope, params
        self.read: set[str] = set()

    def __call__(self, sql: str, sources: list[str], **extra: Any) -> list[list[Any]]:
        if not sources:
            return []
        scope = QueryScope(sources=sources, start=self.scope.start, end=self.scope.end)
        # DuckDB takes exactly the parameters a statement names.
        params = {k: v for k, v in {**self.params, **extra}.items() if f"${k}" in sql}
        res = self.engine.run(sql, scope, params, timeout_s=TIMEOUT_S, name="dashboard")
        self.read |= set(res.sources)
        return res.rows


def _outside(
    rows: list[list[Any]], geo: Lookup, approved: set[str]
) -> tuple[Kpi, dict[str, GeoInfo]]:
    """Successful sign-ins or logins from addresses whose country is not approved, now and
    before. Addresses GeoIP cannot place are not counted."""
    found = geo([str(r[0]) for r in rows])
    now = before = 0
    for ip, ok_now, ok_before in rows:
        info = found.get(str(ip))
        if info and info.country and info.country.upper() not in approved:
            now += int(ok_now)
            before += int(ok_before)
    return Kpi(now, before), found


def _identity(
    run: _Run, m365: list[str], places: Places, geo: Lookup, buckets: list[datetime]
) -> Identity:
    total, failed, failed_before = (run(SIGNIN_TOTALS_SQL, m365) or [[0, 0, 0]])[0]
    by_bucket = _spread([(r[0], r[1]) for r in run(SIGNIN_FAILED_BY_BUCKET_SQL, m365)], buckets)
    top = [
        Row(str(who), int(n), kind="user", last=_iso(last))
        for who, n, last in run(TOP_FAILING_SQL, m365)
    ]
    outside = None
    if places.approved_countries:
        ips = run(SIGNIN_BY_IP_SQL, m365, templates=["m365_signin"])
        outside, _ = _outside(ips, geo, set(places.approved_countries))
    changes = {str(k): (int(a), int(b)) for k, a, b in run(CHANGES_SQL, m365)}
    granted, granted_before, blocked = (run(consents.COUNTS_SQL, m365) or [[0, 0, 0]])[0][:3]
    return Identity(
        failed=Kpi(int(failed), int(failed_before)),
        outside=outside,
        inbox_rules=Kpi(*changes.get("inbox", (0, 0))),
        consents=Kpi(int(granted), int(granted_before), int(blocked)),
        role_grants=Kpi(*changes.get("role", (0, 0))),
        ca_edits=Kpi(*changes.get("ca", (0, 0))),
        sign_ins=int(total),
        failed_by_bucket=by_bucket,
        top_failing=top,
    )


def _attacks(
    run: _Run,
    auth: list[str],
    vpn: list[str],
    places: Places,
    geo: Lookup,
    buckets: list[datetime],
) -> Attacks | None:
    nets: list[Network] = places.networks()
    rows = [r for r in run(AUTH_FAIL_BY_IP_SQL, auth) if not is_internal(str(r[0]), nets)]
    if not rows:
        return None
    now_ips = [str(r[0]) for r in rows if int(r[1])]
    before_ips = [str(r[0]) for r in rows if int(r[2])]
    found = geo([str(r[0]) for r in rows])
    countries = None
    if found or now_ips:
        have_geo = bool(found)
        c_now = {found[i].country for i in now_ips if i in found and found[i].country}
        c_before = {found[i].country for i in before_ips if i in found and found[i].country}
        countries = Kpi(len(c_now), len(c_before)) if have_geo else None
    hosts: dict[str, list[int]] = defaultdict(lambda: [0] * len(buckets))
    at = {b: i for i, b in enumerate(buckets)}
    for host, b, n in run(AUTH_FAIL_BY_HOST_SQL, auth, ips=now_ips):
        t = _utc(b)
        if t is not None and t in at:
            hosts[str(host)][at[t]] += int(n)
    ranked = sorted(hosts.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:SMALL_MULTIPLES]
    groups: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for ip, now, _ in rows:
        if not int(now):
            continue
        info = found.get(str(ip))
        country = (info.country_name or info.country or "") if info else ""
        network = f"AS{info.asn} {info.org or ''}".strip() if info and info.asn else ""
        g = groups[(country or "Unknown", network)]
        g[0] += 1
        g[1] += int(now)
    top = sorted(groups.items(), key=lambda kv: (-kv[1][1], kv[0]))[:TOP]
    vpn_outside = None
    if vpn and places.approved_countries:
        logins = run(SIGNIN_BY_IP_SQL, vpn, templates=list(VPN_TEMPLATES))
        vpn_outside, _ = _outside(logins, geo, set(places.approved_countries))
    return Attacks(
        failures=Kpi(sum(int(r[1]) for r in rows), sum(int(r[2]) for r in rows)),
        addresses=Kpi(len(now_ips), len(before_ips)),
        countries=countries,
        vpn_outside=vpn_outside,
        has_vpn=bool(vpn),
        by_host=[Series(h, counts) for h, counts in ranked],
        top_sources=[
            Row(country, n, kind="network", detail=f"{network}|{addrs}")
            for (country, network), (addrs, n) in top
        ],
    )


def _matches(
    meta: MetaDB, allowed: list[str] | None, start: datetime, before: datetime
) -> tuple[list[tuple[str, str, str, datetime | None]], int]:
    """(rule title, level, event id, event time) of matches since the window before, one
    per rule and event, on readable sources; and how many rules are enabled."""
    with meta.connect() as con:
        rows = con.execute(
            "SELECT v.rule_id, v.title, v.level, m.event_id, m.event_time, m.source_id"
            " FROM rule_matches m JOIN rule_runs r ON r.run_id = m.run_id"
            " JOIN rule_versions v ON v.sha256 = r.sha256"
            " WHERE m.event_time >= ? ORDER BY m.rowid DESC LIMIT ?",
            (before.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"), MAX_MATCHES * 4),
        ).fetchall()
        enabled = con.execute("SELECT count(*) FROM rules WHERE enabled = 1").fetchone()[0]
    permitted = None if allowed is None else set(allowed)
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, datetime | None]] = []
    for r in rows:
        if permitted is not None and r["source_id"] not in permitted:
            continue
        key = (str(r["rule_id"]), str(r["event_id"]))
        if key in seen:
            continue
        seen.add(key)
        when = _utc(datetime.fromisoformat(r["event_time"])) if r["event_time"] else None
        out.append((str(r["title"]), str(r["level"]).lower(), str(r["event_id"]), when))
    return out[:MAX_MATCHES], int(enabled)


def _detections(
    run: _Run,
    meta: MetaDB,
    allowed: list[str] | None,
    readable: list[str],
    start: datetime,
    before: datetime,
    buckets: list[datetime],
    window: Window,
) -> Detections | None:
    matches, enabled = _matches(meta, allowed, start, before)
    if not enabled and not matches:
        return None
    now = [m for m in matches if m[3] is not None and m[3] >= start]
    prior = [m for m in matches if m[3] is not None and m[3] < start]
    step = timedelta(hours=1) if window == "24h" else timedelta(days=1)
    by_rule: dict[str, list[int]] = defaultdict(lambda: [0] * len(buckets))
    levels: dict[str, str] = {}
    for title, level, _, when in now:
        assert when is not None  # filtered above
        i = int((when - buckets[0]) / step)
        if 0 <= i < len(buckets):
            by_rule[title][i] += 1
        levels[title] = level
    ranked = sorted(by_rule.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:SMALL_MULTIPLES]
    ids = sorted({m[2] for m in now})
    involved_rows = run(INVOLVED_SQL, readable, ids=ids) if ids else []
    per_event = {str(e): (who, host) for e, who, host in involved_rows}
    hosts: Counter[str] = Counter()
    users: Counter[str] = Counter()
    for _, _, eid, _ in now:
        who, host = per_event.get(eid, (None, None))
        if host:
            hosts[str(host)] += 1
        if who:
            users[str(who)] += 1
    involved = [Row(h, n, kind="host") for h, n in hosts.most_common(TOP)]
    involved += [Row(u, n, kind="user") for u, n in users.most_common(TOP)]
    involved.sort(key=lambda r: (-r.count, r.kind, r.label))
    return Detections(
        matches=Kpi(len(now), len(prior)),
        rules_matched=Kpi(len({m[0] for m in now}), len({m[0] for m in prior}), extra=enabled),
        hosts=Kpi(len(hosts)),
        users=Kpi(len(users)),
        by_rule=[Series(t, c, level=levels.get(t)) for t, c in ranked],
        involved=involved[: TOP * 2],
    )


def sections(
    engine: QueryEngine,
    meta: MetaDB,
    allowed: list[str] | None,
    sources: list[tuple[str, str, str | None]],
    places: Places,
    geo: Lookup,
    window: Window,
    now: datetime,
) -> Sections:
    """The three sections for the caller. `sources` is the install's (id, kind, template);
    only those the caller may read are used."""
    start, before, buckets = bounds(window, now)
    mine = [s for s in sources if allowed is None or s[0] in set(allowed)]
    m365 = [sid for sid, kind, tpl in mine if kind == "m365" or (tpl or "").startswith("m365_")]
    vpn = [sid for sid, _, tpl in mine if tpl in VPN_TEMPLATES]
    other = [sid for sid, _, _ in mine if sid not in set(m365)]
    unit = "hour" if window == "24h" else "day"
    run = _Run(
        engine,
        QueryScope(sources=None, start=before, end=now),
        {"start": start, "unit": unit},
    )
    out = Sections(
        window=window,
        start=start,
        end=now,
        buckets=buckets,
        approved_set=bool(places.approved_countries),
        has_public=places.has_public,
    )
    if m365:
        out.identity = _identity(run, m365, places, geo, buckets)
    out.attacks = _attacks(run, other, vpn, places, geo, buckets)
    out.detections = _detections(
        run, meta, allowed, [s[0] for s in mine], start, before, buckets, window
    )
    out.read = sorted(run.read)
    return out
