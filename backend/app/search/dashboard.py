"""Dashboard sections (ADR-0038 edit 10): Identity, Attacks and access, and Detections, for
one page window (24 hours, 7 days, or 30 days) against the window before it.

Everything is read on the caller's view (rule 13): events through the per-session `events`
view and the guard, rule matches only on sources the caller may read. A section whose
source the viewer does not have is None, so the page hides it. Countries come from local
GeoIP (ADR-0023); "external" and "outside approved countries" use the install's lists
(`app.enrich.networks`). No model is called.
"""

from __future__ import annotations

import ipaddress
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ai import consents
from app.core.errors import RuleRejectedError
from app.detect.rules import compile_rule
from app.engine.duckdb import QueryEngine, QueryScope
from app.enrich.geoip import GeoInfo, is_public
from app.enrich.networks import Network, Places, is_internal
from app.meta.db import MetaDB
from app.search import drill

Window = Literal["24h", "7d", "30d"]
TIMEOUT_S = 20.0
TOP = 5
SMALL_MULTIPLES = 6
MAX_IPS = 5000
MAX_MATCHES = 5000
VPN_TEMPLATES = ("paloalto_globalprotect", "openvpn_server")
Lookup = Callable[[list[str]], dict[str, GeoInfo]]
# The window before must have data for this share of its length on every source that
# counts toward a section, or the section shows no changes (owner 2026-10-30).
MIN_COVERAGE = 0.9

_TS = "coalesce(time, time_observed)"
# Entra error codes that interrupt a sign-in rather than refuse it (MFA, register a method,
# stay signed in, an external challenge, seamless SSO): not failures (owner edit 2).
INTERRUPT_CODES = (50072, 50074, 50076, 50079, 50097, 50125, 50140, 50158, 81010, 81012, 81014)
_CODE = "TRY_CAST(TRY(json_extract_string(raw, '$.status.errorCode')) AS INTEGER)"
INTERRUPTED = f"status_id = 2 AND list_contains({list(INTERRUPT_CODES)}, {_CODE})"
FAILED = f"status_id = 2 AND NOT coalesce(list_contains({list(INTERRUPT_CODES)}, {_CODE}), false)"
_WHO = "nullif(trim(actor_user_name), '')"
_HOST = "coalesce(nullif(device_hostname, ''), nullif(dst_endpoint_hostname, ''))"


# Mail rules and forwarding, one definition for the Dashboard and Microsoft 365 > Overview
# (owner, 2026-10-31): on `op`, the operation name in lower case without a trailing
# period. Exchange reports them only through the Management Activity API, so each record
# is one change and is counted as one (the person-and-minute key would merge two rules
# made in the same minute).
MAIL_RULE_OPS = "('new-inboxrule', 'set-inboxrule', 'updateinboxrules')"


def mail_rules(op: str = "op") -> str:
    return f"{op} IN {MAIL_RULE_OPS}"


def forwarding(op: str = "op") -> str:
    return f"{op} = 'set-mailbox' AND raw ILIKE '%Forwarding%'"


MAIL_RULES = mail_rules()
FORWARDING = forwarding()
_EXCHANGE = f"({MAIL_RULES} OR {FORWARDING})"

_CHANGE_KIND = f"""CASE
    WHEN {MAIL_RULES} THEN 'inbox'
    WHEN {FORWARDING} THEN 'inbox'
    WHEN op IN ('add member to role', 'add eligible member to role') THEN 'role'
    WHEN op LIKE '%conditional access policy' THEN 'ca'
  END"""
# The key one change is counted by: D122's, except Exchange records (one each).
_CHANGE_KEY = f"""CASE WHEN {_EXCHANGE} THEN event_id ELSE
    coalesce(metadata_correlation_uid,
             coalesce(lower(actor_user_name), '') || '|' || strftime(ts, '%Y-%m-%d %H:%M'))
  END"""
_M365_AUDIT = "template_id IN ('m365_directory_audit', 'm365_management_activity')"


# The first event of each source back to the start of the window before: a source that
# started inside it cannot be compared with it.
FIRST_EVENT_SQL = f"""
SELECT source_id, min({_TS}) FROM events GROUP BY 1"""  # noqa: S608  # fixed SQL text


