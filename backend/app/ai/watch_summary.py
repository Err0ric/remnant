"""AI Watch at the top of the Dashboard (ADR-0035 rows 10, 12, 13): five cards, AI use
over 30 days by review status, and the top services.

Everything is computed on the caller's view: the use rows come from the per-session
`events` and `ai_rollup` views (rule 13), the review items are counted only when the viewer
may read their sources, and the Microsoft 365 and telemetry counts read only the sources of
those kinds the viewer may read. A card whose data needs a source the install does not have
says which; one the viewer may not read says Restricted. No model is called.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.ai import consents
from app.ai import usage as usage_mod
from app.ai.agents import agents
from app.ai.agents import masked as masked_agents
from app.ai.catalog import NON_USAGE, Catalog, Service
from app.ai.usage import Usage
from app.alerts.items import AlertItem
from app.core.timing import in_context
from app.engine.duckdb import QueryEngine, QueryScope
from app.search.dashboard import zone

CHART_DAYS = 30
TOP = 10
TIMEOUT_S = 20.0

# Claude Code sensitive-data signals, now and in the period before. Only the telemetry
# sources are read, never the whole lake. Consents are counted in `consents`.
SIGNALS_SQL = """
WITH e AS (
  SELECT coalesce(time, time_observed) AS ts, nullif(actor_user_name, '') AS who,
         TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) AS sens,
         nullif(device_hostname, '') AS machine
  FROM events
  WHERE template_id = 'claude_code_otel'
)
SELECT
  coalesce(sum(sens) FILTER (WHERE ts >= $start), 0),
  coalesce(sum(sens) FILTER (WHERE ts < $start), 0),
  arg_max(struct_pack(who := who, machine := machine), sens)
    FILTER (WHERE sens > 0 AND ts >= $start AND who IS NOT NULL)
FROM e"""


# The events behind the sensitive data card (ADR-0039), one row per event that reported any.
SENSITIVE_DRILL = (
    "SELECT time, actor_user_name AS person, device_hostname,\n"
    "       TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT)"
    " AS sensitive, message, event_id\n"
    "FROM events\nWHERE template_id = 'claude_code_otel'\n"
    "  AND TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) > 0\n"
    "  AND coalesce(time, time_observed) >= TIMESTAMPTZ '{from}'"
    " AND coalesce(time, time_observed) < TIMESTAMPTZ '{to}'\n"
    "ORDER BY coalesce(time, time_observed) DESC"
)


class _Use:
    """One service's use in the period, from the daily rows."""

    def __init__(self) -> None:
        self.people: set[str] = set()
        self.machines: set[str] = set()
        self.events = 0
        self.first: datetime | None = None
        self.last: datetime | None = None

    def add(self, who: Any, machine: Any, events: Any, first: datetime | None,
            last: datetime | None) -> None:  # fmt: skip
        if who:
            self.people.add(str(who))
        if machine:
            self.machines.add(str(machine))
        self.events += int(events or 0)
        if first is not None and (self.first is None or first < self.first):
            self.first = first
        if last is not None and (self.last is None or last > self.last):
            self.last = last


@dataclass(slots=True)
class Card:
    key: str
    label: str
    value: int | None  # None when the card cannot be counted (needs, restricted)
    previous: int | None
    context: str = ""
    needs: str | None = None  # "a Microsoft 365 source": the install has none
    restricted: bool = False  # the install has the source, the viewer may not read it
    # Devices or addresses with no person matched to them, never added to `value`
    # (people card only): "3 more devices not matched to a person".
    devices: int | None = None
    # Consent card: attempts a policy blocked, never added to `value`, and the newest.
    # Services not yet approved (D184): those still not reviewed (open or closed alerts
    # list) and those marked Not approved, counted apart. Unreviewed is not a violation.
    unreviewed: int | None = None
    not_approved: int | None = None
    blocked: int | None = None
    blocked_context: str = ""
    # Search SQL for the rows behind the card and behind `blocked` (consent card).
    rows_sql: str | None = None
    blocked_sql: str | None = None
    # Drill-through templates with `{from}` and `{to}` (ADR-0039): the number, the period
    # before when it needs another query, and the devices line.
    drill: str | None = None
    drill_before: str | None = None
    devices_drill: str | None = None
    blocked_drill: str | None = None


