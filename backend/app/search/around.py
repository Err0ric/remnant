"""Around this event (ADR-0038 section 8, rows 23 to 26): the rows from every source the
caller may read within 5 minutes either side of an event, by the same person or the same
device, at most 50, newest last.

The person and device come from the event's own columns and, when it names no person, from
the spans that held its source address then (ADR-0029), so a proxy row with only an
address joins the person. `Likely cause` is a hint, never a verdict: the nearest earlier
row from another source whose status is a failure or whose message says denied or blocked.
Deterministic SQL on the caller's `events` view; no model is called."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import NotFoundError
from app.engine.duckdb import QueryEngine, QueryScope
from app.search import drill
from app.search.addresses import spans

SPAN = timedelta(minutes=5)
FIND = timedelta(hours=1)  # how far from the given time the event itself is looked for
MAX_ROWS = 50
TIMEOUT_S = 20.0
COLUMNS = drill.EVENT_COLUMNS + ", status_id"
_TS = drill.TS
# A row that went wrong: OCSF failure, or a block or deny in its words.
FAILED = (
    "(status_id = 2 OR message ILIKE '%denied%' OR message ILIKE '%deny%'"
    " OR message ILIKE '%blocked%')"
)
RULE = (
    "The nearest earlier row from another source with a failure status, or a message "
    "that says denied or blocked"
)
FIRST_RULE = (
    "No failure before it: the nearest earlier row whose destination (host, app, or address) "
    "this person or device had not reached in the 30 days before"
)
HISTORY = timedelta(days=30)
# What a row reached: a host name, the app or resource, or an address.
TARGET = (
    "coalesce(nullif(dst_endpoint_hostname, ''), nullif(resource_name, ''),"
    " nullif(dst_endpoint_ip, ''))"
)

EVENT_SQL = f"""
SELECT {_TS}, source_id, actor_user_name, device_hostname, src_endpoint_ip
FROM events WHERE event_id = $id LIMIT 1"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class Around:
    event_id: str
    at: str
    person: list[str]
    devices: list[str]
    addresses: list[str]
    joined_by_address: bool  # the person came from who held the address (ADR-0029)
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    more: bool = False  # more rows than MAX_ROWS in the window: the nearest are shown
    likely_cause: str | None = None  # event_id of the hint row
    likely_rule: str = RULE
    sql: str = ""  # Search SQL with {from} and {to}
    start: str = ""
    end: str = ""
    sources: list[str] = field(default_factory=list)


def _utc(v: Any) -> datetime:
    t = v if isinstance(v, datetime) else datetime.fromisoformat(str(v))
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(UTC)


def _where(people: list[str], devices: list[str], ips: list[str]) -> str:
    parts = []
    if people:
        parts.append(f"lower(actor_user_name) IN ({', '.join(drill.lit(p) for p in people)})")
    if devices:
        parts.append(f"lower(device_hostname) IN ({', '.join(drill.lit(d) for d in devices)})")
    if ips:
        ip_list = ", ".join(drill.lit(i) for i in ips)
        parts.append(f"src_endpoint_ip IN ({ip_list}) OR device_ip IN ({ip_list})")
    return " OR ".join(parts)


def around(engine: QueryEngine, allowed: list[str] | None, event_id: str, at: datetime) -> Around:
    at = at.astimezone(UTC)
    found = engine.run(
        EVENT_SQL, QueryScope(allowed, at - FIND, at + FIND), {"id": event_id},
        timeout_s=TIMEOUT_S, name="around.event",
    )  # fmt: skip
    if not found.rows:
        raise NotFoundError("That event is not in the sources you can read")
    t, source, who, host, ip = found.rows[0]
    t = _utc(t)
    people = [str(who).lower()] if who else []
    devices = [str(host).lower()] if host else []
    ips = [str(ip)] if ip else []
    joined = False
    if not people and ip:
        for s in spans(engine, QueryScope(allowed), str(ip), t):
            if s.person and s.kind != "dhcp" and s.person.lower() not in people:
                people.append(s.person.lower())
                joined = True
            if s.machine and s.machine.lower() not in devices:
                devices.append(s.machine.lower())
    out = Around(
        event_id=event_id, at=t.isoformat(), person=people, devices=devices, addresses=ips,
        joined_by_address=joined, start=(t - SPAN).isoformat(), end=(t + SPAN).isoformat(),
    )  # fmt: skip
    cond = _where(people, devices, ips)
    if not cond:  # nothing to join on: the event alone
        cond = f"event_id = {drill.lit(event_id)}"
    out.sql = drill.events(f"({cond})", COLUMNS)
    body = (
        f"SELECT {COLUMNS} FROM events WHERE ({cond})"  # noqa: S608  # escaped literals only
        f" ORDER BY abs(epoch({_TS}) - epoch($at)), event_id LIMIT {MAX_ROWS}"
    )
    res = engine.run(
        body, QueryScope(allowed, t - SPAN, t + SPAN), {"at": t}, timeout_s=TIMEOUT_S,
        name="around.rows",
    )  # fmt: skip
    cols = [c.strip() for c in COLUMNS.split(",")]
    ti, ei = cols.index("time"), cols.index("event_id")
    rows = sorted(res.rows, key=lambda r: (_utc(r[ti]) if r[ti] else t, str(r[ei])))
    out.columns, out.sources = cols, sorted(res.sources)
    out.more = len(res.rows) >= MAX_ROWS
    out.rows = [[v.isoformat() if isinstance(v, datetime) else v for v in r] for r in rows]
    cause = engine.run(
        f"SELECT event_id FROM events WHERE ({cond}) AND source_id <> $src AND {FAILED}"  # noqa: S608  # escaped literals only
        f" AND {_TS} < $at ORDER BY {_TS} DESC LIMIT 1",
        QueryScope(allowed, t - SPAN, t), {"src": source, "at": t}, timeout_s=TIMEOUT_S,
        name="around.cause",
    ).rows  # fmt: skip
    shown = {str(r[ei]) for r in rows}
    if cause and str(cause[0][0]) in shown:
        out.likely_cause = str(cause[0][0])
        return out
    first = _first_seen(engine, allowed, cond, event_id, t)
    if first and first in shown:
        out.likely_cause, out.likely_rule = first, FIRST_RULE
    return out


def _first_seen(
    engine: QueryEngine, allowed: list[str] | None, cond: str, event_id: str, t: datetime
) -> str | None:
    """The nearest earlier row in the window whose destination is new for this person or
    device: not reached in the HISTORY before the window. Two bounded queries."""
    near = engine.run(
        f"SELECT event_id, {TARGET} AS v FROM events WHERE ({cond}) AND event_id <> $id"  # noqa: S608  # escaped literals only
        f" AND {_TS} < $at AND {TARGET} IS NOT NULL ORDER BY {_TS} DESC LIMIT {MAX_ROWS}",
        QueryScope(allowed, t - SPAN, t), {"id": event_id, "at": t}, timeout_s=TIMEOUT_S,
        name="around.first",
    ).rows  # fmt: skip
    if not near:
        return None
    values = sorted({str(v) for _, v in near})
    sql = (
        f"SELECT DISTINCT {TARGET} FROM events WHERE ({cond})"  # noqa: S608  # escaped literals only
        f" AND list_contains($values, {TARGET})"
    )
    before = engine.run(
        sql, QueryScope(allowed, t - SPAN - HISTORY, t - SPAN), {"values": values},
        timeout_s=TIMEOUT_S, name="around.history",
    ).rows  # fmt: skip
    seen = {str(r[0]) for r in before}
    return next((str(i) for i, v in near if str(v) not in seen), None)
