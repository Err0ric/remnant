"""Who had an address at a time (ADR-0020 row 1), from logon, User-ID, and GlobalProtect
events in the caller's sources, audited as address.lookup; and the address page's sections
(P4), each a library query on the caller's view, audited as address.section. Router only."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.ai.catalog import Catalog
from app.api.access import CurrentUser, client_ip
from app.auth.service import AuthService
from app.core import clock
from app.core.errors import AppError
from app.core.times import UtcDateTime, utc
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.views import permitted_sources
from app.ingest.sources import SourceStore
from app.search import address_page
from app.search.addresses import MAX_AGE_HOURS, Span, spans
from app.search.library import Library

router = APIRouter(tags=["addresses"])


class HolderOut(BaseModel):
    kind: str
    name: str
    last_seen: str
    events: int


class SpanOut(BaseModel):
    """One match that held the address at the time (D107 C1): what it was, when it
    started and ended, whether the end was assumed (capped), and the source."""

    kind: str  # vpn | userid | logon | dhcp | signin
    start: str
    end: str | None
    capped: bool
    person: str | None
    machine: str | None
    mac: str | None
    source: str


class AddressOut(BaseModel):
    ip: str
    at: str
    max_age_hours: int
    holders: list[HolderOut]
    spans: list[SpanOut]


@router.get("/addresses/{ip}")
async def address(
    ip: str, request: Request, user: CurrentUser, at: UtcDateTime | None = None
) -> AddressOut:
    """The spans that held this address at `at` (default now), newest first: logons,
    User-ID, GlobalProtect, DHCP leases, and the sign-ins that name a machine's person
    (ADR-0029)."""
    when = utc(at or clock.now())  # a time without a zone was read as UTC (UtcDateTime)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    engine: QueryEngine = request.app.state.engine
    auth: AuthService = request.app.state.auth
    detail: dict[str, object] = {"ip": ip[:64], "at": when.isoformat(), "sources_in_scope": allowed}
    try:
        found = await run_in_threadpool(spans, engine, QueryScope(allowed), ip, when)
    except AppError as exc:
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "address.lookup", "failure", user.user_id, client_ip(request), detail
        )
        raise
    await run_in_threadpool(
        auth.audit.write, "address.lookup", "success", user.user_id, client_ip(request), detail
    )
    return AddressOut(
        ip=ip,
        at=when.isoformat(),
        max_age_hours=MAX_AGE_HOURS,
        holders=_holders(found),
        spans=[SpanOut(**{f: getattr(x, f) for f in SpanOut.model_fields}) for x in found],
    )


def _holders(found: list[Span]) -> list[HolderOut]:
    """People and machines from the spans, newest first; DHCP never names a person."""
    out: dict[tuple[str, str], HolderOut] = {}
    for x in found:
        for kind, name in (("user", x.person), ("host", x.machine)):
            if name and (kind, name) not in out and not (kind == "user" and x.kind == "dhcp"):
                out[(kind, name)] = HolderOut(kind=kind, name=name, last_seen=x.start, events=1)
    return list(out.values())


class FoundOut(BaseModel):
    source_id: str
    kind: str  # DNS, firewall, syslog, identity, application, findings, other


# A template's category in plain words, as the address coverage lines name them.
KINDS = {"dns": "DNS", "network": "firewall", "system": "syslog", "identity": "identity",
         "application": "application", "findings": "findings"}  # fmt: skip


class SectionOut(BaseModel):
    """One section of the address page (P4): a shipped library query's rows for this
    address, what it read, and per row the events behind it for Logs (server-built SQL,
    `{{start}}` and `{{end}}` filled by the Logs range). `no_source`: none of the caller's
    sources is set to a template in `needs`, so nothing ran."""

    section: address_page.Name
    title: str  # the page's title for it
    library: str  # "<pack>/<query>@<version>"
    query: str  # the library query's name
    state: str
    count: int
    count_words: str
    columns: list[str]
    rows: list[list[Any]]
    links: list[str | None]
    read: list[str]
    needs: list[str]
    restricted: bool  # the caller cannot read every source
    # The sources that returned rows, each with its kind in plain words ("DNS").
    found: list[FoundOut]


SECTION_DAYS = 30  # with no start, the 30 days before the end, as the top bar lookup


def section_out(
    s: address_page.Section, names: dict[str, str], restricted: bool, kinds: dict[str, str]
) -> SectionOut:
    return SectionOut(
        section=s.name, title=address_page.TITLES[s.name], library=s.library, query=s.query,
        state=s.state, count=s.count,
        count_words=s.words(), columns=s.columns, rows=s.rows, links=s.links, read=s.read,
        needs=[names.get(t, t) for t in s.needs], restricted=restricted,
        found=[FoundOut(source_id=x, kind=kinds.get(x, "other")) for x in s.found],
    )  # fmt: skip


def readable(request: Request, allowed: list[str] | None) -> set[str] | None:
    """Templates the caller's own sources are set to (None: one parses with any)."""
    store: SourceStore = request.app.state.sources
    mine = [
        (s.source_id, s.template_id)
        for s in store.list()
        if allowed is None or s.source_id in allowed
    ]
    return address_page.readable_templates(mine)


@router.get("/addresses/{ip}/sections/{name}")
async def address_section(
    ip: str,
    name: address_page.Name,
    request: Request,
    user: CurrentUser,
    start: UtcDateTime | None = None,
    end: UtcDateTime | None = None,
) -> SectionOut:
    """One section of the address page: `dhcp` (who had it: DHCP leases and VPN tunnels),
    `dns` (the names it looked up), `access` (sign-ins, access checks, and firewall
    traffic by kind and outcome), `ai` (the AI services seen from it, as AI usage counts
    them). Each is a shipped library query through the guard on the caller's view; the
    page asks for each on its own, so a slow one holds up no other."""
    value = address_page.address(ip)
    stop = utc(end or clock.now())
    begin = start or stop - timedelta(days=SECTION_DAYS)
    allowed = await run_in_threadpool(permitted_sources, request.app.state.meta, user)
    engine: QueryEngine = request.app.state.engine
    library: Library = request.app.state.library
    auth: AuthService = request.app.state.auth
    templates = await run_in_threadpool(readable, request, allowed)
    detail: dict[str, object] = {
        "ip": value[:64], "section": name, "sources_in_scope": allowed,
        "start": begin.isoformat(), "end": stop.isoformat(),
    }  # fmt: skip
    catalog: Catalog = request.app.state.ai_catalog
    services = await run_in_threadpool(catalog.services)
    try:
        s = await run_in_threadpool(
            address_page.section, engine, library, name, value,
            QueryScope(allowed, begin, stop), templates, stop, services,
        )  # fmt: skip
    except AppError as exc:
        detail["error"] = type(exc).__name__
        await run_in_threadpool(
            auth.audit.write, "address.section", "failure", user.user_id, client_ip(request), detail
        )
        raise
    detail |= {"library": s.library, "state": s.state, "read": s.read}
    await run_in_threadpool(
        auth.audit.write, "address.section", "success", user.user_id, client_ip(request), detail
    )
    names = {t.id: t.name for t in request.app.state.templates.all()}
    return section_out(s, names, allowed is not None, await run_in_threadpool(kinds, request))


def kinds(request: Request) -> dict[str, str]:
    """Each source's kind in plain words, from its template's category."""
    store: SourceStore = request.app.state.sources
    templates = request.app.state.templates
    out = {}
    for src in store.list():
        t = templates.get(src.template_id) if src.template_id else None
        out[src.source_id] = KINDS.get(t.category if t else "", "other")
    return out
