"""/api/rules: imported Sigma rules (ADR-0006). Router only.

Admins import and enable or disable rules; every role can list them and read a rule's
YAML, because matches name the rule they came from. Admins and analysts run rules; runs
and matches are shown only to callers who may read every source the run read.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip, require_role
from app.auth.users import User
from app.detect.logsource import LogSource
from app.detect.runner import MatchRow, RuleRunner, RunRow
from app.detect.store import ImportReport, RuleRow, RuleStore

# ADR-0006 row 5: analysts run rules; auditors see runs and matches but do not start them.
RunnerUser = Annotated[User, Depends(require_role("admin", "analyst"))]

router = APIRouter(tags=["rules"])


class ImportIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class RefusalOut(BaseModel):
    path: str
    reason: str


class ImportOut(BaseModel):
    import_id: str
    path: str
    files: int
    accepted: int
    new_rules: int
    updated: int
    unchanged: int
    refused: int
    truncated: bool
    refusals: list[RefusalOut]  # first 200; the rest via /rules/imports/{id}/refusals


class RuleOut(BaseModel):
    rule_id: str
    title: str
    author: str
    level: str
    status: str
    product: str | None
    service: str | None
    category: str | None
    tags: list[str]
    path: str
    enabled: bool
    sha256: str
    import_id: str
    updated_at: str


class RuleListOut(RuleOut):
    # Sources this rule would read for the caller (their permitted sources whose template
    # declares a matching logsource); empty means a run would find no data.
    source_ids: list[str]


class RuleDetail(RuleOut):
    yaml: str


class EnableIn(BaseModel):
    rule_ids: list[str] = Field(min_length=1, max_length=10_000)
    enabled: bool


class EnableOut(BaseModel):
    changed: int


class ImportSummary(BaseModel):
    import_id: str
    path: str
    imported_by: str
    imported_at: str
    files: int
    accepted: int
    refused: int
    new_rules: int
    updated: int


class RunIn(BaseModel):
    start: datetime
    end: datetime


class RunOut(BaseModel):
    run_id: str
    rule_id: str
    sha256: str
    title: str
    author: str
    level: str
    started_by: str
    started_at: str
    range_start: str
    range_end: str
    status: str
    match_count: int
    matches_stored: int
    elapsed_ms: int
    sources_in_scope: list[str]
    error: str | None


class MatchOut(BaseModel):
    event_id: str
    event_time: str | None
    source_id: str


def _runner(request: Request) -> RuleRunner:
    runner: RuleRunner = request.app.state.rule_runner
    return runner


def _run_out(r: RunRow) -> RunOut:
    return RunOut(**{f: getattr(r, f) for f in RunOut.model_fields})


def _match_out(m: MatchRow) -> MatchOut:
    return MatchOut(event_id=m.event_id, event_time=m.event_time, source_id=m.source_id)


def _store(request: Request) -> RuleStore:
    store: RuleStore = request.app.state.rules
    return store


def _out(r: RuleRow) -> RuleOut:
    return RuleOut(**{f: getattr(r, f) for f in RuleOut.model_fields})


def _import_out(r: ImportReport) -> ImportOut:
    return ImportOut(
        import_id=r.import_id,
        path=r.path,
        files=r.files,
        accepted=r.accepted,
        new_rules=r.new_rules,
        updated=r.updated,
        unchanged=r.unchanged,
        refused=len(r.refusals),
        truncated=r.truncated,
        refusals=[RefusalOut(path=x.path, reason=x.reason) for x in r.refusals[:200]],
    )


@router.get("/rules")
async def list_rules(request: Request, user: CurrentUser) -> list[RuleListOut]:
    rows = await run_in_threadpool(_store(request).all)
    keys = {LogSource(r.product, r.service, r.category) for r in rows}
    by_ls = await run_in_threadpool(_runner(request).sources_by_logsource, keys, user)
    return [
        RuleListOut(
            **_out(r).model_dump(),
            source_ids=by_ls.get(LogSource(r.product, r.service, r.category), []),
        )
        for r in rows
    ]


@router.get("/rules/imports")
async def list_imports(request: Request, _: AdminUser) -> list[ImportSummary]:
    rows = await run_in_threadpool(_store(request).imports)
    return [ImportSummary.model_validate(r) for r in rows]


@router.get("/rules/imports/{import_id}/refusals")
async def import_refusals(import_id: str, request: Request, _: AdminUser) -> list[RefusalOut]:
    rows = await run_in_threadpool(_store(request).refusals, import_id)
    return [RefusalOut(path=r.path, reason=r.reason) for r in rows]


@router.get("/rules/runs")
async def list_runs(
    request: Request,
    user: CurrentUser,
    rule_id: Annotated[str | None, Query(max_length=300)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    rows = await run_in_threadpool(_runner(request).runs, user, rule_id, limit)
    return [_run_out(r) for r in rows]


@router.get("/rules/runs/{run_id}")
async def get_run(run_id: str, request: Request, user: CurrentUser) -> RunOut:
    return _run_out(await run_in_threadpool(_runner(request).get_run, run_id, user))


@router.get("/rules/runs/{run_id}/matches")
async def run_matches(run_id: str, request: Request, user: CurrentUser) -> list[MatchOut]:
    rows = await run_in_threadpool(_runner(request).matches, run_id, user)
    return [_match_out(m) for m in rows]


@router.post("/rules/{rule_id}/run")
async def run_rule(rule_id: str, body: RunIn, request: Request, user: RunnerUser) -> RunOut:
    row = await run_in_threadpool(
        _runner(request).run, rule_id, user, body.start, body.end, client_ip(request)
    )
    return _run_out(row)


@router.get("/rules/{rule_id}")
async def get_rule(rule_id: str, request: Request, _: CurrentUser) -> RuleDetail:
    row, text = await run_in_threadpool(_store(request).get, rule_id)
    return RuleDetail(**_out(row).model_dump(), yaml=text)


@router.post("/rules/import")
async def import_rules(body: ImportIn, request: Request, actor: AdminUser) -> ImportOut:
    report = await run_in_threadpool(
        _store(request).import_path, body.path, actor.user_id, client_ip(request)
    )
    return _import_out(report)


@router.post("/rules/enabled")
async def set_enabled(body: EnableIn, request: Request, actor: AdminUser) -> EnableOut:
    changed = await run_in_threadpool(
        _store(request).set_enabled,
        body.rule_ids,
        body.enabled,
        actor.user_id,
        client_ip(request),
    )
    return EnableOut(changed=changed)
