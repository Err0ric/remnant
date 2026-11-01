"""A person's timeline (ADR-0038 section 9). Router only."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import CurrentUser, client_ip
from app.api.alert_items import _readable
from app.auth.service import AuthService
from app.auth.users import User
from app.engine.views import permitted_sources
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
    first, with the forms of the name that matched. Audited `search.timeline`."""
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    ident = await run_in_threadpool(request.app.state.identities.load)
    start, end = window(days, datetime.now(UTC))
    out = await run_in_threadpool(
        timeline, request.app.state.engine, allowed, ident,
        request.app.state.ai_catalog.domain_table(), person[:256], start, end,
        request.app.state.ai_rollup,
    )  # fmt: skip
    out.rows = await run_in_threadpool(
        _with_alerts, request, user, out.rows, person[:256], start, end
    )
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "search.timeline", "success", user.user_id, client_ip(request),
        {"person": out.person[:256], "days": days, "rows": len(out.rows),
         "sources_in_scope": out.sources},
    )  # fmt: skip
    return PersonTimelineOut(
        person=out.person, forms=out.forms, devices=out.devices, start=out.start, end=out.end,
        rows=[TimelineRowOut(**{f: getattr(r, f) for f in TimelineRowOut.model_fields})
              for r in out.rows],
        more=out.more, sql=out.sql, signins_sql=out.signins_sql,
        maybe=[MaybeOut(name=m.name, devices=m.devices) for m in out.maybe],
    )  # fmt: skip


def _with_alerts(
    request: Request, user: User, rows: list[Row], person: str, start: datetime, end: datetime
) -> list[Row]:
    """Alerts about the person in the window (ADR-0038 row 28), the ones the caller may
    read, as rows that open the alert."""
    ident = request.app.state.identities.load()
    keys = set(ident.keys_for(person))
    readable = _readable(request, user)
    lo, hi = start.isoformat(), end.isoformat()
    for i in request.app.state.alert_items.items(user, "all"):
        if not (lo <= i.created_at <= hi) or not readable(i):
            continue
        if not any(ident.key(p) in keys for p in i.people):
            continue
        rows.append(
            Row("alert", i.created_at, i.created_at, i.title, f"Alert, {i.state}", i.count or 1,
                "alerts", "warn" if i.state == "open" else "neutral", "", i.item_id)
        )  # fmt: skip
    rows.sort(key=lambda r: r.start, reverse=True)
    return rows