class _Users:
    """People, and devices seen without a person, kept apart."""

    def __init__(self) -> None:
        self.people: set[str] = set()
        self.matched: set[str] = set()  # devices seen with a person
        self.devices: set[str] = set()

    def add(self, who: Any, machine: Any) -> None:
        if who:
            self.people.add(str(who))
            if machine:
                self.matched.add(str(machine))
        elif machine:
            self.devices.add(str(machine))

    def unmatched(self) -> int:
        return len(self.devices - self.matched)


@dataclass(slots=True)
class Day:
    day: str  # YYYY-MM-DD (UTC)
    approved: int
    unreviewed: int
    not_approved: int


@dataclass(slots=True)
class TopService:
    service_id: str
    name: str
    status: str
    people: int
    machines: int
    events: int
    first_seen: str | None
    last_seen: str | None


@dataclass(slots=True)
class Summary:
    days: int
    start: str
    end: str
    cards: list[Card]
    chart: list[Day]
    top: list[TopService]
    sources: list[str] = field(default_factory=list)
    new: list[NewThing] = field(default_factory=list)
    # False while AI use was seen for less than 90% of the period before (owner
    # 2026-10-30): the cards then show no change. `since`: the first use seen.
    compared: bool = True
    since: str | None = None
    # AI services with any use in the period, of every review status (the Dashboard's
    # "AI services in use"; `top` is only the first few).
    services_in_use: int = 0
    before: str = ""  # start of the period before
    chart_drill: str | None = None  # AI use per service for one chart day (`{from}`, `{to}`)
    names: bool = False  # whether any text names a person: audited as such (G3)


@dataclass(slots=True)
class NewThing:
    """First seen in the last 24 hours (ADR-0037 row 6), by when its use first appears in
    the data, never by when an item was raised or a decision made (owner, 2026-10-23)."""

    kind: str  # service | mcp | agent
    id: str
    name: str
    first_seen: str
    item_id: str | None  # its AI Watch item, when the viewer can read one


