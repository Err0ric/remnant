"""Health and product metadata. Routers only, no business logic."""

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip, current_user
from app.auth.service import AuthService
from app.core.branding import PRODUCT_NAME
from app.core.build import full_version
from app.core.schema import COLUMNS, OCSF_VERSION, SCHEMA_VERSION

router = APIRouter(tags=["meta"])


def app_version() -> str:
    try:
        return version("app")
    except PackageNotFoundError:
        return "0.0.0"


class Health(BaseModel):
    status: str


class ColumnInfo(BaseModel):
    name: str
    type: str
    group: str
    description: str
    nullable: bool


class Meta(BaseModel):
    product_name: str
    version: str
    ocsf_version: str
    schema_version: int
    environment_label: str | None = None


@router.get("/health")
async def health() -> Health:
    return Health(status="ok")


@router.get("/meta")
async def meta(request: Request) -> Meta:
    config = getattr(request.app.state, "config", None)
    return Meta(
        product_name=PRODUCT_NAME,
        version=full_version(app_version()),
        ocsf_version=OCSF_VERSION,
        schema_version=SCHEMA_VERSION,
        environment_label=config.server.environment_label if config else None,
    )


class InstallOut(BaseModel):
    name: str


class InstallIn(BaseModel):
    # Shown as text in the top bar; letters, digits, spaces, and simple punctuation.
    name: str = Field(default="", max_length=40, pattern=r"^[\w .,&()'/-]*$")


def _install_name(request: Request) -> str:
    with request.app.state.meta.connect() as con:
        row = con.execute("SELECT name FROM install_settings WHERE id = 1").fetchone()
    return str(row[0]) if row else ""


@router.get("/install")
async def get_install(request: Request, _: CurrentUser) -> InstallOut:
    """The optional install name (ADR-0038 nav pass 2). Signed-in people only: it may name
    the organization, so the sign-in page never shows it."""
    return InstallOut(name=await run_in_threadpool(_install_name, request))


@router.put("/install")
async def put_install(request: Request, body: InstallIn, user: AdminUser) -> InstallOut:
    name = " ".join(body.name.split())

    def save() -> None:
        with request.app.state.meta.connect() as con:
            con.execute(
                "INSERT INTO install_settings (id, name, updated_at, updated_by)"
                " VALUES (1, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET name = excluded.name,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (name, datetime.now(UTC).isoformat(), user.user_id),
            )

    await run_in_threadpool(save)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "install.update", "success", user.user_id, client_ip(request),
        {"name": name},
    )  # fmt: skip
    return InstallOut(name=name)


@router.get("/schema/columns", dependencies=[Depends(current_user)])
async def columns() -> list[ColumnInfo]:
    return [
        ColumnInfo(
            name=c.name,
            type=c.type.value,
            group=c.group.value,
            description=c.description,
            nullable=c.nullable,
        )
        for c in COLUMNS
    ]
