"""Settings > Claude plugins (owner, 2026-10-29; SPEC D127): the hooks plugin per platform,
the named per-deployment tokens of each OTLP source, and what each variant has sent. Admin
only. Router only; tokens live in `app.ingest.otlp_tokens`."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from cryptography import x509
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from app.ai.claude_plugin import SCRIPT_SHA256
from app.ai.claude_plugin import VERSION as PLUGIN_VERSION
from app.ai.sessions import _ONE_COPY, _a
from app.api.access import AdminUser, client_ip
from app.auth.service import AuthService
from app.auth.tls import resolve_tls
from app.core.errors import ConfigError, NotFoundError
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


class MachineOut(BaseModel):
    host: str
    last_seen: str


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
    machines: list[MachineOut] = []  # each machine that sent with it, newest first (D170)
    last_error: str | None = None  # why the receiver last refused it
    last_error_at: str | None = None


class UnknownOut(BaseModel):
    prefix: str  # the first 8 characters only
    client: str
    first_at: str
    last_at: str
    count: int


class VariantOut(BaseModel):
    platform: str
    label: str
    script_sha256: str
    devices_24h: int
    last_event: str | None
    dropped_24h: int


class CertificateOut(BaseModel):
    """Whether a package should carry this server's self-signed certificate (owner,
    2026-11-02): only when the server serves its own generated certificate and people reach
    it directly. Behind a reverse proxy the proxy's certificate is the one clients see, and
    pinning this one would break every send."""

    self_signed: bool  # this server serves its generated self-signed certificate
    names: list[str]  # the DNS names and addresses that certificate is for
    behind_proxy: bool  # server.trusted_proxies is set
    include_by_default: bool
    reason: str


class PluginsOut(BaseModel):
    version: str
    variants: list[VariantOut]
    sources: list[dict[str, Any]]
    tokens: list[TokenOut]
    public_url: str | None
    certificate: CertificateOut | None = None
    # Refused tokens that match none of this server's, by prefix (D170): an old download.
    unknown_tokens: list[UnknownOut] = []


class NewToken(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class MadeToken(TokenOut):
    token: str = Field(description="Shown once, for an OpenTelemetry collector; never again")


LABELS = {"windows": "Claude Code for Windows", "posix": "Claude Code for macOS and Linux"}


def _out(t: Token) -> TokenOut:
    out = {k: getattr(t, k) for k in TokenOut.model_fields if k != "machines"}
    machines = [MachineOut(host=m.host, last_seen=m.last_seen) for m in t.machines]
    return TokenOut(**out, machines=machines)


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
        certificate=certificate(request),
        unknown_tokens=[
            UnknownOut(
                prefix=u.prefix,
                client=u.client,
                first_at=u.first_at,
                last_at=u.last_at,
                count=u.count,
            )
            for u in await run_in_threadpool(tokens.unknown)
        ],
    )


def certificate(request: Request) -> CertificateOut:
    config = request.app.state.config
    proxied = bool(config.server.trusted_proxies)
    try:
        tls = resolve_tls(config)
    except ConfigError:
        tls = None
    if tls is None or not tls.self_signed:
        return CertificateOut(
            self_signed=False,
            names=[],
            behind_proxy=proxied,
            include_by_default=False,
            reason="This server does not serve its own self-signed certificate.",
        )
    names = cert_names(tls.cert.read_bytes())
    public = request.app.state.public_url
    host = (urlsplit(public).hostname or "").lower() if public else ""
    if proxied:
        reason = (
            "Off: people reach this server through a reverse proxy, whose certificate is the"
            " one their computers check."
        )
    elif host and host not in names:
        reason = (
            f"Off: the public address ({host}) is not a name on this server's certificate,"
            " so another certificate answers there."
        )
    else:
        reason = "On: people reach this server directly, and it serves its own certificate."
    return CertificateOut(
        self_signed=True,
        names=names,
        behind_proxy=proxied,
        include_by_default=reason.startswith("On"),
        reason=reason,
    )


def cert_names(pem: bytes) -> list[str]:
    """DNS names and addresses in a certificate's subject alternative names, lower case."""
    cert = x509.load_pem_x509_certificate(pem)
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    names = [str(n).lower() for n in san.get_values_for_type(x509.DNSName)]
    names += [str(a) for a in san.get_values_for_type(x509.IPAddress)]
    return sorted(set(names))


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


class TestRecordOut(BaseModel):
    status: int  # the receiver's HTTP status
    ok: bool
    detail: str
    session_id: str  # the synthetic session, findable on Agents > Sessions (empty, hidden)


def test_payload(session_id: str, at: datetime) -> dict[str, Any]:
    """One synthetic SessionStart in the plugin's own OTLP shape (owner, 2026-11-02). No
    person, no host: it marks no device and names no one, and `test_record` keeps it out
    of Agents."""
    attrs = {
        "event_name": "claude_hooks.session_start",
        "role": "session",
        "session_id": session_id,
        "plugin_variant": "server_test",
        "test_record": "true",
    }
    record = {
        "timeUnixNano": str(int(at.timestamp()) * 1_000_000_000),
        "body": {"stringValue": "claude_hooks.session_start"},
        "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()],
    }
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": "claude-hooks"}}]}
    scope = {"scope": {"name": "claude-hooks"}, "logRecords": [record]}
    return {"resourceLogs": [{"resource": resource, "scopeLogs": [scope]}]}


@router.post("/sources/{source_id}/otlp-tokens/{token_id}/test")
async def send_test_record(
    source_id: str, token_id: str, request: Request, user: AdminUser
) -> TestRecordOut:
    """Post one synthetic SessionStart with this deployment's token through the real
    receiver (`POST /api/otlp/v1/logs`, in process) and report its HTTP result, so the
    server side can be checked without a client. Audited source.otlp_token (never the
    token)."""
    tokens: OtlpTokens = request.app.state.otlp_tokens
    owner, plain = await run_in_threadpool(tokens.plain, token_id)
    if owner != source_id:
        raise NotFoundError("No such token, or it was revoked")
    now = datetime.now(UTC)
    sid = f"server-test-{now.strftime('%Y%m%dT%H%M%SZ')}"
    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url=str(request.base_url)) as c:
        res = await c.post(
            "/api/otlp/v1/logs",
            json=test_payload(sid, now),
            headers={"Authorization": f"Bearer {plain}"},
        )
    ok = res.status_code == 200
    detail = "Accepted: the receiver took the record with this token." if ok else _reason(res)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "source.otlp_token",
        "success" if ok else "failure",
        user.user_id,
        client_ip(request),
        {"source_id": source_id, "token_id": token_id, "change": "test", "status": res.status_code},
    )
    return TestRecordOut(status=res.status_code, ok=ok, detail=detail, session_id=sid)


def _reason(res: httpx.Response) -> str:
    try:
        body = res.json()
    except ValueError:
        body = {}
    msg = body.get("detail") or body.get("message") if isinstance(body, dict) else None
    return f"Refused ({res.status_code}): {msg}" if msg else f"Refused ({res.status_code})"


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
