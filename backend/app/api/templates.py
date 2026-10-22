"""/api/templates: parser templates available to sources (SPEC 4). Router only."""

import contextlib
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.api.cancel import watch_disconnect
from app.auth.service import AuthService
from app.llm.parser_draft import ParserDrafter
from app.meta.audit import Outcome
from app.templates.drafts import Approval, Draft, DraftInfo, DraftStore, Preview, SampleKind
from app.templates.registry import TemplateRegistry
from app.templates.validator import Template

router = APIRouter(tags=["templates"])


class TemplateOut(BaseModel):
    id: str
    name: str
    version: str
    description: str
    category: str
    envelope: Literal["syslog", "none"]
    payload_format: str
    class_uid: int
    classification_default: Literal["local_only", "cloud_allowed"]


class ProblemOut(BaseModel):
    file: str
    message: str


def _out(t: Template) -> TemplateOut:
    return TemplateOut(
        id=t.id,
        name=t.name,
        version=t.version,
        description=t.description,
        category=t.category,
        envelope=t.envelope.type,
        payload_format=t.payload.format,
        class_uid=t.mapping.class_uid,
        classification_default=t.classification_default,
    )


def _registry(request: Request) -> TemplateRegistry:
    registry: TemplateRegistry = request.app.state.templates
    return registry


@router.get("/templates")
async def list_templates(request: Request, _: CurrentUser) -> list[TemplateOut]:
    return [_out(t) for t in _registry(request).all()]


@router.get("/templates/problems")
async def template_problems(request: Request, _: AdminUser) -> list[ProblemOut]:
    """Template files that were not loaded, and why. Admin only: names local paths."""
    return [ProblemOut(file=p.file, message=p.message) for p in _registry(request).problems]


# --- drafts (ADR-0005): Admin only, every change audited --------------------------------


class SampleIn(BaseModel):
    kind: SampleKind = "none"
    path: str | None = Field(default=None, max_length=4096)
    glob: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=300_000)

    @model_validator(mode="after")
    def _fits_kind(self) -> "SampleIn":
        if self.kind == "file" and not self.path:
            raise ValueError("a file sample needs a path")
        if self.kind == "pasted" and not self.text:
            raise ValueError("a pasted sample needs text")
        return self

    def row(self) -> tuple[SampleKind, str | None, str | None, str | None]:
        return (self.kind, self.path, self.glob, self.text)


class DraftCreate(BaseModel):
    template_id: str = Field(max_length=64)
    from_template: str | None = Field(default=None, max_length=64)
    sample: SampleIn = Field(default_factory=SampleIn)


class DraftUpdate(BaseModel):
    yaml: str | None = Field(default=None, max_length=300_000)
    sample: SampleIn | None = None


class PreviewIn(BaseModel):
    yaml: str | None = Field(default=None, max_length=300_000)


class SourceText(BaseModel):
    template_id: str
    yaml: str


def _drafts(request: Request) -> DraftStore:
    store: DraftStore = request.app.state.drafts
    return store


async def _audit(
    request: Request,
    action: str,
    user_id: str,
    detail: dict[str, Any],
    outcome: Outcome = "success",
) -> None:
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(auth.audit.write, action, outcome, user_id, client_ip(request), detail)


@contextlib.asynccontextmanager
async def _audited(
    request: Request, action: str, user_id: str, detail: dict[str, Any]
) -> AsyncIterator[None]:
    """Audit a change as success, or as failure when it raises (CLAUDE.md rule 14)."""
    try:
        yield
    except Exception:
        await _audit(request, action, user_id, detail, "failure")
        raise
    await _audit(request, action, user_id, detail)


@router.get("/templates/drafts")
async def list_drafts(request: Request, _: AdminUser) -> list[DraftInfo]:
    return await run_in_threadpool(_drafts(request).list_drafts)


@router.post("/templates/drafts", status_code=status.HTTP_201_CREATED)
async def create_draft(body: DraftCreate, request: Request, user: AdminUser) -> Draft:
    detail = {
        "template_id": body.template_id,
        "from": body.from_template,
        "sample": body.sample.kind,
    }
    async with _audited(request, "template.draft_create", user.user_id, detail):
        draft = await run_in_threadpool(
            _drafts(request).create,
            body.template_id,
            user.user_id,
            body.sample.row(),
            body.from_template,
        )
    return draft


@router.get("/templates/drafts/{template_id}")
async def get_draft(template_id: str, request: Request, _: AdminUser) -> Draft:
    return await run_in_threadpool(_drafts(request).get, template_id)


@router.put("/templates/drafts/{template_id}")
async def update_draft(
    template_id: str, body: DraftUpdate, request: Request, user: AdminUser
) -> Draft:
    detail = {
        "template_id": template_id[:64],
        "yaml": body.yaml is not None,
        "sample": body.sample is not None,
    }
    async with _audited(request, "template.draft_update", user.user_id, detail):
        draft = await run_in_threadpool(
            _drafts(request).update,
            template_id,
            body.yaml,
            body.sample.row() if body.sample else None,
        )
    return draft


@router.delete("/templates/drafts/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(template_id: str, request: Request, user: AdminUser) -> Response:
    detail = {"template_id": template_id[:64]}
    async with _audited(request, "template.draft_delete", user.user_id, detail):
        await run_in_threadpool(_drafts(request).delete, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/templates/drafts/{template_id}/preview")
async def preview_draft(
    template_id: str, body: PreviewIn, request: Request, _: AdminUser
) -> Preview:
    """Validate, run the tests, and parse the saved sample. Saves nothing."""
    return await run_in_threadpool(_drafts(request).preview, template_id, body.yaml)


class ApproveIn(BaseModel):
    # The sha256 from the preview the admin reviewed; a draft saved since is refused.
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/templates/drafts/{template_id}/approve")
async def approve_draft(
    template_id: str, body: ApproveIn, request: Request, user: AdminUser
) -> Approval:
    detail: dict[str, Any] = {"template_id": template_id[:64]}
    async with _audited(request, "template.approve", user.user_id, detail):
        approval = await run_in_threadpool(
            _drafts(request).approve, template_id, user.user_id, body.sha256
        )
        detail.update(version=approval.version, sha256=approval.sha256)
    return approval


class AiDraftIn(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64)


@router.post("/templates/drafts/{template_id}/ai-draft")
async def ai_draft(template_id: str, body: AiDraftIn, request: Request, user: AdminUser) -> Draft:
    """Ask a model for the payload, transforms, mapping, and tests. Inert until approved."""
    drafter: ParserDrafter = request.app.state.drafter
    detail: dict[str, Any] = {"template_id": template_id[:64], "provider_id": body.provider_id}
    async with _audited(request, "template.ai_draft", user.user_id, detail):
        try:
            async with watch_disconnect(request):
                draft = await run_in_threadpool(
                    drafter.draft, template_id, user.user_id, body.provider_id
                )
        except Exception as exc:
            detail["llm_call_id"] = getattr(exc, "call_id", None)  # joins to llm_calls
            raise
        detail["llm_call_id"] = draft.llm_call_id
    return draft


@router.get("/templates/{template_id}/source")
async def template_source(template_id: str, request: Request, _: AdminUser) -> SourceText:
    text = await run_in_threadpool(_drafts(request).template_source, template_id)
    return SourceText(template_id=template_id, yaml=text)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, request: Request, user: AdminUser) -> Response:
    detail = {"template_id": template_id[:64]}
    async with _audited(request, "template.delete", user.user_id, detail):
        await run_in_threadpool(_drafts(request).delete_template, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
