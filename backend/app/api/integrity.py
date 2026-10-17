"""/api/integrity: log integrity status, verification, seals, and the report (ADR-0022).

Admins and auditors read the status and download the signed report; admins run a
verification now and choose where failures and daily seals go. Every call is audited
(`integrity.*`). Router only.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, client_ip, require_role
from app.auth.service import AuthService
from app.auth.users import User
from app.ingest.integrity import IntegrityLedger
from app.ingest.lakelock import lake_lock
from app.ops.integrity import IntegrityService

router = APIRouter(tags=["integrity"])
Reader = Annotated[User, Depends(require_role("admin", "auditor"))]


class FindingOut(BaseModel):
    severity: str
    kind: str
    path: str
    detail: str


class SealOut(BaseModel):
    seal_id: int
    at: str
    status: str
    lake_head: str
    lake_seq: int
    audit_head: str
    audit_rows: int
    files: int
    failures: int
    warnings: int
    findings: list[FindingOut]
    signature: str
    signature_ok: bool


class SettingsOut(BaseModel):
    target_ids: list[str]
    send_seals: bool
    updated_at: str | None


class StatusOut(BaseModel):
    latest: SealOut | None
    history: list[SealOut]  # newest first, findings left out
    lake_head: str
    lake_entries: int
    interval_s: float
    settings: SettingsOut


class SettingsIn(BaseModel):
    target_ids: list[str] = Field(default_factory=list, max_length=10)
    send_seals: bool = False


def _svc(request: Request) -> IntegrityService:
    svc: IntegrityService = request.app.state.integrity_service
    return svc


def _audit(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def _seal_out(svc: IntegrityService, seal: dict[str, Any], findings: bool = True) -> SealOut:
    return SealOut(
        **{**seal, "findings": seal["findings"] if findings else []},
        signature_ok=svc.check_seal(seal),
    )


@router.get("/integrity")
async def status(request: Request, user: Reader) -> StatusOut:
    """Latest seal with its findings, the last 30 days of seals, and the settings.
    Audited as integrity.view."""
    svc = _svc(request)
    seals = await run_in_threadpool(svc.seals, 30)
    head, seq = await run_in_threadpool(request.app.state.integrity.head)
    settings = await run_in_threadpool(svc.settings)
    await run_in_threadpool(
        _audit(request).audit.write, "integrity.view", "success", user.user_id, client_ip(request)
    )
    return StatusOut(
        latest=_seal_out(svc, seals[0]) if seals else None,
        history=[_seal_out(svc, s, findings=False) for s in seals[:60]],
        lake_head=head,
        lake_entries=seq,
        interval_s=request.app.state.config.maintenance.integrity_interval_s,
        settings=SettingsOut(**settings)
        if user.role == "admin"
        else SettingsOut(
            target_ids=[],
            send_seals=bool(settings["send_seals"]),
            updated_at=settings["updated_at"],
        ),
    )


def _verify_now(request: Request, user_id: str) -> dict[str, Any]:
    ledger: IntegrityLedger = request.app.state.integrity
    with lake_lock(request.app.state.lake_dir, wait=True):
        result = ledger.verify()
    return _svc(request).seal(result, user_id)


@router.post("/integrity/verify")
async def verify(request: Request, user: AdminUser) -> SealOut:
    """Run a verification now, under the lake lock so compaction and retention wait.
    Sealed, audited, and alerted the same way as the scheduled run."""
    seal = await run_in_threadpool(_verify_now, request, user.user_id)
    findings = (await run_in_threadpool(_svc(request).seals, 1))[0]["findings"]
    return _seal_out(_svc(request), {**seal, "findings": findings})


@router.get("/integrity/report")
async def report(
    request: Request, user: Reader, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> dict[str, Any]:
    """The signed integrity report for the last `days` days (ADR-0022 row 7). Audited as
    integrity.report."""
    return await run_in_threadpool(_svc(request).report, days, user.user_id)


@router.put("/integrity/settings")
async def save_settings(request: Request, body: SettingsIn, user: AdminUser) -> SettingsOut:
    """Where failures and the optional daily seal are sent. Targets must exist."""
    targets = request.app.state.alert_targets
    for target_id in body.target_ids:
        await run_in_threadpool(targets.get, target_id)  # raises NotFound
    svc = _svc(request)
    await run_in_threadpool(svc.save_settings, body.target_ids, body.send_seals, user.user_id)
    await run_in_threadpool(
        _audit(request).audit.write,
        "integrity.settings",
        "success",
        user.user_id,
        client_ip(request),
        {"target_ids": body.target_ids, "send_seals": body.send_seals},
    )
    return SettingsOut(**await run_in_threadpool(svc.settings))
