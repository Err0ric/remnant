"""A person's timeline (ADR-0038 section 9). Router only."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.ai.people_view import audit_ai_view, can_view_people
from app.api.access import CurrentUser, client_ip
from app.api.alert_items import _readable
from app.api.identities import caller_identities
from app.auth.service import AuthService
from app.auth.users import User
from app.core import clock
from app.engine.duckdb import QueryScope
from app.engine.views import permitted_sources
from app.search.identity import IdentityMap
from app.search.person_hosts import person_hosts
from app.search.timeline import Row, timeline, window

router = APIRouter(tags=["search"])


class TimelineRowOut(BaseModel):
    kind: str
    start: str
    end: str
    title: str
    detail: str
    count: int
    source: str
    tone: str
    sql: str
    item_id: str | None = None


class MaybeOut(BaseModel):
    name: str
    devices: list[str]


class PersonTimelineOut(BaseModel):
    person: str
    forms: list[str]
    devices: list[str]
    start: str
    end: str
    rows: list[TimelineRowOut]
    more: bool
    sql: str
    signins_sql: str
    maybe: list[MaybeOut] = []


@router.get("/people/{person}/timeline")
async def person_timeline(
    person: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> PersonTimelineOut:
    """One row per action by this person across the sources the caller may read, newest
    first, with the forms of the name that matched. Without View people in AI usage, AI
    rows (Claude sessions, first use of AI services, AI telemetry, AI Watch alerts) are
    left out (D242). Audited `search.timeline`, and ai.view_people or ai.view."""
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    start, end = window(days, clock.now())
    # The person's other forms, as far as the caller's scope shows them (T70, D219, D223).
    ident = await caller_identities(request, user, QueryScope(allowed, start, end))
    named_ok = can_view_people(user)
    out = await run_in_threadpool(
        timeline, request.app.state.engine, allowed, ident,
        request.app.state.ai_catalog.domain_table(), person[:256], start, end,
        request.app.state.ai_rollup, named_ok,
    )  # fmt: skip
    out.rows = await run_in_threadpool(
        _with_alerts, request, user, out.rows, person[:256], start, end, ident, named_ok
    )
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "search.timeline", "success", user.user_id, client_ip(request),
        {"person": out.person[:256], "days": days, "rows": len(out.rows),
         "sources_in_scope": out.sources},
    )  # fmt: skip
    # The page is about a named person: with the permission its AI rows are shown (G3).
    # The search.timeline row above holds who the page is about; this row only says AI
    # rows were part of that view, so it repeats no name (D242).
    await run_in_threadpool(
        audit_ai_view, auth.audit, user, client_ip(request), "person.timeline", start, end,
        out.sources, named_ok, days=days,
    )  # fmt: skip
    return PersonTimelineOut(
        person=out.person, forms=out.forms, devices=out.devices, start=out.start, end=out.end,
        rows=[TimelineRowOut(**{f: getattr(r, f) for f in TimelineRowOut.model_fields})
              for r in out.rows],
        more=out.more, sql=out.sql, signins_sql=out.signins_sql,
        maybe=[MaybeOut(name=m.name, devices=m.devices) for m in out.maybe],
    )  # fmt: skip


class UsedOut(BaseModel):
    kind: str
    value: str
    events: int
    failed: int
    first_seen: str | None
    last_seen: str | None
    sources: list[str]


class PersonHostsOut(BaseModel):
    person: str
    start: str
    end: str
    hosts: list[UsedOut]
    addresses: list[UsedOut]
    sources: list[str]


@router.get("/people/{person}/hosts")
async def person_hosts_route(
    person: str,
    request: Request,
    user: CurrentUser,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> PersonHostsOut:
    """The hosts and source addresses on this person's own records, busiest first, with
    failed sign-ins and first and last seen (D197). Audited `search.person_hosts`."""
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    start, end = window(days, clock.now())
    scope = QueryScope(allowed, start, end)
    ident = await caller_identities(request, user, scope)  # T70, D219, D223
    out = await run_in_threadpool(
        person_hosts, request.app.state.engine, scope, ident,
        person[:256],
    )  # fmt: skip
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "search.person_hosts", "success", user.user_id, client_ip(request),
        {"person": person[:256], "days": days, "sources_in_scope": out.sources},
    )  # fmt: skip
    return PersonHostsOut(
        person=out.person, start=start.isoformat(), end=end.isoformat(),
        hosts=[UsedOut.model_validate(u, from_attributes=True) for u in out.hosts],
        addresses=[UsedOut.model_validate(u, from_attributes=True) for u in out.addresses],
        sources=out.sources,
    )  # fmt: skip


def _with_alerts(
    request: Request,
    user: User,
    rows: list[Row],
    person: str,
    start: datetime,
    end: datetime,
    ident: IdentityMap,
    named_ok: bool = True,
) -> list[Row]:
    """Alerts about the person in the window (ADR-0038 row 28), the ones the caller may
    read, as rows that open the alert. `ident` is the timeline's own (T70, D219). Without
    View people in AI usage, AI Watch items are left out before any name is matched."""
    keys = set(ident.keys_for(person))
    readable = _readable(request, user)
    lo, hi = start.isoformat(), end.isoformat()
    for i in request.app.state.alert_items.items(user, "all"):
        if not (lo <= i.created_at <= hi) or not readable(i):
            continue
        if i.kind == "ai_watch" and not named_ok:
            continue
        if not any(ident.key(p) in keys for p in i.people):
            continue
        rows.append(
            Row("alert", i.created_at, i.created_at, i.title, f"Alert, {i.state}", i.count or 1,
                "alerts", "warn" if i.state == "open" else "neutral", "", i.item_id)
        )  # fmt: skip
    rows.sort(key=lambda r: r.start, reverse=True)
    return rows
