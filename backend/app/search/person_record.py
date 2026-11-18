"""The person page as a Record (ADR-0052, DESIGN.md 6.3): what the page needs besides the
summary, in one read of the person's own rows.

The names counted as this person (the Accounts list), events and failed sign-ins per day in
the viewer's time zone (Activity per day), and the person's Microsoft 365 lists as Search
query templates (sign-ins, mailbox rule changes, directory changes the person made). The
person is matched under every form of the name, as on the timeline (`_mine`). Deterministic
SQL on the caller's own view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.signin_classes import REAL_FAILURE
from app.search import drill, mail_rules
from app.search.admin_changes import DIR, OP
from app.search.dashboard import zone
from app.search.identity import IdentityMap
from app.search.timeline import AI_TELEMETRY, _mine, _signins

TIMEOUT_S = 20.0
MAX_FORMS = 50
M365_LISTS = ("sign_ins", "mail", "admin")

# One row per name and quarter hour: few rows, and the days are cut in the viewer's zone in
# Python (every zone's offset is a multiple of 15 minutes). A failed sign-in is a real
# failure, as on the summary: interrupted and expired sign-ins are not failures (DESIGN.md
# 6.2a).
SQL = f"""
SELECT actor_user_name,
       time_bucket(INTERVAL '15 minutes', timezone('UTC', coalesce(time, time_observed))),
       count(*), count(*) FILTER (WHERE class_uid = 3002 AND {REAL_FAILURE})
FROM events WHERE {{mine}}{{ai}}
GROUP BY 1, 2
"""  # noqa: S608  # fixed SQL text; the person condition holds literals only (`_mine`)


@dataclass(slots=True)
class Day:
    day: str  # the viewer's calendar day, YYYY-MM-DD
    events: int = 0
    failed: int = 0


@dataclass(slots=True)
class PersonRecord:
    person: str
    forms: list[str] = field(default_factory=list)
    days: list[Day] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    # The person's events as a Search query template: what a day's bar opens.
    sql: str = ""


def m365_sql(ident: IdentityMap, person: str, name: str) -> str:
    """One of the person's Microsoft 365 lists as a Search query template (`{from}`,
    `{to}`): the rows the page shows and the query Open in Logs hands over."""
    if not person.strip():
        raise ParamInvalidError("Name a person")
    mine = _mine(ident, ident.keys_for(person))
    if name == "sign_ins":
        return _signins(mine)
    if name == "mail":
        return drill.events(
            f"{mail_rules.WHERE} AND {mine}",
            f"time, actor_user_name, {mail_rules.OP} AS operation, src_endpoint_ip, event_id",
        )
    if name == "admin":
        return drill.events(
            f"{DIR} AND {mine}",
            f"time, actor_user_name, {OP} AS operation, resource_name AS target, event_id",
        )
    raise ParamInvalidError(f"Unknown list {name[:32]!r}")


def person_record(
    engine: QueryEngine,
    scope: QueryScope,
    ident: IdentityMap,
    person: str,
    tz: str = "UTC",
    ai: bool = True,
) -> PersonRecord:
    """Without `ai` (a caller without View people in AI usage, D242) AI telemetry rows are
    left out, as on the timeline."""
    if not person.strip():
        raise ParamInvalidError("Name a person")
    assert scope.start is not None and scope.end is not None  # the page always has a window
    z = zone(tz)
    first = scope.start.astimezone(z).date()
    # The end is exclusive: a window that stops at midnight has no row for the day after.
    last = (scope.end - timedelta(microseconds=1)).astimezone(z).date()
    days = {
        (first + timedelta(days=i)).isoformat(): Day((first + timedelta(days=i)).isoformat())
        for i in range((last - first).days + 1)
    }
    res = engine.run(
        SQL.format(mine=_mine(ident, ident.keys_for(person)), ai="" if ai else AI_TELEMETRY),
        scope, timeout_s=TIMEOUT_S, name="person.record", page=True,
    )  # fmt: skip  # the condition is literals built by _mine
    mine = _mine(ident, ident.keys_for(person))
    forms: set[str] = set()
    for name, hour, events, failed in res.rows:
        if name:
            forms.add(str(name))
        at = hour if isinstance(hour, datetime) else datetime.fromisoformat(str(hour))
        day = days.get(at.replace(tzinfo=UTC).astimezone(z).date().isoformat())
        if day is not None:
            day.events += int(events)
            day.failed += int(failed)
    return PersonRecord(
        ident.key(person), sorted(forms)[:MAX_FORMS], list(days.values()), list(res.sources),
        drill.events(mine if ai else f"{mine}{AI_TELEMETRY}"),
    )  # fmt: skip
