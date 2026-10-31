"""Keeping enrichment files current (ADR-0023 rows 3 to 5).

Off on a fresh install. When an admin turns it on, each feed is checked on its own
interval. GeoIP editions are monthly: a check for the month already installed makes no
request at all; otherwise one download of the new edition, or a 404 meaning it is not
published yet. Downloads go only to the feed's fixed host, through the configured proxy.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
import structlog

from app.alerts.net import egress
from app.core.errors import AppError
from app.enrich import intel
from app.enrich.feeds import (
    FEEDS,
    FEODO_URL,
    MAX_FILE,
    THREATFOX_URL,
    FeedState,
    FeedStore,
    dbip_url,
)
from app.meta.audit import AuditLog

log = structlog.get_logger(__name__)

TIMEOUT_S = 60.0
ClientFactory = Callable[[], httpx.Client]


class FeedDownloadError(Exception):
    """A download that cannot be used; recorded on the feed, never raised to callers."""


def default_client() -> httpx.Client:
    out = egress()
    return httpx.Client(
        timeout=TIMEOUT_S,
        verify=out.verify(),
        proxy=out.proxy(),
        follow_redirects=False,  # a redirect could leave the fixed host
        headers={"User-Agent": "log-enrichment-updater"},
    )


class FeedUpdater:
    def __init__(
        self,
        store: FeedStore,
        audit: AuditLog,
        client: ClientFactory = default_client,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        key: Callable[[str], str | None] = lambda _feed: None,
        intel_every_s: int | None = None,
    ) -> None:
        self._store = store
        self._audit = audit
        self._client = client
        self._clock = clock
        self._not_modified = False  # the last download answered 304 Not Modified
        self._key = key  # the feed's key, decrypted when needed; never logged
        self._intel_every = intel_every_s
        self._lock = threading.Lock()  # one update at a time (scheduler and Update now)

    def run_due(self) -> list[FeedState]:
        """Called every few minutes; does nothing unless automatic updates are on."""
        if not self._store.auto_update():
            return []
        done = []
        now = self._clock()
        for feed_id, spec in FEEDS.items():
            if not spec.host:
                continue  # uploaded lists only
            st = self._store.state(feed_id)
            if not st.enabled or (spec.needs_key and not st.has_key):
                continue
            every = (
                (self._intel_every or spec.check_every_s) if spec.is_intel else spec.check_every_s
            )
            if st.checked_at is not None:
                last = datetime.fromisoformat(st.checked_at)
                if (now - last).total_seconds() < every:
                    continue
            done.append(self.update(feed_id, None))
        return done

    def update(self, feed_id: str, user_id: str | None) -> FeedState:
        """Check one feed now; download only if there is something new."""
        with self._lock:
            return self._update(feed_id, user_id)

    def _update(self, feed_id: str, user_id: str | None) -> FeedState:
        spec = FEEDS[feed_id]
        st = self._store.state(feed_id)
        try:
            if not spec.host:
                raise FeedDownloadError("This list is uploaded, not downloaded")
            if spec.needs_key and not st.has_key:
                raise FeedDownloadError("Add a free abuse.ch Auth-Key first")
            if feed_id == "intel_feodo":
                new = self._feodo(st)
            elif feed_id == "intel_threatfox":
                new = self._threatfox(st)
            else:
                new = self._geoip(st)
            if new is None:
                return self._store.state(feed_id)
        except (httpx.HTTPError, AppError, OSError, FeedDownloadError) as exc:
            reason = _reason(exc)
            log.warning("enrichment.update_failed", feed=feed_id, reason=reason)
            self._audit.write(
                "enrichment.update", "failure", user_id, None, {"feed": feed_id, "error": reason}
            )
            return self._store.record_check(feed_id, reason)
        self._audit.write(
            "enrichment.update",
            "success",
            user_id,
            None,
            {"feed": feed_id, "version": new.version, "sha256": new.sha256, "size": new.size},
        )
        log.info("enrichment.updated", feed=feed_id, version=new.version)
        return new

    def _geoip(self, st: FeedState) -> FeedState | None:
        """A monthly edition: no request when this month's is installed; a 404 means it is
        not published yet."""
        spec = FEEDS[st.feed_id]
        month = self._clock().strftime("%Y-%m")
        if st.source == "download" and st.version == month:
            self._store.record_check(st.feed_id, None, current=True)
            return None
        got = self._download(self._fixed(spec.feed_id, dbip_url(spec, month)))
        if got is None:
            self._store.record_check(
                st.feed_id, None if st.installed_at else f"The {month} edition is not out yet"
            )
            return None
        return self._store.install(st.feed_id, got[0], "download", version=month)

    def _feodo(self, st: FeedState) -> FeedState | None:
        """A conditional GET: an unchanged list costs one small request."""
        headers = {}
        if st.installed_at and st.etag:
            headers["If-None-Match"] = st.etag
        if st.installed_at and st.last_modified:
            headers["If-Modified-Since"] = st.last_modified
        got = self._download(self._fixed(st.feed_id, FEODO_URL), headers)
        if got is None:
            # 304: the installed list is the latest. 404: the list moved; say so.
            moved = not self._not_modified
            self._store.record_check(
                st.feed_id,
                "The feed server answered HTTP 404" if moved else None,
                current=not moved,
            )
            return None
        raw, etag, modified = got
        return self._store.install(st.feed_id, raw, "download", etag=etag, last_modified=modified)

    def _threatfox(self, st: FeedState) -> FeedState | None:
        """The last day's additions (a week's on first run), merged into a rolling list."""
        key = self._key(st.feed_id)
        if not key:
            raise FeedDownloadError("Add a free abuse.ch Auth-Key first")
        now = self._clock()
        recent = st.installed_at and (now - datetime.fromisoformat(st.installed_at)).days < 1
        body = {"query": "get_iocs", "days": 1 if recent else 7}
        url = self._fixed(st.feed_id, THREATFOX_URL)
        with self._client() as client:
            res = client.post(url, json=body, headers={"Auth-Key": key})
        if res.status_code in (401, 403):
            raise FeedDownloadError(
                "abuse.ch refused the Auth-Key; check it on the Enrichment page"
            )
        if res.status_code != 200:
            raise FeedDownloadError(f"The feed server answered HTTP {res.status_code}")
        if len(res.content) > MAX_FILE:
            raise FeedDownloadError("The download is larger than 100 MB")
        try:
            new, _bad = intel.parse_threatfox(res.content)
        except ValueError as exc:
            raise FeedDownloadError(str(exc)) from exc
        old = intel.read_parquet(self._store.path(st.feed_id))
        rows = intel.merge_recent(old, new, now)
        return self._store.install_intel(st.feed_id, rows, "download")

    def _fixed(self, feed_id: str, url: str) -> str:
        if urlsplit(url).hostname != FEEDS[feed_id].host:  # the fixed host list, checked again
            raise FeedDownloadError("Feed URL outside its fixed host")
        return url

    def _download(
        self, url: str, headers: dict[str, str] | None = None
    ) -> tuple[bytes, str | None, str | None] | None:
        """The body with its ETag and Last-Modified, or None for 304 and 404."""
        with self._client() as client, client.stream("GET", url, headers=headers) as res:
            self._not_modified = res.status_code == 304
            if res.status_code in (404, 304):
                return None
            if res.status_code != 200:
                raise FeedDownloadError(f"The feed server answered HTTP {res.status_code}")
            return _capped(res), res.headers.get("etag"), res.headers.get("last-modified")


def _capped(res: httpx.Response) -> bytes:
    declared = res.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE:
        raise FeedDownloadError("The download is larger than 100 MB")
    out = bytearray()
    for chunk in res.iter_bytes():  # decoded as it streams, so the cap also bounds gzip
        out += chunk
        if len(out) > MAX_FILE:
            raise FeedDownloadError("The download is larger than 100 MB")
    return bytes(out)


def _reason(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "The feed server did not answer in time"
    if isinstance(exc, httpx.HTTPError):
        return "Could not reach the feed server (check the network or proxy settings)"
    return str(exc)[:300] or type(exc).__name__
