"""/api/providers: model providers, admin only (SPEC 6.1). Router only.

API keys are write-only: accepted, encrypted, never returned or logged.
"""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response, status
from pydantic import AfterValidator, BaseModel, Field, SecretStr, StringConstraints, field_validator
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, client_ip
from app.auth.service import AuthService
from app.core.config import AppConfig
from app.core.errors import CloudAckRequiredError, ProviderConfigError
from app.llm import gate
from app.llm.locality import provider_endpoint
from app.llm.provider import Locality
from app.llm.queue import DEFAULT_WAIT_S, slots_for
from app.llm.registry import ProviderRecord, ProviderStore

router = APIRouter(tags=["providers"])


def _check_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Use an http or https URL")
    if parts.username or parts.password:
        raise ValueError("Put credentials in the API key field, not the URL")
    if parts.query or parts.fragment:
        raise ValueError("The base URL cannot have a query or fragment")
    return value.rstrip("/")


BaseUrl = Annotated[str, StringConstraints(max_length=500), AfterValidator(_check_url)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Model = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


Reasoning = Literal["none", "low", "medium", "high"]


class ProviderOut(BaseModel):
    provider_id: str
    name: str
    kind: str
    base_url: str
    model: str
    enabled: bool
    has_api_key: bool
    locality: Locality
    # False: the host did not resolve, which is why it counts as cloud
    host_found: bool
    redact: bool  # ADR-0010: tokens instead of IPs, users, and hosts (cloud calls only)
    reasoning: Reasoning | None  # thinking control sent as reasoning_effort; None: default
    # ADR-0028: requests at once (None: 1 for local, no limit for cloud) and how long a
    # request waits for the model before "busy" (None: 120 s).
    max_concurrent: int | None
    wait_budget_s: int | None
    effective_slots: int | None  # what applies now; None: no queue
    effective_wait_s: int


class ProviderCreate(BaseModel):
    name: Name
    # openai_compat covers Ollama, LM Studio, vLLM, OpenAI and others; anthropic is the
    # Messages API and always counts as cloud (SPEC 6.1).
    kind: Literal["openai_compat", "anthropic"] = "openai_compat"
    base_url: BaseUrl
    model: Model = ""
    api_key: SecretStr | None = None
    acknowledge_cloud: bool = False


class ProviderUpdate(BaseModel):
    name: Name | None = None
    base_url: BaseUrl | None = None
    model: Model | None = None
    enabled: bool | None = None
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    acknowledge_cloud: bool = False
    redact: bool | None = None
    # "default" clears it (the model decides); others are sent as reasoning_effort.
    reasoning: Reasoning | Literal["default"] | None = None
    # 0 returns to the default.
    max_concurrent: int | None = Field(default=None, ge=0, le=16)
    wait_budget_s: int | None = Field(default=None, ge=0, le=600)

    @field_validator("wait_budget_s")
    @classmethod
    def _budget(cls, value: int | None) -> int | None:
        if value is not None and 0 < value < 10:
            raise ValueError("Wait at least 10 seconds, or 0 for the default (120)")
        return value


class HealthOut(BaseModel):
    ok: bool
    busy: bool = False  # answering another request: occupied, not down (ADR-0028)
    detail: str
    models: list[str] = Field(default_factory=list)


def _store(request: Request) -> ProviderStore:
    store: ProviderStore = request.app.state.providers
    return store


def _trusted(request: Request) -> list[str]:
    config: AppConfig = request.app.state.config
    return config.llm.trusted_local_hosts


def _out(r: ProviderRecord, trusted: list[str]) -> ProviderOut:
    endpoint = provider_endpoint(r.kind, r.base_url, trusted)
    return ProviderOut(
        provider_id=r.provider_id,
        name=r.name,
        kind=r.kind,
        base_url=r.base_url,
        model=r.model,
        enabled=r.enabled,
        has_api_key=r.has_api_key,
        locality=endpoint.locality,
        host_found=endpoint.host_found,
        redact=r.redact,
        reasoning=r.reasoning,  # type: ignore[arg-type]  # the column CHECK keeps it a Reasoning
        max_concurrent=r.max_concurrent,
        wait_budget_s=r.wait_budget_s,
        effective_slots=slots_for(r.max_concurrent, endpoint.locality == "local"),
        effective_wait_s=r.wait_budget_s or DEFAULT_WAIT_S,
    )


def _require_ack_for_cloud(kind: str, url: str, trusted: list[str], acknowledged: bool) -> None:
    cloud = provider_endpoint(kind, url, trusted).locality == "cloud"
    if cloud and urlsplit(url).scheme != "https":
        raise ProviderConfigError(
            "Cloud providers must use an https URL. For a server on your own network, use "
            "its private address or add its name to trusted local hosts"
        )
    if cloud and not acknowledged:
        raise CloudAckRequiredError(
            "This URL is a cloud provider. Data from local-only sources is always blocked from "
            "it; confirm to add it anyway"
        )


def _audit(request: Request, action: str, actor: AdminUser, detail: dict[str, object]) -> None:
    auth: AuthService = request.app.state.auth
    auth.audit.write(action, "success", actor.user_id, client_ip(request), detail)


@router.get("/providers")
async def list_providers(request: Request, _: AdminUser) -> list[ProviderOut]:
    trusted = _trusted(request)
    records = await run_in_threadpool(_store(request).all)
    return [await run_in_threadpool(_out, r, trusted) for r in records]


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def add_provider(body: ProviderCreate, request: Request, actor: AdminUser) -> ProviderOut:
    trusted = _trusted(request)
    await run_in_threadpool(
        _require_ack_for_cloud, body.kind, body.base_url, trusted, body.acknowledge_cloud
    )
    key = body.api_key.get_secret_value() if body.api_key else None
    r = await run_in_threadpool(
        _store(request).add, body.name, body.base_url, body.model, key, body.kind
    )
    await run_in_threadpool(
        _audit,
        request,
        "provider.create",
        actor,
        {
            "provider_id": r.provider_id,
            "name": r.name,
            "base_url": r.base_url,
            "has_api_key": r.has_api_key,
            "kind": r.kind,
        },
    )
    return await run_in_threadpool(_out, r, trusted)


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: str, body: ProviderUpdate, request: Request, actor: AdminUser
) -> ProviderOut:
    trusted = _trusted(request)
    if body.base_url is not None:
        current = await run_in_threadpool(_store(request).get, provider_id)
        await run_in_threadpool(
            _require_ack_for_cloud, current.kind, body.base_url, trusted, body.acknowledge_cloud
        )
    key = body.api_key.get_secret_value() if body.api_key else None
    r = await run_in_threadpool(
        _store(request).update,
        provider_id,
        body.name,
        body.base_url,
        body.model,
        body.enabled,
        key,
        body.clear_api_key,
        body.redact,
        None if body.reasoning is None else ("" if body.reasoning == "default" else body.reasoning),
        body.max_concurrent,
        body.wait_budget_s,
    )
    changed = body.model_dump(exclude={"api_key", "acknowledge_cloud"}, exclude_none=True)
    changed["api_key_changed"] = bool(key) or body.clear_api_key
    await run_in_threadpool(
        _audit, request, "provider.update", actor, {"provider_id": provider_id, **changed}
    )
    return await run_in_threadpool(_out, r, trusted)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: str, request: Request, actor: AdminUser) -> Response:
    await run_in_threadpool(_store(request).delete, provider_id)
    await run_in_threadpool(_audit, request, "provider.delete", actor, {"provider_id": provider_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, request: Request, _: AdminUser) -> HealthOut:
    store = _store(request)
    record = await run_in_threadpool(store.get, provider_id)
    h = await run_in_threadpool(gate.health, record, store, _trusted(request))
    return HealthOut(ok=h.ok, busy=h.busy, detail=h.detail, models=h.models)
