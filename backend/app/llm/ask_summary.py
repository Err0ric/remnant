"""The answer step's one model call (ADR-0042 row 8, slice 1c): statements about the rows,
each citing event ids. Zero tools. The rows go under `data` with the sources of the query
declared, so the gate's classification check covers them (a `local_only` source in scope
blocks a cloud provider) and redaction applies as configured. Audited under purpose `ask`
with the prompt `ask_answer.v1`, as routing is with `ask_route.v1` (owner, 2026-11-02).

Nothing in the answer is run or followed. Statements that cite no sent row are removed in
code (`app.search.ask_summary.check_claims`), never shown labeled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.errors import ProviderError
from app.engine.duckdb import QueryScope
from app.llm.gate import GateRequest, LLMGate, data_message
from app.search.ask_summary import Sample

PROMPT = "ask_answer.v1"
# Five statements with a few 36-character ids each fit; ADR-0042 row 15 said 400, which
# a UUID-citing answer outgrows (recorded under As built).
MAX_TOKENS = 600


class Statement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
    event_ids: list[Annotated[str, StringConstraints(max_length=64)]] = Field(
        default_factory=list, max_length=20
    )


class Statements(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[Statement] = Field(default_factory=list, max_length=10)

    def cited_event_ids(self) -> list[str]:
        return [i.strip().lower() for c in self.claims for i in c.event_ids]


@dataclass(frozen=True, slots=True)
class Summary:
    claims: list[tuple[str, list[str]]]
    call_id: str
    citation_check: str


def summarize(
    gate: LLMGate,
    actor_id: str,
    provider_id: str,
    question: str,
    rows: Sample,
    sources: list[str],
) -> Summary:
    payload = {
        "question": question,
        "columns": rows.columns,
        "rows": rows.rows,
        "row_count": rows.row_count,
        "truncated": rows.truncated,
    }
    result = gate.call(
        GateRequest(
            actor_id=actor_id,
            provider_id=provider_id,
            purpose="ask",
            scope=QueryScope(sources=sources),
            prompt=PROMPT,
            messages=[data_message(payload, sources)],
            response_model=Statements,
            max_tokens=MAX_TOKENS,
            citable_event_ids=rows.event_ids,
        )
    )
    parsed = result.parsed
    if not isinstance(parsed, Statements):  # pragma: no cover  # the gate validated it
        raise ProviderError("The model returned an answer in the wrong shape")
    claims = [(c.text, list(c.event_ids)) for c in parsed.claims]
    return Summary(claims, result.call_id, result.citation_check or "fail")