INVOLVED_SQL = f"""
SELECT event_id, {_WHO} AS who, {_HOST} AS host FROM events
WHERE list_contains($ids, event_id)"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class Kpi:
    value: int
    before: int | None = None
    extra: int | None = None  # a second number the card states (blocked consents)
    # Search query templates behind the number, the window before, and `extra` (ADR-0039).
    drill: str | None = None
    drill_before: str | None = None  # None: the same query over the window before
    extra_drill: str | None = None


@dataclass(slots=True)
class Series:
    label: str
    counts: list[int]
    level: str | None = None  # a rule's level, for Detections
    drill: str | None = None


@dataclass(slots=True)
class Row:
    label: str
    count: int
    kind: str = ""
    detail: str = ""
    last: str | None = None
    drill: str | None = None  # rows with no entity page open Search (ADR-0039)


@dataclass(slots=True)
class Identity:
    failed: Kpi
    outside: Kpi | None  # None: approved countries not set
    inbox_rules: Kpi
    consents: Kpi
    role_grants: Kpi
    ca_edits: Kpi
    sign_ins: int
    failed_trend: Trend
    top_failing: list[Row]
    history: History = field(default_factory=lambda: History(True))


@dataclass(slots=True)
class History:
    """Whether the window before can be compared: every source that counts toward the
    section has data for at least MIN_COVERAGE of it. `since`: the latest first event
    among those sources, for "sources start Oct 21"."""

    compared: bool
    since: datetime | None = None


@dataclass(slots=True)
class Trend:
    """One line over the window with the window before on the same points: hourly for 24
    hours and 7 days, daily for 30 days (owner 2026-10-30)."""

    points: list[datetime]
    counts: list[int]
    before: list[int]


@dataclass(slots=True)
class Attacks:
    failures: Kpi
    addresses: Kpi
    countries: Kpi | None  # None: no GeoIP file
    vpn_outside: Kpi | None  # None: approved countries not set or no VPN source
    has_vpn: bool
    by_host: list[Series]
    top_sources: list[Row]
    history: History = field(default_factory=lambda: History(True))


@dataclass(slots=True)
class Detections:
    matches: Kpi
    rules_matched: Kpi  # extra: rules enabled
    hosts: Kpi
    users: Kpi
    by_rule: list[Series]
    involved: list[Row]
    history: History = field(default_factory=lambda: History(True))


@dataclass(slots=True)
class Sections:
    window: str
    start: datetime
    end: datetime
    before: datetime  # start of the window before
    buckets: list[datetime]
    approved_set: bool
    has_public: bool
    geoip_date: str | None = None  # when the GeoIP country file was installed
    identity: Identity | None = None
    attacks: Attacks | None = None
    detections: Detections | None = None
    read: list[str] = field(default_factory=list)


def bounds(
    window: Window, now: datetime, tz: str = "UTC"
) -> tuple[datetime, datetime, list[datetime]]:
    """Window start, the start of the window before, and the bucket starts (hours for 24
    hours, the viewer's days otherwise, in UTC; the last bucket holds now)."""
    if window == "24h":
        top = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        buckets = [top - timedelta(hours=23 - i) for i in range(24)]
        start = buckets[0]
        return start, start - timedelta(hours=24), buckets
    days = 7 if window == "7d" else 30
    local = now.astimezone(zone(tz))
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Wall-clock days in the viewer's zone (ZoneInfo gives each its own offset, so a day
    # across a clock change is 23 or 25 hours).
    buckets = [(today - timedelta(days=days - 1 - i)).astimezone(UTC) for i in range(days)]
    start = buckets[0]
    before = (today - timedelta(days=2 * days - 1)).astimezone(UTC)
    return start, before, buckets


def fact_run(run: _Run, sources: list[str], rollup: Any) -> tuple[_Run, bool]:
    """A run over a fact rollup's days for `sources`: closed days wholly in range, and
    today's rows observed by its cutoff (D135); the rest from events. The flag says
    whether any rollup day is read."""
    scope = QueryScope(sources, run.scope.start, run.scope.end)
    covered = rollup.covered(scope) if rollup is not None else []
    part = rollup.today(scope) if rollup is not None else None
    keys = covered + (part[0] if part else [])
    lo = run.scope.start or datetime(1970, 1, 1, tzinfo=UTC)
    hi = run.scope.end or datetime.now(UTC)
    params = {**run.params, "covered": keys, "fact_lo": lo, "fact_hi": hi}
    after = (part[1], part[2]) if part else None
    return _Run(run.engine, run.scope, params, covered, after), bool(keys)


def zone(tz: str) -> ZoneInfo:
    """The viewer's IANA time zone; UTC when it is not one."""
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def trend_points(window: Window, now: datetime, tz: str = "UTC") -> tuple[str, list[datetime]]:
    """The trend's unit and point starts: from the window start to the point holding now."""
    start, _, buckets = bounds(window, now, tz)
    if window != "7d":
        return ("hour" if window == "24h" else "day"), buckets
    top = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hours = int((top - start) / timedelta(hours=1)) + 1
    return "hour", [start + timedelta(hours=i) for i in range(hours)]


def _trend(
    rows: list[list[Any]], points: list[datetime], span: timedelta, tz: str = "UTC"
) -> Trend:
    """Counts per point now and per the same point one window earlier. Day points match
    by the viewer's date, `len(points)` days back: a window across a clock change is an
    hour longer or shorter than the one before, so adding `span` would miss the day."""
    at = {p: i for i, p in enumerate(points)}
    now, before = [0] * len(points), [0] * len(points)
    daily = len(points) > 1 and points[1] - points[0] >= timedelta(hours=23)
    z = zone(tz)
    by_day = {p.astimezone(z).date(): i for i, p in enumerate(points)} if daily else {}
    for b, n in rows:
        t = _utc(b)
        if t is None:
            continue
        if t in at:
            now[at[t]] += int(n)
        elif daily:
            i = by_day.get(t.astimezone(z).date() + timedelta(days=len(points)))
            if i is not None:
                before[i] += int(n)
        elif t + span in at:
            before[at[t + span]] += int(n)
    return Trend(points, now, before)


NOT_ADDRESS = "Not an address"
NOT_PUBLIC = "Not a public address"
NOT_IN_GEOIP = "Not in GeoIP file"
NO_GEOIP = "No GeoIP file"
UNPLACED = (NOT_ADDRESS, NOT_PUBLIC, NOT_IN_GEOIP, NO_GEOIP)


def unplaced(value: str, have_geoip: bool) -> str:
    """Why an address has no country: the value is not an address, the address is not
    public (no country exists), or the GeoIP file does not list it."""
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return NOT_ADDRESS
    if not is_public(addr):
        return NOT_PUBLIC
    return NOT_IN_GEOIP if have_geoip else NO_GEOIP


def _history(
    first: dict[str, datetime], counted: Iterable[str], start: datetime, before: datetime
) -> History:
    """Compared only when each counted source began before (or soon enough into) the
    window before."""
    span = start - before
    firsts = [first[s] for s in counted if s in first]
    if not firsts:
        return History(True)
    latest = max(firsts)
    covered = (start - max(before, latest)) / span if span else 1.0
    return History(covered >= MIN_COVERAGE, latest if latest > before else None)


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


class _Run:
    """Runs fixed SQL on one scope and remembers the sources read."""

    def __init__(
        self,
        engine: QueryEngine,
        scope: QueryScope,
        params: dict[str, Any],
        skip_days: list[str] | None = None,
        after: tuple[list[str], datetime] | None = None,
    ) -> None:
        self.engine, self.scope, self.params = engine, scope, params
        # Days read from a fact rollup (ADR-0041), left out of `events`; and sources whose
        # rows observed by a cutoff today come from the rollup too (D135).
        self.skip = skip_days or []
        self.after = after
        self.read: set[str] = set()
        self._lock = threading.Lock()  # runs may come from several threads

    def events(self, sql: str, sources: list[str]) -> list[list[Any]]:
        """Run on events for every day in scope, rollup days included."""
        return self._go(sql, sources, [], {}, fresh=True)

    def __call__(self, sql: str, sources: list[str], **extra: Any) -> list[list[Any]]:
        return self._go(sql, sources, self.skip, extra)

    def _go(
        self,
        sql: str,
        sources: list[str],
        skip: list[str],
        extra: dict[str, Any],
        fresh: bool = False,
    ) -> list[list[Any]]:
        if not sources:
            return []
        scope = QueryScope(sources=sources, start=self.scope.start, end=self.scope.end)
        # DuckDB takes exactly the parameters a statement names.
        params = {k: v for k, v in {**self.params, **extra}.items() if re.search(rf"\${k}\b", sql)}
        res = self.engine.run(
            sql,
            scope,
            params,
            timeout_s=TIMEOUT_S,
            rollup=bool(skip) or (self.after is not None and not fresh),
            skip_days=skip,
            name="dashboard",
            after=None if fresh else self.after,
        )
        with self._lock:
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


FAILED_SIGNIN = f"template_id = 'm365_signin' AND {FAILED}"
# Failures from addresses outside Internal networks, as the Attacks counts read them.
EXTERNAL_FAILURE = (
    "class_uid = 3002 AND status_id = 2 AND template_id NOT LIKE 'm365_%'\n"
    "  AND nullif(src_endpoint_ip, '') IS NOT NULL AND NOT is_internal(src_endpoint_ip)"
)


def outside_where(templates: list[str], approved: tuple[str, ...]) -> str:
    """Successful sign-ins placed by GeoIP in a country not approved (unplaced: not counted)."""
    return (
        f"list_contains({drill.lits(templates)}, template_id)"
        " AND activity_id IS DISTINCT FROM 2 AND status_id = 1\n"
        f"  AND NOT list_contains({drill.lits(sorted(c.upper() for c in approved))},"
        " ip_country(src_endpoint_ip))"
    )


def changes_drill(kind: str) -> str:
    """One row per change, as CHANGES_SQL counts them, with the events behind each."""
    # Fixed SQL text; the kind is a quoted literal and the page fills the bounds.
    return (
        "WITH r0 AS (\n"  # noqa: S608
        f"  SELECT {_TS} AS ts, lower(rtrim(trim(message), '.')) AS op, raw,\n"
        "         actor_user_name, event_id, metadata_correlation_uid\n"
        f"  FROM events\n  WHERE {_M365_AUDIT}\n),\n"
        f"r AS (SELECT ts, op, raw, actor_user_name AS who, event_id, {_CHANGE_KEY} AS k"
        " FROM r0),\n"
        f"c AS (SELECT *, {_CHANGE_KIND} AS kind FROM r)\n"
        "SELECT min(ts) AS time, any_value(who) AS person, op AS operation,"
        " list(event_id) AS event_ids\n"
        f"FROM c\nWHERE kind = {drill.lit(kind)}\nGROUP BY k, op\n"
        "HAVING min(ts) >= TIMESTAMPTZ '{from}' AND min(ts) < TIMESTAMPTZ '{to}'\n"
        "ORDER BY time DESC"
    )


def _identity(
    run: _Run,
    m365: list[str],
    places: Places,
    geo: Lookup,
    window: Window,
    now: datetime,
    first: dict[str, datetime],
    rollup: Any = None,
    tz: str = "UTC",
) -> Identity:
    """From the Microsoft 365 facts (ADR-0041): closed days from the rollup when it has
    them, the rest from events, with the same definitions as Microsoft 365 > Overview."""
    from app.search import m365 as facts  # m365 builds on this module

    unit, points = trend_points(window, now, tz)
    start, before, _ = bounds(window, now, tz)
    frun, use = fact_run(run, m365, rollup)
    frun.params["tz"] = zone(tz).key
    names = ["signins", "failed_trend", "top_failing", "changes", "consents", "mail"]
    if places.approved_countries:
        names.append("ok_by_ip")
    got = facts.run_facts(frun, m365, names, use, unit=unit)
    with run._lock:
        run.read |= frun.read
    total, _, failed, failed_before, _, _ = (got["signins"] or [[0] * 6])[0]
    trend = _trend(got["failed_trend"], points, start - before, tz)
    top = [
        Row(str(who), int(n), kind="user", last=_iso(last)) for who, n, last in got["top_failing"]
    ]
    outside = None
    if places.approved_countries:
        outside, _ = _outside(got["ok_by_ip"], geo, set(places.approved_countries))
    changes = {str(k): (int(a), int(b)) for k, a, b in got["changes"]}
    granted, granted_before, blocked = (got["consents"] or [[0, 0, 0]])[0][:3]
    # Risky inbox rules, organizing ones apart (D132).
    from app.search.mail_rules import list_sql as mail_rules_list

    risky, risky_before, organizing = (got["mail"] or [[0, 0, 0]])[0]
    if outside is not None:
        outside.drill = drill.events(
            outside_where(["m365_signin"], places.approved_countries), drill.ADDRESS_COLUMNS
        )

    def change(kind: str) -> Kpi:
        return Kpi(*changes.get(kind, (0, 0)), drill=changes_drill(kind))

    return Identity(
        failed=Kpi(
            int(failed),
            int(failed_before),
            drill=drill.events(FAILED_SIGNIN, drill.ADDRESS_COLUMNS),
        ),
        outside=outside,
        inbox_rules=Kpi(
            int(risky),
            int(risky_before),
            int(organizing),
            drill=mail_rules_list("risky"),
            extra_drill=mail_rules_list("class = 'organizing'"),
        ),
        consents=Kpi(
            int(granted),
            int(granted_before),
            int(blocked),
            drill=consents.drill_sql(blocked=False),
            extra_drill=consents.drill_sql(blocked=True),
        ),
        role_grants=change("role"),
        ca_edits=change("ca"),
        sign_ins=int(total),
        failed_trend=trend,
        top_failing=top,
        history=_history(first, m365, start, before),
    )


def _attacks(
    run: _Run,
    auth: list[str],
    vpn: list[str],
    places: Places,
    geo: Lookup,
    buckets: list[datetime],
    first: dict[str, datetime],
    start: datetime,
    before: datetime,
    rollup: Any = None,
) -> Attacks | None:
    """From the auth facts (D135): closed days from the auth rollup when it has them,
    the rest from events."""
    from app.search import auth_facts

    frun, r = fact_run(run, auth + vpn, rollup)

    def fact(name: str, sources: list[str], **extra: Any) -> list[list[Any]]:
        return frun(auth_facts.query(name, r), sources, **extra)

    nets: list[Network] = places.networks()
    try:
        return _attacks_on(fact, auth, vpn, places, geo, buckets, first, start, before, nets)
    finally:
        with run._lock:
            run.read |= frun.read


def _attacks_on(
    fact: Callable[..., list[list[Any]]],
    auth: list[str],
    vpn: list[str],
    places: Places,
    geo: Lookup,
    buckets: list[datetime],
    first: dict[str, datetime],
    start: datetime,
    before: datetime,
    nets: list[Network],
) -> Attacks | None:
    rows = [r for r in fact("fail_by_ip", auth) if not is_internal(str(r[0]), nets)]
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
    for host, b, n in fact("fail_by_host", auth, ips=now_ips):
        t = _utc(b)
        if t is not None and t in at:
            hosts[str(host)][at[t]] += int(n)
    ranked = sorted(hosts.items(), key=lambda kv: (-sum(kv[1]), kv[0]))[:SMALL_MULTIPLES]
    groups: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    keys: dict[tuple[str, str], tuple[str | None, int | None]] = {}
    for ip, now, _ in rows:
        if not int(now):
            continue
        info = found.get(str(ip))
        country = (info.country_name or info.country or "") if info else ""
        network = f"AS{info.asn} {info.org or ''}".strip() if info and info.asn else ""
        key = (country or unplaced(str(ip), bool(found)), network)
        keys[key] = (info.country if info else None, info.asn if info else None)
        g = groups[key]
        g[0] += 1
        g[1] += int(now)
    top = sorted(groups.items(), key=lambda kv: (-kv[1][1], kv[0]))[:TOP]
    counted = {str(r[0]) for r in fact("fail_sources", auth, ips=now_ips)}
    vpn_outside = None
    if vpn and places.approved_countries:
        logins = fact("vpn_by_ip", vpn)
        vpn_outside, _ = _outside(logins, geo, set(places.approved_countries))
    if countries is not None:
        countries.drill = drill.grouped(EXTERNAL_FAILURE, "ip_country(src_endpoint_ip)", "country")
    if vpn_outside is not None:
        vpn_outside.drill = drill.events(
            outside_where(list(VPN_TEMPLATES), places.approved_countries), drill.ADDRESS_COLUMNS
        )

    def place(key: tuple[str, str]) -> str:
        code, asn = keys.get(key, (None, None))
        c = "ip_country(src_endpoint_ip) " + (f"= {drill.lit(code)}" if code else "IS NULL")
        a = "ip_asn(src_endpoint_ip) " + (f"= {asn}" if asn is not None else "IS NULL")
        return drill.events(f"{EXTERNAL_FAILURE}\n  AND {c} AND {a}", drill.ADDRESS_COLUMNS)

    def on_host(host: str) -> str:
        cond = f"{_HOST} IS NULL" if host == "(no host)" else f"{_HOST} = {drill.lit(host)}"
        return drill.events(f"{EXTERNAL_FAILURE}\n  AND {cond}", drill.ADDRESS_COLUMNS)

    return Attacks(
        failures=Kpi(
            sum(int(r[1]) for r in rows),
            sum(int(r[2]) for r in rows),
            drill=drill.events(EXTERNAL_FAILURE, drill.ADDRESS_COLUMNS),
        ),
        addresses=Kpi(
            len(now_ips),
            len(before_ips),
            drill=drill.grouped(EXTERNAL_FAILURE, "src_endpoint_ip", "address"),
        ),
        countries=countries,
        vpn_outside=vpn_outside,
        has_vpn=bool(vpn),
        by_host=[Series(h, counts, drill=on_host(h)) for h, counts in ranked],
        history=_history(first, counted, start, before),
        top_sources=[
            Row(
                country,
                n,
                kind="network",
                detail=f"{network}|{addrs}",
                drill=place((country, network)),
            )
            for (country, network), (addrs, n) in top
        ],
    )


def _matches(
    meta: MetaDB, allowed: list[str] | None, start: datetime, before: datetime
) -> tuple[list[tuple[str, str, str, datetime | None, str, str]], int]:
    """(rule title, level, event id, event time, source, rule version) of matches since
    the window before, one per rule and event, on readable sources; and how many rules
    are enabled."""
    with meta.connect() as con:
        rows = con.execute(
            "SELECT v.rule_id, v.title, v.level, m.event_id, m.event_time, m.source_id, v.sha256"
            " FROM rule_matches m JOIN rule_runs r ON r.run_id = m.run_id"
            " JOIN rule_versions v ON v.sha256 = r.sha256"
            " WHERE m.event_time >= ? ORDER BY m.rowid DESC LIMIT ?",
            (before.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"), MAX_MATCHES * 4),
        ).fetchall()
        enabled = con.execute("SELECT count(*) FROM rules WHERE enabled = 1").fetchone()[0]
    permitted = None if allowed is None else set(allowed)
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str, datetime | None, str, str]] = []
    for r in rows:
        if permitted is not None and r["source_id"] not in permitted:
            continue
        key = (str(r["rule_id"]), str(r["event_id"]))
        if key in seen:
            continue
        seen.add(key)
        when = _utc(datetime.fromisoformat(r["event_time"])) if r["event_time"] else None
        out.append(
            (
                str(r["title"]),
                str(r["level"]).lower(),
                str(r["event_id"]),
                when,
                str(r["source_id"]),
                str(r["sha256"]),
            )
        )
    return out[:MAX_MATCHES], int(enabled)


