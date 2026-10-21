"""Explain these events (Slice 4, SPEC 7.3, CLAUDE.md security rule 4).

The analyst picks events; only those events are sent, and only if the analyst may read
their sources. At most `MAX_EVENTS` events go out, each reduced to the columns below with
long values cut, all under the `data` key with their sources declared, so the gate's
classification check covers exactly what is sent. The model has no tools.

The answer is a list of claims, each citing event ids. The gate records whether the
answer as a whole cites only events that were sent (`citation_check`); each claim is also
marked verified only when it cites at least one id and every id it cites was sent.
Nothing in the answer is run or followed: it is text shown to the analyst.
"""

import re
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.errors import ParamInvalidError, ProviderError
from app.engine.duckdb import QueryEngine, QueryScope
from app.llm.gate import GateRequest, LLMGate, data_message

MAX_EVENTS = 50
MAX_VALUE = 500  # characters per field value
MAX_RAW = 2_000  # characters of the original line
COLUMNS = (
    "event_id",
    "source_id",
    "time",
    "class_uid",
    "activity_id",
    "status_id",
    "severity_id",
    "message",
    "actor_user_name",
    "actor_process_name",
    "src_endpoint_ip",
    "src_endpoint_port",
    "dst_endpoint_ip",
    "dst_endpoint_port",
    "device_hostname",
    "raw",
)
EVENT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class Claim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
    # Ids are compared lowercase, as stored; a model's casing or spacing is not a fabrication.
    event_ids: list[
        Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=64)]
    ] = Field(default_factory=list, max_length=50)


class ExplainAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[Claim] = Field(min_length=1, max_length=10)

    def cited_event_ids(self) -> list[str]:
        return [i for c in self.claims for i in c.event_ids]


@dataclass(frozen=True, slots=True)
class CheckedClaim:
    text: str
    event_ids: list[str]
    verified: bool


@dataclass(frozen=True, slots=True)
class Explanation:
    claims: list[CheckedClaim]
    citation_check: str
    call_id: str
    events_sent: list[str]
    not_found: int  # requested ids that do not exist or are outside the caller's sources
    sources: list[str]


def _cut(value: object, limit: int) -> object:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


class Explainer:
    def __init__(self, gate: LLMGate, engine: QueryEngine) -> None:
        self._gate = gate
        self._engine = engine

    def fetch(self, event_ids: list[str], scope: QueryScope) -> list[dict[str, object]]:
        ids = sorted({i.lower() for i in event_ids})
        if not ids or len(ids) > MAX_EVENTS:
            raise ParamInvalidError(f"Choose between 1 and {MAX_EVENTS} events to explain")
        if not all(EVENT_ID.fullmatch(i) for i in ids):
            raise ParamInvalidError("Event ids must be UUIDs")
        listed = ", ".join(f"'{i}'" for i in ids)  # each one checked as a UUID above
        cols = ", ".join(f'"{c}"' for c in COLUMNS)
        result = self._engine.run(
            f"SELECT {cols} FROM events WHERE CAST(event_id AS VARCHAR) IN ({listed})"  # noqa: S608  # ids validated, columns fixed
            " ORDER BY coalesce(time, time_observed), event_id",
            scope,
            row_cap=MAX_EVENTS,
        )
        rows = []
        for r in result.rows:
            event = {c: v for c, v in zip(result.columns, r, strict=True) if v is not None}
            event["event_id"] = str(event["event_id"])
            for c, v in event.items():
                event[c] = _cut(v, MAX_RAW if c == "raw" else MAX_VALUE)
            rows.append(event)
        return rows

    def explain(
        self,
        actor_id: str,
        provider_id: str,
        scope: QueryScope,
        event_ids: list[str],
        question: str | None,
    ) -> Explanation:
        events = self.fetch(event_ids, scope)
        if not events:
            raise ParamInvalidError("None of those events exist in sources you can read")
        sent = [str(e["event_id"]) for e in events]
        sources = sorted({str(e["source_id"]) for e in events})
        payload: dict[str, object] = {"events": events}
        if question:
            payload["question"] = question
        result = self._gate.call(
            GateRequest(
                actor_id=actor_id,
                provider_id=provider_id,
                purpose="explain",
                scope=QueryScope(sources=sources),
                prompt="explain.v1",
                messages=[data_message(payload, sources)],
                response_model=ExplainAnswer,
                max_tokens=4_096,
                citable_event_ids=frozenset(sent),
            )
        )
        if not isinstance(result.parsed, ExplainAnswer):  # pragma: no cover  # gate validated
            raise ProviderError("The model returned an answer in the wrong shape")
        allowed = set(sent)
        claims = [
            CheckedClaim(
                c.text,
                list(dict.fromkeys(c.event_ids)),
                bool(c.event_ids) and set(c.event_ids) <= allowed,
            )
            for c in result.parsed.claims
        ]
        return Explanation(
            claims=claims,
            citation_check=result.citation_check or "fail",
            call_id=result.call_id,
            events_sent=sent,
            not_found=len({i.lower() for i in event_ids}) - len(sent),
            sources=sources,
        )
