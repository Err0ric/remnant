"""Health and product metadata. Routers only, no business logic."""

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.access import current_user
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
