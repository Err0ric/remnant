"""Ask routing with a model (ADR-0042 slice 1b, row 4): one short call with no tools that
says whether a question is about the analyst's data or general know-how, and which shipped
library query answers it, if any.

The model sees the question, the library candidates code already ranked (their ref, name,
example questions, and parameter names; reviewed repository text, never log data), and
what code already read from the question. It returns a kind, a ref or null, and values for
that query's own parameters. Code then checks every part: an unknown ref is no match, and
parameter values must fit their declared types. The call goes through the gate with no
sources declared, because no log data is sent; it is audited under purpose `ask` with the
prompt `ask_route.v1`, which tells it apart from the SQL-writing calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.errors import ParamInvalidError, ProviderError
from app.engine.duckdb import QueryScope
from app.llm.gate import GateRequest, LLMGate
from app.llm.provider import ChatMessage
from app.search.ask_route import Candidate, Entity, Span
from app.search.params import coerce

PROMPT = "ask_route.v1"
MAX_TOKENS = 256

Scalar = str | int | float | bool


class RouteAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["data", "knowhow"] = "data"
    query: Annotated[str, StringConstraints(max_length=100)] | None = None
    params: dict[Annotated[str, StringConstraints(max_length=32)], Scalar | None] = Field(
        default_factory=dict, max_length=20
    )


@dataclass(frozen=True, slots=True)
class Route:
    kind: Literal["data", "knowhow"]
    candidate: Candidate | None
    params: dict[str, Scalar]
    call_id: str
    dropped: list[str]  # parameter values the model gave that did not fit, by name


def _payload(
    question: str, candidates: list[Candidate], entities: list[Entity], span: Span | None
) -> str:
    return json.dumps(
        {
            "question": question,
            "candidates": [
                {
                    "ref": c.ref,
                    "name": c.query.name,
                    "questions": c.query.ask,
                    "params": [
                        {"name": p.name, "type": p.type, "about": p.description}
                        for p in c.query.params
                    ],
                }
                for c in candidates
            ],
            "found": {
                "entities": [{"kind": e.kind, "value": e.value} for e in entities],
                "time": span.label if span else None,
            },
        }
    )


def route(
    gate: LLMGate,
    actor_id: str,
    provider_id: str,
    question: str,
    candidates: list[Candidate],
    entities: list[Entity],
    span: Span | None,
) -> Route:
    result = gate.call(
        GateRequest(
            actor_id=actor_id,
            provider_id=provider_id,
            purpose="ask",
            # No log data is sent: the question, reviewed library text, and what code read
            # from the question. Nothing to classify.
            scope=QueryScope(sources=[]),
            prompt=PROMPT,
            messages=[ChatMessage("user", _payload(question, candidates, entities, span))],
            response_model=RouteAnswer,
            max_tokens=MAX_TOKENS,
        )
    )
    answer = result.parsed
    if not isinstance(answer, RouteAnswer):  # pragma: no cover  # the gate validated it
        raise ProviderError("The model returned a route in the wrong shape")
    chosen = next((c for c in candidates if c.ref == answer.query), None)
    params: dict[str, Scalar] = {}
    dropped: list[str] = []
    if chosen is not None:
        for p in chosen.query.params:
            value = answer.params.get(p.name)
            if value is None or value == "":
                continue
            try:
                params[p.name] = coerce(p, value)
            except ParamInvalidError:
                dropped.append(p.name)
    kind = answer.kind if chosen is None else "data"  # a picked query is a data question
    return Route(kind, chosen, params, result.call_id, dropped)
