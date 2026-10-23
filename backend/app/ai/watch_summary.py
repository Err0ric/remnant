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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.ai.catalog import NON_USAGE, Catalog
from app.ai.usage import Usage
from app.alerts.items import AlertItem
from app.engine.duckdb import QueryEngine, QueryScope

CHART_DAYS = 30
TOP = 10
TIMEOUT_S = 20.0

# Microsoft 365 app consents and Claude Code sensitive-data signals, now and in the period
# before. Only the M365 and telemetry sources are read, never the whole lake.
SIGNALS_SQL = """
WITH e AS (
  SELECT coalesce(time, time_observed) AS ts, template_id, message,
         nullif(actor_user_name, '') AS who,
         TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) AS sens
  FROM events
  WHERE template_id IN ('m365_directory_audit', 'm365_management_activity', 'claude_code_otel')
)
SELECT
  count(*) FILTER (WHERE template_id <> 'claude_code_otel'
    AND message ILIKE 'Consent to application%' AND ts >= $start),
  count(*) FILTER (WHERE template_id <> 'claude_code_otel'
    AND message ILIKE 'Consent to application%' AND ts < $start),
  arg_max(who, ts) FILTER (WHERE template_id <> 'claude_code_otel'
    AND message ILIKE 'Consent to application%' AND ts >= $start),
  coalesce(sum(sens) FILTER (WHERE template_id = 'claude_code_otel' AND ts >= $start), 0),
  coalesce(sum(sens) FILTER (WHERE template_id = 'claude_code_otel' AND ts < $start), 0),
  arg_max(who, sens) FILTER (WHERE template_id = 'claude_code_otel' AND sens > 0
    AND ts >= $start)
FROM e"""


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
) -> Summary:
    """`allowed` is the viewer's sources (None: all); `items` the AI Watch items they may
    see (readable or not); `kinds` the install's sources by class (`source_classes`),
    to tell "needs a source" from "restricted"."""
    now = now.astimezone(UTC)
    today = now.date()
    cur_from = today - timedelta(days=days - 1)  # whole UTC days, today included
    prev_from = cur_from - timedelta(days=days)
    window_from = min(prev_from, today - timedelta(days=CHART_DAYS - 1))
    start = datetime.combine(window_from, datetime.min.time(), UTC)
    services = {s.id: s for s in catalog.services()}
    rows, read = usage.daily(QueryScope(allowed, start, now))

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
    people_by_svc: dict[str, set[str]] = defaultdict(set)
    chart: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for sid, who, machine, day_v, events, _last, _first in rows:
        if not is_use(sid):
            continue
        d = _day(day_v)
        st = status(sid)
        if d >= today - timedelta(days=CHART_DAYS - 1):
            chart[d][st] += int(events)
        unapproved = st != "approved"
        if d >= cur_from:
            if unapproved:
                cur_svcs.add(sid)
                cur.add(who, machine)
                if who:
                    people_by_svc[sid].add(str(who))
        elif d >= prev_from and unapproved:
            prev_svcs.add(sid)
            prev.add(who, machine)

    top_unapproved = sorted(cur_svcs, key=lambda s: (-len(people_by_svc[s]), s))
    lead = top_unapproved[0] if top_unapproved else None
    not_reviewed = sum(1 for s in cur_svcs if status(s) == "unreviewed")
    cards = [
        Card(
            "services",
            "Unapproved AI services",
            len(cur_svcs),
            len(prev_svcs),
            (
                f"{services[lead].name} most used"
                + (f"; {not_reviewed} not reviewed yet" if not_reviewed else "")
            )
            if lead
            else "None in use",
        ),
        Card(
            "people",
            "People using unapproved AI",
            len(cur.people),
            len(prev.people),
            f"{len(people_by_svc[lead])} on {services[lead].name}"
            if lead and people_by_svc[lead]
            else "",
            devices=cur.unmatched(),
        ),
        _agents_card(items, readable, cur_from, prev_from, kinds, allowed),
    ]
    signals, read_signals = _signal_cards(engine, allowed, kinds, cur_from, prev_from, now)
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
    cur_scope = QueryScope(allowed, datetime.combine(cur_from, datetime.min.time(), UTC), now)
    found, read_top = usage.services(cur_scope)
    found.sort(key=lambda u: (-u.people, -u.events, u.service.name))
    top = [
        TopService(
            u.service.id,
            u.service.name,
            u.service.status,
            u.people,
            u.machines,
            u.events,
            _iso(u.first_seen),
            _iso(u.last_seen),
        )
        for u in found[:TOP]
    ]
    return Summary(
        days,
        datetime.combine(cur_from, datetime.min.time(), UTC).isoformat(),
        now.isoformat(),
        cards,
        chart_days,
        top,
        sorted(set(read) | set(read_top) | set(read_signals)),
    )


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
    items: list[AlertItem],
    readable: Callable[[AlertItem], bool],
    cur_from: date,
    prev_from: date,
    kinds: dict[str, list[str]],
    allowed: list[str] | None,
) -> Card:
    mine, have = _readable_kind(kinds, allowed, {"telemetry"})
    label = "New agents and MCP servers"
    if not have:
        return Card("agents", label, None, None, needs="Claude Code telemetry or the MCP inventory")
    if not mine:
        return Card("agents", label, None, None, restricted=True)
    cur = prev = 0
    unapproved = 0
    for i in items:
        if not (i.subject.startswith(("agent:", "mcp:")) and readable(i)):
            continue
        made = _day(i.created_at)
        if made >= cur_from:
            cur += 1
            unapproved += i.why == "Not approved"
        elif made >= prev_from:
            prev += 1
    return Card("agents", label, cur, prev, f"{unapproved} not approved" if cur else "None new")


def _signal_cards(
    engine: QueryEngine,
    allowed: list[str] | None,
    kinds: dict[str, list[str]],
    cur_from: date,
    prev_from: date,
    now: datetime,
) -> tuple[list[Card], list[str]]:
    m365, have_m365 = _readable_kind(kinds, allowed, {"m365"})
    tel, have_tel = _readable_kind(kinds, allowed, {"telemetry"})
    consent_label, sens_label = "App consent grants", "Sensitive data to AI"
    values: list[Any] = [0, 0, None, 0, 0, None]
    read = sorted(set(m365) | set(tel))
    sources: list[str] = []
    if read:
        start = datetime.combine(cur_from, datetime.min.time(), UTC)
        scope = QueryScope(read, datetime.combine(prev_from, datetime.min.time(), UTC), now)
        res = engine.run(SIGNALS_SQL, scope, {"start": start}, timeout_s=TIMEOUT_S)
        if res.rows:
            values = list(res.rows[0])
        sources = list(res.sources)
    c_cur, c_prev, c_who, s_cur, s_prev, s_who = values
    if not have_m365:
        consent = Card("consent", consent_label, None, None, needs="a Microsoft 365 source")
    elif not m365:
        consent = Card("consent", consent_label, None, None, restricted=True)
    else:
        consent = Card(
            "consent",
            consent_label,
            int(c_cur or 0),
            int(c_prev or 0),
            f"Latest by {c_who}" if c_who else "None granted",
        )
    if not have_tel:
        sens = Card("sensitive", sens_label, None, None, needs="Claude Code telemetry")
    elif not tel:
        sens = Card("sensitive", sens_label, None, None, restricted=True)
    else:
        sens = Card(
            "sensitive",
            sens_label,
            int(s_cur or 0),
            int(s_prev or 0),
            f"Most from {s_who}" if s_who else "None in Claude Code",
        )
    return [consent, sens], sources