_CONDITIONS: dict[str, str] = {}


def rule_conditions(meta: MetaDB, shas: set[str]) -> dict[str, str]:
    """Each rule version's WHERE condition on events, compiled once per process."""
    missing = [s for s in shas if s not in _CONDITIONS]
    if missing:
        with meta.connect() as con:
            marks = ", ".join("?" for _ in missing)
            found = con.execute(
                f"SELECT sha256, yaml FROM rule_versions WHERE sha256 IN ({marks})",  # noqa: S608  # placeholders only
                missing,
            ).fetchall()
        for sha, text in found:
            try:
                _CONDITIONS[str(sha)] = compile_rule(str(text).encode()).condition
            except RuleRejectedError:
                _CONDITIONS[str(sha)] = ""
    return {s: _CONDITIONS[s] for s in shas if _CONDITIONS.get(s)}


def _detections(
    run: _Run,
    meta: MetaDB,
    allowed: list[str] | None,
    readable: list[str],
    start: datetime,
    before: datetime,
    buckets: list[datetime],
    window: Window,
    first: dict[str, datetime],
) -> Detections | None:
    matches, enabled = _matches(meta, allowed, start, before)
    if not enabled and not matches:
        return None
    now = [m for m in matches if m[3] is not None and m[3] >= start]
    prior = [m for m in matches if m[3] is not None and m[3] < start]
    step = timedelta(hours=1) if window == "24h" else timedelta(days=1)
    by_rule: dict[str, list[int]] = defaultdict(lambda: [0] * len(buckets))
    levels: dict[str, str] = {}
    for title, level, _, when, _, _ in now:
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
    for _, _, eid, _, _, _ in now:
        who, host = per_event.get(eid, (None, None))
        if host:
            hosts[str(host)] += 1
        if who:
            users[str(who)] += 1
    involved = [Row(h, n, kind="host") for h, n in hosts.most_common(TOP)]
    involved += [Row(u, n, kind="user") for u, n in users.most_common(TOP)]
    involved.sort(key=lambda r: (-r.count, r.kind, r.label))
    shas = {m[0]: m[5] for m in matches}
    conds = rule_conditions(meta, set(shas.values()))

    def where(ms: list[tuple[str, str, str, datetime | None, str, str]]) -> str:
        """The matched rules' conditions; event ids when they do not fit in Search."""
        joined = drill.any_of(conds.get(m[5], "") for m in ms)
        if joined is not None:
            return joined
        newest = sorted(ms, key=lambda m: m[3] or start, reverse=True)[:300]
        return f"list_contains({drill.lits(sorted({m[2] for m in newest}))}, event_id)"

    now_where, prior_where = where(now), where(prior)

    def matches_kpi(value: int, before_value: int, extra: int | None = None) -> Kpi:
        return Kpi(
            value,
            before_value,
            extra,
            drill=drill.events(now_where),
            drill_before=drill.events(prior_where) if prior_where != now_where else None,
        )

    def on_rule(title: str) -> str | None:
        cond = conds.get(shas.get(title, ""))
        return drill.events(cond) if cond else None

    return Detections(
        matches=matches_kpi(len(now), len(prior)),
        rules_matched=matches_kpi(
            len({m[0] for m in now}), len({m[0] for m in prior}), extra=enabled
        ),
        hosts=Kpi(len(hosts), drill=drill.grouped(now_where, _HOST, "host")),
        users=Kpi(len(users), drill=drill.grouped(now_where, _WHO, "person")),
        by_rule=[Series(t, c, level=levels.get(t), drill=on_rule(t)) for t, c in ranked],
        involved=involved[: TOP * 2],
        history=_history(first, {m[4] for m in now}, start, before),
    )


