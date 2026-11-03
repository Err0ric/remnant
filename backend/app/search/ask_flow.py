"""Ask's path for one question (ADR-0042 slice 1b): code reads the question, the router
picks a library query or none, and code builds what runs. The SQL-writing agent is the
fallback. Nothing here runs the query: it is kept and run by its id (slice 1a)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.engine.duckdb import QueryEngine, QueryScope
from app.llm.ask_router import Route, route
from app.llm.gate import LLMGate
from app.search.ask_route import (
    Candidate,
    Entity,
    Plan,
    Span,
    find_entities,
    parse_time,
    plan,
    rank,
)
from app.search.identity import IdentityMap
from app.search.library import Library
from app.search.params import compile_sql, placeholders

DESCRIBE_TIMEOUT_S = 10.0


@dataclass(slots=True)
class Routed:
    kind: Literal["data", "knowhow"]
    by: Literal["model", "forced"]
    span: Span | None
    entities: list[Entity]
    candidates: list[Candidate]
    candidate: Candidate | None = None
    plan: Plan | None = None
    call_id: str | None = None
    # Why the library was not used, in plain words, for How I got this.
    reason: str | None = None
    dropped: list[str] = field(default_factory=list)


def read_question(
    question: str, now: datetime, tz: str | None, ident: IdentityMap | None
) -> tuple[Span | None, list[Entity]]:
    people = set(ident.aliases) | set(ident.aliases.values()) if ident else set()
    return parse_time(question, now, tz), find_entities(question, people)


def output_columns(
    engine: QueryEngine, sql: str, scope: QueryScope, params: dict[str, object]
) -> list[str]:
    """The library query's output column names, from a zero-row run on the asker's view."""
    used = placeholders(sql)
    params = {k: v for k, v in params.items() if k in used}
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
    span, entities = read_question(question, now, tz, ident)
    candidates = rank(question, library, seen)
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
    if out.kind == "knowhow":
        return out
    if r.candidate is None:
        out.reason = "No library query fits this question"
        return out
    q = r.candidate.query
    params = {p.name: p.default for p in q.params if p.default is not None} | r.params
    when = scope if span is None else QueryScope(scope.sources, span.start, span.end)
    values = dict(params)
    values.setdefault("start", when.start or datetime(1970, 1, 1, tzinfo=now.tzinfo))
    values.setdefault("end", when.end or now)
    columns = output_columns(engine, q.sql, when, values)
    p = plan(q, columns, entities, params, ident)
    if p.unused:
        names = ", ".join(e.value for e in p.unused)
        out.reason = f"{r.candidate.query.name} cannot be narrowed to {names}"
        return out
    out.candidate, out.plan = r.candidate, p
    return out