def _iso(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _day(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def summary(
    usage: Usage,
    catalog: Catalog,
    engine: QueryEngine,
    allowed: list[str] | None,
    items: list[AlertItem],
    readable: Callable[[AlertItem], bool],
    kinds: dict[str, list[str]],
    now: datetime,
    days: int,
    tz: str = "UTC",
    named: bool = True,
) -> Summary:
    """`allowed` is the viewer's sources (None: all); `items` the AI Watch items they may
    see (readable or not); `kinds` the install's sources by class (`source_classes`),
    to tell "needs a source" from "restricted". Without `named` (no View people in AI
    usage, D242) the cards' text and the new agents show machines, never names."""
    now = now.astimezone(UTC)
    where = zone(tz)
    today = now.astimezone(where).date()

    def midnight(d: date) -> datetime:
        """The start of the viewer's day `d`, in UTC (owner, 2026-10-31)."""
        return datetime.combine(d, datetime.min.time(), where).astimezone(UTC)

    cur_from = today - timedelta(days=days - 1)  # whole days in the viewer's zone, today too
    prev_from = cur_from - timedelta(days=days)
    if days == 1:  # "24 hours" is a rolling 24 hours ending now, not since midnight (D221)
        cur_start, prev_start = now - ROLLING, now - 2 * ROLLING
    else:
        cur_start, prev_start = midnight(cur_from), midnight(prev_from)
    start = min(prev_start, midnight(today - timedelta(days=CHART_DAYS - 1)))
    services = {s.id: s for s in catalog.services()}
    # The signal cards read other sources: run them beside the daily use, not after it.
    pool = ThreadPoolExecutor(max_workers=1)
    signals_job = pool.submit(
        in_context(_signal_cards),
        engine,
        allowed,
        kinds,
        cur_start,
        prev_start,
        now,
        named,
    )
    try:
        rows, read = usage.daily(QueryScope(allowed, start, now), where.key, cur_start, prev_start)
        signals, read_signals, signal_names = signals_job.result()
    finally:
        pool.shutdown(wait=False)

    def is_use(sid: str) -> bool:
        s = services.get(sid)
        return s is not None and s.kind != NON_USAGE

    def status(sid: str) -> str:
        return services[sid].status

    cur_svcs: set[str] = set()
    prev_svcs: set[str] = set()
    # People and devices are counted apart (owner, 2026-10-22): a device counts only when
    # no event of the period names its person.
    cur = _Users()
    prev = _Users()
    # People this period on a service of each status (a person can be on both).
    people_by_status: dict[str, set[str]] = defaultdict(set)
    chart: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # The top services and the first-seen times come from these same rows: one query of
    # events for the whole section (F63).
    use: dict[str, _Use] = {}
    first_in_rows: dict[str, datetime] = {}
    chart_svcs: set[str] = set()
    for sid, who, machine, day_v, events, last, first, period in rows:
        if not is_use(sid):
            continue
        d = _day(day_v)
        st = status(sid)
        f = _ts(first)
        if f is not None and (sid not in first_in_rows or f < first_in_rows[sid]):
            first_in_rows[sid] = f
        if period == 2:
            use.setdefault(sid, _Use()).add(who, machine, events, f, _ts(last))
        if d >= today - timedelta(days=CHART_DAYS - 1):
            chart[d][st] += int(events)
            chart_svcs.add(sid)
        unapproved = st != "approved"
        if period == 2:
            if unapproved:
                cur_svcs.add(sid)
                cur.add(who, machine)
                if who:
                    people_by_status[st].add(str(who))
        elif period == 1 and unapproved:
            prev_svcs.add(sid)
            prev.add(who, machine)

    table = catalog.domain_table()

    unapproved_ids = cur_svcs | prev_svcs

    def use_drill(ids: set[str], kind: str) -> str | None:
        return usage_mod.drill_sql(table, ids, kind) if ids else None

    # Not yet approved = Not approved + Unreviewed, said apart (owner, 2026-11-03: the
    # card read "Unapproved" over 0 Not approved and 776 Unreviewed; D184).
    not_reviewed = sum(1 for s in cur_svcs if status(s) == "unreviewed")
    refused = sum(1 for s in cur_svcs if status(s) == "not_approved")
    cards = [
        Card(
            "services",
            "AI services not yet approved",
            len(cur_svcs),
            len(prev_svcs),
            f"{refused} not approved, {not_reviewed} unreviewed" if cur_svcs else "None in use",
            unreviewed=not_reviewed,
            not_approved=refused,
            drill=use_drill(unapproved_ids, "services"),
        ),
        Card(
            "people",
            "People using AI not yet approved",
            len(cur.people),
            len(prev.people),
            f"{len(people_by_status['not_approved'])} on not approved,"
            f" {len(people_by_status['unreviewed'])} on unreviewed"
            if cur.people
            else "",
            devices=cur.unmatched(),
            drill=use_drill(unapproved_ids, "people"),
            devices_drill=use_drill(unapproved_ids, "devices"),
        ),
    ]
    cards.extend(signals)

    chart_days = [
        Day(
            (today - timedelta(days=i)).isoformat(),
            chart[today - timedelta(days=i)]["approved"],
            chart[today - timedelta(days=i)]["unreviewed"],
            chart[today - timedelta(days=i)]["not_approved"],
        )
        for i in range(CHART_DAYS - 1, -1, -1)
    ]
    # First seen is the earliest event ever: the window's rows or, earlier, the rollup's
    # first-seen index (owner 2026-10-29), never just the start of the window.
    index = usage.first_seen(allowed)
    firsts, shown_ids, owned = _firsts(
        usage, engine, allowed, items, readable, now, prev_start, first_in_rows, services, index,
        named,
    )  # fmt: skip
    cards.insert(2, _agents_card(firsts, items, readable, cur_start, prev_start, kinds, allowed))

    def first_ever(sid: str, seen: datetime | None) -> datetime | None:
        found = [t for t in (seen, first_in_rows.get(sid), index.get(f"service:{sid}")) if t]
        return min(found) if found else None

    ranked = sorted(
        use.items(), key=lambda p: (-len(p[1].people), -p[1].events, services[p[0]].name)
    )
    top = [
        TopService(
            sid,
            services[sid].name,
            services[sid].status,
            len(u.people),
            len(u.machines),
            u.events,
            _iso(first_ever(sid, u.first)),
            _iso(u.last),
        )
        for sid, u in ranked[:TOP]
    ]
    new = [n for n in firsts if n.first_seen >= (now - NEW_WINDOW).isoformat()]
    oldest = min(first_in_rows.values(), default=None)
    compared = oldest is None or (cur_start - max(prev_start, oldest)) >= 0.9 * (
        cur_start - prev_start
    )
    return Summary(
        days,
        cur_start.isoformat(),
        now.isoformat(),
        cards,
        chart_days,
        top,
        sorted(set(read) | set(read_signals)),
        [replace(n, id=shown_ids[n.id]) if n.id in shown_ids else n for n in new],
        compared=compared,
        since=oldest.isoformat() if oldest is not None and oldest > prev_start else None,
        before=prev_start.isoformat(),
        chart_drill=use_drill(set(use) | chart_svcs, "services"),
        services_in_use=len(use),
        names=signal_names or any(n.kind == "agent" and n.id in owned for n in new),
    )


NEW_WINDOW = timedelta(hours=24)
ROLLING = timedelta(hours=24)
HISTORY = timedelta(days=30)  # telemetry read for MCP servers and agents; older days: index


def _ts(v: Any) -> datetime | None:
    if v is None:
        return None
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace(" ", "T", 1))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _firsts(
    usage: Usage,
    engine: QueryEngine,
    allowed: list[str] | None,
    items: list[AlertItem],
    readable: Callable[[AlertItem], bool],
    now: datetime,
    since: datetime,
    services_first: dict[str, datetime],
    known: dict[str, Service],
    index: dict[str, datetime],
    named: bool = True,
) -> tuple[list[NewThing], dict[str, str], set[str]]:
    """Services, MCP servers, and agents first seen from `since` on: never seen before in
    the rows of the summary's window, nor in any closed day the rollup's first-seen index
    has (D116, F63). MCP servers and agents are read from telemetry, which is small;
    services come from the summary's own rows, so this reads no further events for them.
    "New in 24 hours" and the new agents card are both cut from this list. Without `named`,
    agents carry their masked label, and the masked key of each agent is returned apart
    (by its own key, which can hold a name), so the items still match by the real key; and
    the agents whose label names their owners."""
    cutoff = since
    scope = QueryScope(allowed, min(now - HISTORY, since), now)
    item_of: dict[str, str] = {}
    for i in sorted(items, key=lambda i: i.created_at):
        if readable(i):
            item_of[i.subject] = i.item_id

    def first_of(key: str, seen: datetime | None) -> datetime | None:
        earlier = index.get(key)
        if seen is None or (earlier is not None and earlier < seen):
            return earlier
        return seen

    out: list[NewThing] = []
    for sid, seen in services_first.items():
        first = first_of(f"service:{sid}", seen)
        if first is not None and first >= cutoff and sid in known:
            out.append(
                NewThing(
                    "service",
                    sid,
                    known[sid].name,
                    first.isoformat(),
                    item_of.get(f"service:{sid}"),
                )
            )
    for m in usage.mcp(scope):
        first = first_of(f"mcp:{m.name}", _ts(m.first_seen))
        if first is not None and first >= cutoff:
            out.append(
                NewThing("mcp", m.name, m.name, first.isoformat(), item_of.get(f"mcp:{m.name}"))
            )
    found = agents(engine, allowed, now)
    pairs = [(a, a) for a in found] if named else masked_agents(found)
    shown_ids = {} if named else {orig.agent: a.agent for a, orig in pairs}
    owned = {a.agent for shown, a in pairs if shown.owners}
    for shown, a in pairs:
        first = first_of(f"agent:{a.agent}", _ts(a.first_seen))
        if first is not None and first >= cutoff:
            out.append(
                NewThing(
                    "agent",
                    a.agent,
                    shown.label,
                    first.isoformat(),
                    item_of.get(f"agent:{a.agent}"),
                )
            )
    return sorted(out, key=lambda n: n.first_seen, reverse=True), shown_ids, owned


TELEMETRY_TEMPLATES = frozenset({"claude_code_otel", "mcp_inventory"})


def source_classes(sources: list[tuple[str, str, str | None]]) -> dict[str, list[str]]:
    """Which sources can carry what the cards count, from (id, kind, template): telemetry
    (an OpenTelemetry receiver, or a file read with the Claude Code or MCP inventory
    template) and Microsoft 365 (the connector, or a file with an M365 template)."""
    out: dict[str, list[str]] = {"telemetry": [], "m365": []}
    for sid, kind, template in sources:
        if kind == "otlp" or template in TELEMETRY_TEMPLATES:
            out["telemetry"].append(sid)
        if kind == "m365" or (template or "").startswith("m365_"):
            out["m365"].append(sid)
    return out


def _readable_kind(
    kinds: dict[str, list[str]], allowed: list[str] | None, wanted: set[str]
) -> tuple[list[str], bool]:
    """The viewer's sources of these classes, and whether the install has any at all."""
    have = sorted({s for k in wanted for s in kinds.get(k, [])})
    mine = have if allowed is None else [s for s in have if s in set(allowed)]
    return mine, bool(have)


def _agents_card(
    firsts: list[NewThing],
    items: list[AlertItem],
    readable: Callable[[AlertItem], bool],
    cur_start: datetime,
    prev_start: datetime,
    kinds: dict[str, list[str]],
    allowed: list[str] | None,
) -> Card:
    """Agents and MCP servers first seen in the window and in the one before, never the
    alerts raised for them (owner, 2026-11-08; D116)."""
    mine, have = _readable_kind(kinds, allowed, {"telemetry"})
    label = "New agents and MCP servers"
    if not have:
        return Card("agents", label, None, None, needs="Claude Code telemetry or the MCP inventory")
    if not mine:
        return Card("agents", label, None, None, restricted=True)
    refused = {i.subject for i in items if readable(i) and i.why == "Not approved"}
    cur = prev = unapproved = 0
    for n in firsts:
        if n.kind == "service":
            continue
        seen = _ts(n.first_seen)
        if seen is None:
            continue
        if seen >= cur_start:
            cur += 1
            unapproved += f"{n.kind}:{n.id}" in refused
        elif seen >= prev_start:
            prev += 1
    return Card("agents", label, cur, prev, f"{unapproved} not approved" if cur else "None new")


def _signal_cards(
    engine: QueryEngine,
    allowed: list[str] | None,
    kinds: dict[str, list[str]],
    start: datetime,
    before: datetime,
    now: datetime,
    named: bool = True,
) -> tuple[list[Card], list[str], bool]:
    """The consent and sensitive data cards, the sources read, and whether their text names
    a person."""
    m365, have_m365 = _readable_kind(kinds, allowed, {"m365"})
    tel, have_tel = _readable_kind(kinds, allowed, {"telemetry"})
    consent_label, sens_label = "App consent grants", "Sensitive data to AI"
    sources: set[str] = set()
    names = False
    if not have_m365:
        consent = Card("consent", consent_label, None, None, needs="a Microsoft 365 source")
    elif not m365:
        consent = Card("consent", consent_label, None, None, restricted=True)
    else:
        res = engine.run(
            consents.COUNTS_SQL, QueryScope(m365, before, now), {"start": start},
            timeout_s=TIMEOUT_S, page=True,
        )  # fmt: skip
        sources.update(res.sources)
        granted, prev, blocked, latest, latest_blocked = (
            res.rows[0] if res.rows else (0, 0, 0, None, None)
        )
        names = named and any(
            isinstance(x, dict) and x.get("who")
            for x in (latest if granted else None, latest_blocked if blocked else None)
        )
        consent = Card(
            "consent",
            consent_label,
            int(granted or 0),
            int(prev or 0),
            f"Latest: {consents.describe(latest, named)}" if granted else "None granted",
            blocked=int(blocked or 0),
            blocked_context=f"Blocked: {consents.describe(latest_blocked, named)}"
            if blocked
            else "",
            rows_sql=consents.rows_sql(False, start),
            blocked_sql=consents.rows_sql(True, start),
            drill=consents.drill_sql(blocked=False),
            blocked_drill=consents.drill_sql(blocked=True),
        )
    if not have_tel:
        sens = Card("sensitive", sens_label, None, None, needs="Claude Code telemetry")
    elif not tel:
        sens = Card("sensitive", sens_label, None, None, restricted=True)
    else:
        res = engine.run(
            SIGNALS_SQL,
            QueryScope(tel, before, now),
            {"start": start},
            timeout_s=TIMEOUT_S,
            page=True,
        )
        sources.update(res.sources)
        s_cur, s_prev, s_top = res.rows[0] if res.rows else (0, 0, None)
        top = s_top if isinstance(s_top, dict) else {}
        # The person who sent the most, or without `named` their machine (D242), else
        # the clause is left out.
        most = top.get("who") if named else top.get("machine")
        names = names or (named and bool(most))
        sens = Card(
            "sensitive",
            sens_label,
            int(s_cur or 0),
            int(s_prev or 0),
            f"Most from {most}" if most else "" if top else "None in Claude Code",
            drill=SENSITIVE_DRILL,
        )
    return [consent, sens], sorted(sources), names