PARTS = ("identity", "attacks", "detections")


def first_events(run: _Run, sources: list[str]) -> dict[str, datetime]:
    """When each source's data starts in scope, from file statistics (no rows read):
    only "did it start inside the window before" depends on it."""
    scope = QueryScope(sources, run.scope.start, run.scope.end)
    found = run.engine.first_times(scope)
    with run._lock:
        run.read |= set(found)
    return found


def sections(
    engine: QueryEngine,
    meta: MetaDB,
    allowed: list[str] | None,
    sources: list[tuple[str, str, str | None]],
    places: Places,
    geo: Lookup,
    window: Window,
    now: datetime,
    m365_rollup: Any = None,
    parts: Collection[str] = PARTS,
    tz: str = "UTC",
    auth_rollup: Any = None,
) -> Sections:
    """The sections for the caller (`parts`: any of identity, attacks, detections; each
    loads on its own). `sources` is the install's (id, kind, template); only those the
    caller may read are used."""
    start, before, buckets = bounds(window, now, tz)
    mine = [s for s in sources if allowed is None or s[0] in set(allowed)]
    m365 = [sid for sid, kind, tpl in mine if kind == "m365" or (tpl or "").startswith("m365_")]
    vpn = [sid for sid, _, tpl in mine if tpl in VPN_TEMPLATES]
    other = [sid for sid, _, _ in mine if sid not in set(m365)]
    unit = "hour" if window == "24h" else "day"
    run = _Run(
        engine,
        QueryScope(sources=None, start=before, end=now),
        {"start": start, "unit": unit, "tz": zone(tz).key},
    )
    out = Sections(
        window=window,
        start=start,
        end=now,
        before=before,
        buckets=buckets,
        approved_set=bool(places.approved_countries),
        has_public=places.has_public,
    )
    first = first_events(run, [s[0] for s in mine])
    if m365 and "identity" in parts:
        out.identity = _identity(run, m365, places, geo, window, now, first, m365_rollup, tz)
    if "attacks" in parts:
        out.attacks = _attacks(
            run, other, vpn, places, geo, buckets, first, start, before, auth_rollup
        )
    if "detections" in parts:
        out.detections = _detections(
            run, meta, allowed, [s[0] for s in mine], start, before, buckets, window, first
        )
    out.read = sorted(run.read)
    return out
