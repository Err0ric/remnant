"""/api/audit: the audit log viewer and export (Slice 5). Router only.

Admins and auditors read the activity log and the AI call log (SPEC 3.6). Reading is
itself recorded (`audit.view`, `audit.export`) with the filters used, so who looked at
the trail is on the trail. Prompt and response bodies are never returned.
"""

import json
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.access import client_ip, require_role
from app.auth.users import User
from app.core.errors import ParamInvalidError
from app.engine.export import to_csv
from app.meta.audit import MAX_PAGE, AuditFilter, AuditReader

router = APIRouter(tags=["audit"])
Reader = Annotated[User, Depends(require_role("admin", "auditor"))]
EXPORT_ROWS = 50_000


class AuditRowOut(BaseModel):
    audit_id: int
    ts: str
    user_id: str | None
    username: str | None
    action: str
    outcome: str
    ip: str | None
    detail: dict[str, Any]


class LlmCallOut(BaseModel):
    call_id: str
    ts: str
    user_id: str
    username: str | None
    provider_id: str
    model: str
    locality: str
    purpose: str
    prompt_ref: str
    sources_in_scope: list[str]
    classification_result: str
    redaction_applied: bool
    redaction_counts: dict[str, int] | None
    prompt_sha256: str | None
    response_sha256: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    queue_wait_ms: int | None = None  # ADR-0028: time waiting for the model
    busy_retries: int | None = None
    citation_check: str | None
    error: str | None
    finished_at: str | None
    provider_name: str | None = None
    chain_hash: str | None = None


class Filters:
    def __init__(
        self,
        action: Annotated[str | None, Query(max_length=100)] = None,
        user_id: Annotated[str | None, Query(max_length=64)] = None,
        outcome: Annotated[
            Literal["success", "failure", "denied", "blocked"] | None, Query()
        ] = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> None:
        for value in (since, until):
            if value is not None and value.tzinfo is None:
                raise ParamInvalidError("since and until need a time zone, for example Z")
        self.value = AuditFilter(action, user_id, outcome, since, until)

    def detail(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self.value).items() if v is not None}


Filtered = Annotated[Filters, Depends()]


def _reader(request: Request) -> AuditReader:
    reader: AuditReader = request.app.state.audit_reader
    return reader


async def _record(request: Request, user: User, action: str, detail: dict[str, Any]) -> None:
    await run_in_threadpool(
        request.app.state.auth.audit.write,
        action,
        "success",
        user.user_id,
        client_ip(request),
        detail,
    )


@router.get("/audit/events")
async def events(
    request: Request,
    user: Reader,
    f: Filtered,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
) -> list[AuditRowOut]:
    rows = await run_in_threadpool(_reader(request).events, f.value, before, limit)
    await _record(request, user, "audit.view", {"log": "activity", **f.detail()})
    return [AuditRowOut(**asdict(r)) for r in rows]


@router.get("/audit/llm-calls")
async def llm_calls(
    request: Request,
    user: Reader,
    f: Filtered,
    before_ts: Annotated[str | None, Query(max_length=64)] = None,
    before_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
) -> list[LlmCallOut]:
    before = (before_ts, before_id) if before_ts and before_id else None
    rows = await run_in_threadpool(_reader(request).llm_calls, f.value, before, limit)
    await _record(request, user, "audit.view", {"log": "llm_calls", **f.detail()})
    return [LlmCallOut(**asdict(r)) for r in rows]


def _all_events(reader: AuditReader, f: AuditFilter) -> tuple[list[str], list[list[Any]]]:
    out: list[list[Any]] = []
    before: int | None = None
    while len(out) < EXPORT_ROWS:
        page = reader.events(f, before, MAX_PAGE)
        if not page:
            break
        out.extend(
            [
                r.audit_id,
                r.ts,
                r.username or r.user_id,
                r.action,
                r.outcome,
                r.ip,
                json.dumps(r.detail, sort_keys=True),
            ]
            for r in page
        )
        before = page[-1].audit_id
    cols = ["audit_id", "time", "user", "action", "outcome", "ip", "detail"]
    return cols, out[:EXPORT_ROWS]


def _all_calls(reader: AuditReader, f: AuditFilter) -> tuple[list[str], list[list[Any]]]:
    out: list[list[Any]] = []
    before: tuple[str, str] | None = None
    fields = list(LlmCallOut.model_fields)
    while len(out) < EXPORT_ROWS:
        page = reader.llm_calls(f, before, MAX_PAGE)
        if not page:
            break
        out.extend([getattr(r, k) for k in fields] for r in page)
        before = (page[-1].ts, page[-1].call_id)
    return fields, out[:EXPORT_ROWS]


@router.get("/audit/{log}/export")
async def export(
    log: Literal["events", "llm-calls"], request: Request, user: Reader, f: Filtered
) -> Response:
    """CSV of everything matching the filters, newest first, at most 50,000 rows."""
    reader = _reader(request)
    builder = _all_events if log == "events" else _all_calls
    columns, rows = await run_in_threadpool(builder, reader, f.value)
    await _record(request, user, "audit.export", {"log": log, "rows": len(rows), **f.detail()})
    name = "audit-activity.csv" if log == "events" else "audit-ai-calls.csv"
    return Response(
        content=to_csv(columns, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
