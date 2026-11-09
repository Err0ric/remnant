"""Ask's path for one question (ADR-0042 slice 1b): code reads the question and matches it
to the library; only when no library query is a confident match does the router pick one
or none (owner, 2026-11-08: a library hit never waits on the model). Code builds what
runs. The SQL-writing agent is the fallback. Nothing here runs the query: it is kept and
run by its id (slice 1a)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Literal

from app.engine.duckdb import QueryEngine, QueryScope
from app.llm.ask_router import Route, route
from app.llm.gate import LLMGate
from app.search.ask_route import (
    Candidate,
    Entity,
    Plan,
    Span,
    confident,
    find_entities,
    parse_time,
    plan,
    rank,
)
from app.search.identity import IdentityMap
from app.search.library import Library
from app.search.params import IDENTITY_PARAMS, compile_sql, placeholders, uses_identities

DESCRIBE_TIMEOUT_S = 10.0


@dataclass(slots=True)
class Routed:
    kind: Literal["data", "knowhow"]
    by: Literal["model", "forced", "library"]
    span: Span | None
    entities: list[Entity]
    candidates: list[Candidate]
    candidate: Candidate | None = None
    plan: Plan | None = None
    call_id: str | None = None
    # Why the library was not used, in plain words, for How I got this.
    reason: str | None = None
    dropped: list[str] = field(default_factory=list)
    # Which route answered, for the audit row: "library" (no model call) or "model".
    via: Literal["library", "model"] = "model"
    route_ms: int = 0  # time spent routing, matching included


def read_question(
    question: str, now: datetime, tz: str | None, ident: IdentityMap | None
) -> tuple[Span | None, list[Entity]]:
    return parse_time(question, now, tz), find_entities(question, read_people(ident))


def read_people(ident: IdentityMap | None) -> set[str]:
    return set(ident.aliases) | set(ident.aliases.values()) if ident else set()


def output_columns(
    engine: QueryEngine, sql: str, scope: QueryScope, params: dict[str, object]
) -> list[str]:
    """The library query's output column names, from a zero-row run on the asker's view."""
    used = placeholders(sql)
    params = {k: v for k, v in params.items() if k in used or k in IDENTITY_PARAMS}
    res = engine.run(
        f"SELECT * FROM (\n{compile_sql(sql)}\n) AS q LIMIT 0",  # noqa: S608  # reviewed library SQL
        scope,
        params or None,
        timeout_s=DESCRIBE_TIMEOUT_S,
        intel=False,
        name="ask.describe",
    )
    return list(res.columns)


def route_question(
    gate: LLMGate,
    engine: QueryEngine,
    library: Library,
    seen: set[str],
    actor_id: str,
    provider_id: str,
    question: str,
    now: datetime,
    tz: str | None,
    ident: IdentityMap | None,
    scope: QueryScope,
    forced: Literal["auto", "data"] = "auto",
) -> Routed:
    started = monotonic()
    span, entities = read_question(question, now, tz, ident)
    candidates = rank(question, library, seen)
    sure = confident(question, candidates, entities)
    if sure is not None:
        p = _plan(engine, sure, {}, entities, span, scope, now, ident)
        if not p.unused:  # otherwise the router decides, exactly as before
            return Routed(
                kind="data", by="forced" if forced == "data" else "library", span=span,
                entities=entities, candidates=candidates, candidate=sure, plan=p,
                via="library", route_ms=_ms(started),
            )  # fmt: skip
    r: Route = route(gate, actor_id, provider_id, question, candidates, entities, span)
    out = Routed(
        kind="data" if forced == "data" else r.kind,
        by="forced" if forced == "data" else "model",
        span=span,
        entities=entities,
        candidates=candidates,
        call_id=r.call_id,
        dropped=r.dropped,
    )
    if out.kind == "knowhow" or r.candidate is None:
        if out.kind != "knowhow":
            out.reason = "No library query fits this question"
        out.route_ms = _ms(started)
        return out
    p = _plan(engine, r.candidate, r.params, entities, span, scope, now, ident)
    out.route_ms = _ms(started)
    if p.unused:
        names = ", ".join(e.value for e in p.unused)
        out.reason = f"{r.candidate.query.name} cannot be narrowed to {names}"
        return out
    out.candidate, out.plan = r.candidate, p
    return out


def _ms(started: float) -> int:
    return round((monotonic() - started) * 1000)


def _plan(
    engine: QueryEngine,
    c: Candidate,
    chosen: dict[str, str | int | float | bool],
    entities: list[Entity],
    span: Span | None,
    scope: QueryScope,
    now: datetime,
    ident: IdentityMap | None,
) -> Plan:
    """The library query with the question's filters, from its output columns."""
    q = c.query
    params = {p.name: p.default for p in q.params if p.default is not None} | chosen
    when = scope if span is None else QueryScope(scope.sources, span.start, span.end)
    values = dict(params)
    values.setdefault("start", when.start or datetime(1970, 1, 1, tzinfo=now.tzinfo))
    values.setdefault("end", when.end or now)
    if uses_identities(q.sql):  # a zero-row describe: the columns need no links (T70, D219)
        values |= IdentityMap().sql_values()
    columns = output_columns(engine, q.sql, when, values)
    return plan(q, columns, entities, params, ident)
