"""Settings > Claude plugins (owner, 2026-10-29; SPEC D127): the hooks plugin per platform,
the named per-deployment tokens of each OTLP source, and what each variant has sent. Admin
only. Router only; tokens live in `app.ingest.otlp_tokens`."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.ai.claude_plugin import SCRIPT_SHA256
from app.ai.claude_plugin import VERSION as PLUGIN_VERSION
from app.ai.sessions import _ONE_COPY, _a
from app.api.access import AdminUser, client_ip
from app.auth.service import AuthService
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.otlp_tokens import OtlpTokens, Token

router = APIRouter(tags=["plugins"])

# What each plugin variant sent in the last 24 hours (Health links from here).
STATUS_SQL = f"""
WITH {_ONE_COPY}
SELECT coalesce({_a("plugin_variant")}, 'posix') AS variant,
       count(DISTINCT device_hostname) AS devices,
       max(coalesce(time, time_observed)) AS last_event,
       coalesce(sum(TRY_CAST({_a("dropped_since_last")} AS BIGINT)), 0) AS dropped
FROM hooks
GROUP BY 1"""  # noqa: S608  # fixed SQL text


class TokenOut(BaseModel):
    token_id: str
    source_id: str
    name: str
    prefix: str
    created_at: str | None
    created_by: str | None
    revoked_at: str | None
    last_used_at: str | None
    devices: int
    hosts: list[str]
    downloadable: bool


class VariantOut(BaseModel):
    platform: str
    label: str
    script_sha256: str
    devices_24h: int
    last_event: str | None
    dropped_24h: int


class PluginsOut(BaseModel):
    version: str
    variants: list[VariantOut]
    sources: list[dict[str, Any]]
    tokens: list[TokenOut]
    public_url: str | None


class NewToken(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class MadeToken(TokenOut):
    token: str = Field(description="Shown once, for an OpenTelemetry collector; never again")


LABELS = {"windows": "Claude Code for Windows", "posix": "Claude Code for macOS and Linux"}


def _out(t: Token) -> TokenOut:
    return TokenOut(**{k: getattr(t, k) for k in TokenOut.model_fields})


@router.get("/plugins")
async def plugins(request: Request, _: AdminUser) -> PluginsOut:
    """Each plugin variant with its version, script hash, and the last 24 hours it sent;
    the OTLP sources; and every named token with the devices that used it."""
    srcs = [s for s in request.app.state.sources.list() if s.kind == "otlp"]
    tokens: OtlpTokens = request.app.state.otlp_tokens
    engine: QueryEngine = request.app.state.engine
    now = datetime.now(UTC)
    rows: list[list[Any]] = []
    if srcs:
        scope = QueryScope([s.source_id for s in srcs], now - timedelta(hours=24), now)

        def status() -> Any:
            return engine.run(STATUS_SQL, scope, timeout_s=20.0, name="plugins.status")

        res = await run_in_threadpool(status)
        rows = res.rows
    seen = {str(r[0]): r for r in rows}
    return PluginsOut(
        version=PLUGIN_VERSION,
        variants=[
            VariantOut(
                platform=p,
                label=LABELS[p],
                script_sha256=SCRIPT_SHA256[p],
                devices_24h=int(seen[p][1]) if p in seen else 0,
                last_event=str(seen[p][2]) if p in seen and seen[p][2] else None,
                dropped_24h=int(seen[p][3]) if p in seen else 0,
            )
            for p in ("windows", "posix")
        ],
        sources=[
            {"source_id": s.source_id, "keep_content": bool(s.otlp_keep_content)} for s in srcs
        ],
        tokens=[_out(t) for t in await run_in_threadpool(tokens.list)],
        public_url=request.app.state.public_url,
    )


@router.post("/sources/{source_id}/otlp-tokens")
async def new_token(source_id: str, body: NewToken, request: Request, user: AdminUser) -> MadeToken:
    """A named token for one deployment. Shown once (for a collector config); a plugin
    download carries it without showing it. Audited source.otlp_token (never the token)."""
    tokens: OtlpTokens = request.app.state.otlp_tokens
    made, plain = await run_in_threadpool(tokens.create, source_id, body.name, user.user_id)
    await _audit(request, "source.otlp_token", user.user_id, made, "create")
    return MadeToken(**_out(made).model_dump(), token=plain)


@router.delete("/sources/{source_id}/otlp-tokens/{token_id}")
async def revoke_token(
    source_id: str, token_id: str, request: Request, user: AdminUser
) -> TokenOut:
    """Revoke one deployment's token; other tokens keep working. Audited."""
    tokens: OtlpTokens = request.app.state.otlp_tokens
    gone = await run_in_threadpool(tokens.revoke, token_id, source_id, user.user_id)
    await _audit(request, "source.otlp_token", user.user_id, gone, "revoke")
    return _out(gone)


async def _audit(request: Request, action: str, user_id: str, t: Token, what: str) -> None:
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        action,
        "success",
        user_id,
        client_ip(request),
        {"source_id": t.source_id, "token_id": t.token_id, "name": t.name, "change": what},
    )
