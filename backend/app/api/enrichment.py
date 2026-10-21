"""/api/enrichment: feed status, the automatic update switch, update now, and upload
(ADR-0023). Everyone signed in reads the status (it is freshness, shown on Health);
admins change anything. Router only."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.access import AdminUser, CurrentUser, client_ip
from app.auth.service import AuthService
from app.core.errors import NotFoundError, ParamInvalidError, PayloadTooLargeError
from app.enrich.feeds import ATTRIBUTION, FEEDS, MAX_FILE, FeedState, FeedStore
from app.enrich.updater import FeedUpdater
from app.meta.secrets import SecretBox

router = APIRouter(tags=["enrichment"])
MAX_UPLOAD = MAX_FILE  # a gzip upload is smaller; the decompressed size is checked again


class FeedOut(BaseModel):
    feed_id: str
    kind: Literal["geoip", "intel"]
    label: str
    provider: str
    terms_url: str
    enabled: bool
    needs_key: bool
    has_key: bool
    downloadable: bool  # False for a list that is only uploaded
    level: Literal["healthy", "attention", "unhealthy", "missing"]
    version: str | None
    entries: int
    size: int
    source: str | None
    installed_at: str | None
    checked_at: str | None
    error: str | None
    check_every_s: int


class EnrichmentOut(BaseModel):
    auto_update: bool
    feeds: list[FeedOut]
    attribution: str
    attribution_url: str


class SettingsIn(BaseModel):
    auto_update: bool


class FeedSettingsIn(BaseModel):
    enabled: bool | None = None
    # A new key for a feed that needs one; "" removes it. Never returned.
    key: str | None = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9_-]*$")


def _store(request: Request) -> FeedStore:
    store: FeedStore = request.app.state.feeds
    return store


def _out(store: FeedStore, st: FeedState) -> FeedOut:
    spec = FEEDS[st.feed_id]
    return FeedOut(
        feed_id=st.feed_id,
        kind="intel" if spec.is_intel else "geoip",
        label=spec.label,
        provider=spec.provider,
        terms_url=spec.terms_url,
        enabled=st.enabled,
        needs_key=spec.needs_key,
        has_key=st.has_key,
        downloadable=bool(spec.host),
        level=store.level(st),
        version=st.version,
        entries=st.entries,
        size=st.size,
        source=st.source,
        installed_at=st.installed_at,
        checked_at=st.checked_at,
        error=st.error,
        check_every_s=spec.check_every_s,
    )


def _status(store: FeedStore) -> EnrichmentOut:
    return EnrichmentOut(
        auto_update=store.auto_update(),
        feeds=[_out(store, store.state(f)) for f in FEEDS],
        attribution=ATTRIBUTION[0],
        attribution_url=ATTRIBUTION[1],
    )


def _feed(feed_id: str) -> str:
    if feed_id not in FEEDS:
        raise NotFoundError("No such feed")
    return feed_id


@router.get("/enrichment")
async def status(request: Request, _: CurrentUser) -> EnrichmentOut:
    """Each feed's edition, age, and last check, and whether updates are automatic."""
    return await run_in_threadpool(_status, _store(request))


@router.put("/enrichment/settings")
async def save_settings(request: Request, body: SettingsIn, user: AdminUser) -> EnrichmentOut:
    """Turn automatic updates on or off (off on a fresh install). Audited."""
    store = _store(request)
    await run_in_threadpool(store.set_auto_update, body.auto_update, user.user_id)
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write,
        "enrichment.settings",
        "success",
        user.user_id,
        client_ip(request),
        {"auto_update": body.auto_update},
    )
    return await run_in_threadpool(_status, store)


@router.put("/enrichment/feeds/{feed_id}")
async def feed_settings(
    feed_id: str, body: FeedSettingsIn, request: Request, user: AdminUser
) -> FeedOut:
    """Switch a threat intel list on or off, or set its key (stored encrypted). Audited;
    the key itself is never logged or returned."""
    feed_id = _feed(feed_id)
    store = _store(request)
    detail: dict[str, object] = {"feed": feed_id}
    if body.enabled is not None:
        if not FEEDS[feed_id].is_intel:
            raise ParamInvalidError("Only threat intel lists can be switched off")
        await run_in_threadpool(store.set_enabled, feed_id, body.enabled)
        detail["enabled"] = body.enabled
    if body.key is not None:
        if not FEEDS[feed_id].needs_key:
            raise ParamInvalidError("This feed does not use a key")
        box = SecretBox(request.app.state.config.paths.data_dir)
        sealed = box.encrypt(body.key) if body.key else None
        await run_in_threadpool(store.set_key, feed_id, sealed)
        detail["key"] = "set" if body.key else "removed"
    auth: AuthService = request.app.state.auth
    await run_in_threadpool(
        auth.audit.write, "enrichment.feed", "success", user.user_id, client_ip(request), detail
    )
    return _out(store, await run_in_threadpool(store.state, feed_id))


@router.post("/enrichment/feeds/{feed_id}/update")
async def update_now(feed_id: str, request: Request, user: AdminUser) -> FeedOut:
    """Check one feed now and download a newer edition if there is one. Audited."""
    updater: FeedUpdater = request.app.state.feed_updater
    st = await run_in_threadpool(updater.update, _feed(feed_id), user.user_id)
    return _out(_store(request), st)


@router.post("/enrichment/feeds/{feed_id}/upload")
async def upload(feed_id: str, request: Request, user: AdminUser) -> FeedOut:
    """Install a file by hand, for networks that cannot reach the feed: an .mmdb (or the
    .mmdb.gz as downloaded) for GeoIP, a list for threat intel (one address, domain, URL,
    or hash per line; `value,description` also works). Checked before it replaces
    anything. Audited."""
    feed_id = _feed(feed_id)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD:
        raise PayloadTooLargeError("Uploads are limited to 100 MB")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_UPLOAD:
            raise PayloadTooLargeError("Uploads are limited to 100 MB")
    store = _store(request)
    auth: AuthService = request.app.state.auth
    try:
        st = await run_in_threadpool(store.install, feed_id, bytes(raw), "upload")
    except Exception as exc:
        await run_in_threadpool(
            auth.audit.write,
            "enrichment.upload",
            "failure",
            user.user_id,
            client_ip(request),
            {"feed": feed_id, "error": type(exc).__name__},
        )
        raise
    await run_in_threadpool(
        auth.audit.write,
        "enrichment.upload",
        "success",
        user.user_id,
        client_ip(request),
        {"feed": feed_id, "version": st.version, "sha256": st.sha256, "size": st.size},
    )
    return _out(store, st)
