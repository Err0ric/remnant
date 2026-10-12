"""Ask mode: a question becomes SQL that the analyst reviews before it runs (SPEC 5.3, 5.7).

The model sees the schema, sample values from low-cardinality columns, the time range,
and up to three earlier turns, all event-derived parts under a "data" key. It may call
`get_schema` and `preview_query` (5 rows) through the gate. Its final SQL is checked by
the guard and one preview; a failure or empty preview gets up to two refinements. The
SQL is returned, never run for the analyst. Every model call is audited by the gate.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.errors import AnswerShapeError, AppError, ProviderError
from app.core.schema import COLUMNS
from app.engine.duckdb import QueryEngine, QueryResult, QueryScope
from app.llm.gate import GateRequest, LLMGate, data_message
from app.llm.provider import ChatMessage, ToolCall
from app.llm.semantic import Vocabulary

PROMPT = "ask.v4"  # v4: distinct counts, INTERSECT, hosts and ports; v3 answer shapes
TOOLS = ["get_schema", "preview_query"]
PREVIEW_ROWS = 5
MAX_TOOL_ROUNDS = 4
MAX_REFINEMENTS = 2
CELL_CAP = 300  # characters per string shown to the model
ITEM_CAP = 20  # items per list or keys per object inside a value
TOOL_RESULT_BYTES = 16 * 1024  # one tool result, as JSON
MAX_CALLS_PER_TURN = 4  # tool calls honoured from one model reply
MAX_PREVIEWS = 8  # model-requested previews per Ask request
PREVIEW_TIMEOUT_S = 10.0
PROFILE_TIMEOUT_S = 5.0
PROFILE_COLUMNS = (
    "source_id",
    "template_id",
    "class_uid",
    "category_uid",
    "activity_id",
    "severity_id",
    "status_id",
    "parse_status",
    "actor_process_name",
    "device_hostname",
)
RESHAPE_REMINDER = (
    "Your last reply was not one JSON object in the required shape. Reply with only"
    ' {"sql": "...", "explanation": "...", "assumptions": ["..."]} and nothing before or after'
    " it. Inside JSON strings, write a backslash as two backslashes."
)
# Room for a reasoning model's thinking plus the answer; the reply is still capped at 64 KB.
ASK_MAX_TOKENS = 4_096
PROFILE_MAX_DISTINCT = 50  # columns with more distinct values are not sampled
PROFILE_VALUES = 20
UNMAPPED_KEYS = 30  # top-level keys of `unmapped` shown per question, most common first
UNMAPPED_VALUES = 5  # sample values for a key with at most PROFILE_VALUES distinct values
# Keys of the `unmapped` JSON per OCSF class, with how many distinct values each holds. The
# key names come from log data and only ever travel as values, never into the SQL text.
_UNMAPPED_SQL = (  # LIMIT 30 is UNMAPPED_KEYS, d <= 20 is PROFILE_VALUES
    "WITH kv AS (SELECT class_uid, k, json_extract_string(unmapped, '$.' || k) AS v"
    " FROM (SELECT class_uid, unmapped, unnest(json_keys(unmapped)) AS k FROM events"
    " WHERE unmapped IS NOT NULL AND json_valid(unmapped))),"
    " stats AS (SELECT class_uid, k, count(*) AS n, approx_count_distinct(v) AS d FROM kv"
    " GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30),"
    " small AS (SELECT kv.class_uid, kv.k,"
    " list(DISTINCT kv.v ORDER BY kv.v) FILTER (WHERE kv.v IS NOT NULL) AS vs"
    " FROM kv JOIN stats ON kv.k = stats.k AND kv.class_uid IS NOT DISTINCT FROM stats.class_uid"
    " WHERE stats.d <= 20 GROUP BY 1, 2)"
    " SELECT s.class_uid, s.k, s.n, s.d, sm.vs FROM stats s"
    " LEFT JOIN small sm ON s.k = sm.k AND s.class_uid IS NOT DISTINCT FROM sm.class_uid"
    " ORDER BY s.n DESC"
)


class AskAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sql: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
    explanation: Annotated[str, StringConstraints(max_length=4_000)] = ""
    assumptions: list[Annotated[str, StringConstraints(max_length=500)]] = Field(
        default_factory=list, max_length=10
    )

    # Small models get the prose fields loosely right: a string for the list, an over-long
    # note, a null. Those are trimmed to fit; `sql` stays strict, since it is what runs.
    @field_validator("explanation", mode="before")
    @classmethod
    def _explanation(cls, value: object) -> object:
        if value is None:
            return ""
        return value[:4_000] if isinstance(value, str) else value

    @field_validator("assumptions", mode="before")
    @classmethod
    def _assumptions(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value] if value.strip() else []
        if isinstance(value, list):
            return [v[:500] if isinstance(v, str) else v for v in value[:10]]
        return value


@dataclass(frozen=True, slots=True)
class AskTurn:
    question: str
    sql: str


@dataclass(slots=True)
class AskOutcome:
    answer: AskAnswer
    check: Literal["ok", "empty", "failed"]
    check_detail: str | None
    call_ids: list[str] = field(default_factory=list)
    attempts: int = 1


@dataclass(frozen=True, slots=True)
class AskExample:
    """A verified saved search (admin vouched for it), used as a worked example."""

    title: str
    sql: str


class AskAgent:
    def __init__(self, gate: LLMGate, engine: QueryEngine, vocabulary: Vocabulary) -> None:
        self._gate = gate
        self._engine = engine
        self._vocabulary = vocabulary

    def ask(
        self,
        actor_id: str,
        provider_id: str,
        scope: QueryScope,
        question: str,
        history: list[AskTurn],
        examples: list[AskExample] | None = None,
    ) -> AskOutcome:
        context, sources = self._context(scope, history)
        # Trusted guidance (repo vocabulary, admin-verified examples) is not event data.
        guidance = {
            "vocabulary": self._vocabulary.for_prompt(),
            "verified_examples": [
                {"title": e.title[:200], "sql": e.sql[:4_000]} for e in (examples or [])[:3]
            ],
        }
        messages: list[ChatMessage] = [
            ChatMessage("user", "Team vocabulary and verified examples:\n" + json.dumps(guidance)),
            data_message(context, sources),
            ChatMessage("user", f"Question: {question}"),
        ]
        call_ids: list[str] = []
        budget = [MAX_PREVIEWS]
        attempt = 0
        while True:
            attempt += 1
            answer = self._answer(actor_id, provider_id, scope, messages, call_ids, budget)
            check, detail, preview = self._check(answer.sql, scope)
            if check == "ok" or attempt > MAX_REFINEMENTS:
                return AskOutcome(answer, check, detail, call_ids, attempt)
            # Feed back the validated answer, not the raw reply: extra keys never return.
            messages.append(ChatMessage("assistant", answer.model_dump_json()))
            problem = (
                {"error": detail} if check == "failed" else {"rows": 0, "note": "no rows matched"}
            )
            messages.append(
                data_message(problem, preview.sources if preview else sources, role="user")
            )
            messages.append(
                ChatMessage(
                    "user",
                    "That query "
                    + ("failed" if check == "failed" else "returned no rows")
                    + ". Check column names and values with the tools, then answer again in"
                    " the same JSON shape. If no rows is the right answer, return the same query"
                    " and say so in the explanation.",
                )
            )

    # --- one answer, with tool rounds ----------------------------------------------------

    def _answer(
        self,
        actor_id: str,
        provider_id: str,
        scope: QueryScope,
        messages: list[ChatMessage],
        call_ids: list[str],
        budget: list[int],
    ) -> AskAnswer:
        reshaped = False
        round_no = 0
        while round_no <= MAX_TOOL_ROUNDS:
            last = round_no == MAX_TOOL_ROUNDS
            try:
                result = self._gate.call(
                    GateRequest(
                        actor_id=actor_id,
                        provider_id=provider_id,
                        purpose="ask",
                        scope=scope,
                        prompt=PROMPT,
                        messages=list(messages),
                        tools=None if last else TOOLS,
                        response_model=AskAnswer,
                        max_tokens=ASK_MAX_TOKENS,
                    )
                )
            except AnswerShapeError:
                if reshaped:
                    raise
                # Asked once more with a reminder of the shape. The bad reply is not sent
                # back (it is audited by the gate and may echo log content).
                reshaped = True
                messages.append(ChatMessage("user", RESHAPE_REMINDER))
                continue
            round_no += 1
            call_ids.append(result.call_id)
            calls = result.response.tool_calls
            if not calls:
                if not isinstance(result.parsed, AskAnswer):  # pragma: no cover  # gate validated
                    raise ProviderError("The model returned an answer in the wrong shape")
                return result.parsed
            # The reply's free text is dropped; only the tool requests go back.
            messages.append(ChatMessage("assistant", "", tool_calls=tuple(calls)))
            for n, call in enumerate(calls):
                if n >= MAX_CALLS_PER_TURN:
                    messages.append(_tool_error(call, f"At most {MAX_CALLS_PER_TURN} tool calls"))
                else:
                    messages.append(self._run_tool(call, scope, budget))
        raise ProviderError("The model kept calling tools without answering")  # pragma: no cover

    def _run_tool(self, call: ToolCall, scope: QueryScope, budget: list[int]) -> ChatMessage:
        if call.name == "get_schema":
            return data_message(_schema(), [], role="tool", tool_call_id=call.call_id)
        if budget[0] <= 0:
            return _tool_error(call, "No previews left for this question; answer now")
        budget[0] -= 1
        try:
            args = json.loads(call.arguments)
            sql = args["sql"] if isinstance(args, dict) else None
        except ValueError:
            sql = None
        if not isinstance(sql, str) or not sql.strip():
            return _tool_error(call, 'preview_query needs {"sql": "SELECT ..."}')
        try:
            res = self._engine.run(sql, scope, row_cap=PREVIEW_ROWS, timeout_s=PREVIEW_TIMEOUT_S)
        except AppError as exc:
            sources = self._engine.sources_in(scope)
            return data_message(
                {"error": str(exc)[:500]}, sources, role="tool", tool_call_id=call.call_id
            )
        return data_message(_rows(res), res.sources, role="tool", tool_call_id=call.call_id)

    # --- context and self-check ----------------------------------------------------------

    def _context(
        self, scope: QueryScope, history: list[AskTurn]
    ) -> tuple[dict[str, Any], list[str]]:
        values: dict[str, list[Any]] = {}
        sources = self._engine.sources_in(scope)
        for col in PROFILE_COLUMNS:
            sql = (
                f"SELECT {col} AS value, count(*) AS n FROM events WHERE {col} IS NOT NULL"  # noqa: S608  # fixed column names from the schema
                f" GROUP BY 1 ORDER BY 2 DESC LIMIT {PROFILE_MAX_DISTINCT + 1}"
            )
            try:
                res = self._engine.run(sql, scope, timeout_s=PROFILE_TIMEOUT_S)
            except AppError:
                continue
            if 0 < len(res.rows) <= PROFILE_MAX_DISTINCT:
                values[col] = [_cell(r[0]) for r in res.rows[:PROFILE_VALUES]]
        context = {
            "schema": _schema(),
            "sample_values": values,
            "unmapped_keys": self._unmapped_keys(scope),
            "time_range": {"start": _iso(scope.start), "end": _iso(scope.end)},
            "sources": sources,
            "earlier_turns": [
                {"question": t.question[:2_000], "sql": t.sql[:20_000]} for t in history[-3:]
            ],
        }
        return context, sources

    def _unmapped_keys(self, scope: QueryScope) -> dict[str, dict[str, list[Any] | None]]:
        """Per OCSF class, the top-level keys found in `unmapped`, with a few sample values
        when a key has few distinct values (None when it has many). Best effort."""
        try:
            res = self._engine.run(
                _UNMAPPED_SQL, scope, row_cap=UNMAPPED_KEYS, timeout_s=PROFILE_TIMEOUT_S
            )
        except AppError:
            return {}
        out: dict[str, dict[str, list[Any] | None]] = {}
        for class_uid, key, _, distinct, vals in res.rows:
            if not isinstance(key, str) or len(key) > 64:
                continue
            small = isinstance(vals, list) and int(distinct or 0) <= PROFILE_VALUES
            sample = [_cell(v) for v in vals[:UNMAPPED_VALUES]] if small else None
            label = "unclassified" if class_uid is None else str(class_uid)
            out.setdefault(label, {})[key] = sample
        return out

    def _check(
        self, sql: str, scope: QueryScope
    ) -> tuple[Literal["ok", "empty", "failed"], str | None, QueryResult | None]:
        try:
            res = self._engine.run(sql, scope, row_cap=PREVIEW_ROWS, timeout_s=PREVIEW_TIMEOUT_S)
        except AppError as exc:
            return "failed", str(exc)[:500], None
        if not res.rows:
            return "empty", "The query ran but matched no rows in this time range", res
        return "ok", None, res


def _schema() -> list[dict[str, str]]:
    return [{"name": c.name, "type": c.duckdb_type, "description": c.description} for c in COLUMNS]


def _tool_error(call: ToolCall, message: str) -> ChatMessage:
    return data_message({"error": message}, [], role="tool", tool_call_id=call.call_id)


def _rows(res: QueryResult) -> dict[str, Any]:
    """Preview rows with every value capped, then dropped from the end to fit the budget."""
    rows = [[_cell(v) for v in row] for row in res.rows]
    out: dict[str, Any] = {"columns": [_cell(c) for c in res.columns], "rows": rows}
    while rows and len(json.dumps(out, default=str)) > TOOL_RESULT_BYTES:
        rows.pop()
        out["truncated"] = True
    if len(json.dumps(out, default=str)) > TOOL_RESULT_BYTES:
        return {"error": "The preview was too large to show; select fewer or narrower columns"}
    return out


def _cell(value: Any, depth: int = 0) -> Any:
    """Cap strings, nested lists, and nested objects so one value cannot carry a source."""
    if isinstance(value, str):
        return value[:CELL_CAP] + "..." if len(value) > CELL_CAP else value
    if depth >= 3 and isinstance(value, list | tuple | dict):
        return "..."
    if isinstance(value, list | tuple):
        items = [_cell(v, depth + 1) for v in value[:ITEM_CAP]]
        return [*items, "..."] if len(value) > ITEM_CAP else items
    if isinstance(value, dict):
        keys = list(value)[:ITEM_CAP]
        capped = {_cell(str(k)): _cell(value[k], depth + 1) for k in keys}
        if len(value) > ITEM_CAP:
            capped["..."] = "..."
        return capped
    return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
