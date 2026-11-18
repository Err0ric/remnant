"""The server's own sign-ins, requests, and refusals in the lake (ADR-0040, handoff item 9).

The built-in source `server_events` is written through the OTLP spool like any pushed record
and parsed by the `server_events` template, so "who is this address" can be answered in
Logs, not only in the journal:

- refusals of a credential this server checks (`server.refused.*`, OCSF Authentication,
  failed): refused ingest tokens, sign-ins (passwords, rate limits, single sign-on), and
  API tokens. A built-in detection reads them (`app.search.refusals`).
- sign-ins that succeeded (`server.sign_in`, OCSF Authentication, success).
- requests that change something, send data out, or are refused (`server.request`, OCSF
  API Activity): the routes in RECORDED (sign-in and setup, users and tokens, exports and
  hand-offs, admin and settings changes), and any API request answered 401, 403, or 429.
  Never reads, even reads sent as POST (READ_ONLY: queries, counts, facets, search compile,
  Ask, Explain, previews; they stay in the audit log, rule 14), health polling, static
  assets, or machine pushes to the ingest endpoints (owner, 2026-11-10; #469 recorded every
  non-GET, so each search became an event).

Metadata only: time, user id and name, client address (as resolved through trusted
proxies), method, route template, status, and duration. Never a query string, a body, a
header, a cookie, a password, or a token (at most a token's id or its first 8 characters).

Rate-capped per budget (refusals and sign-ins share one, requests have their own, so a
burst of requests cannot crowd out a refusal): at most MAX_PER_MINUTE events a minute each;
past that they are counted and the count rides on the next event of that budget, so a flood
cannot fill the disk. Refusals are written at once; sign-ins and requests are queued in
memory (at most QUEUE_MAX) and written by `flush`, which the app runs every second, so a
request never waits on the disk.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog

from app.ingest.otlp import Spool, SpoolFullError, lines
from app.ingest.sources import SourceConfig, SourceStore

log = structlog.get_logger(__name__)

SOURCE_ID = "server_events"
SERVICE = "app-server"
MAX_PER_MINUTE = 300
QUEUE_MAX = 2 * MAX_PER_MINUTE
MAX_PATH = 200
# Never recorded: machine pushes (their refusals are) and the browser's own error reports.
SKIP_PREFIXES = ("/api/otlp/", "/api/client-errors")
# Denied or throttled: recorded on any API route, reads included.
DENIED = frozenset({401, 403, 429})

# What a request record is for, by (method, route template). A test lists every non-GET
# route and fails until a new one is on this list or on READ_ONLY.
RECORDED: frozenset[tuple[str, str]] = frozenset(
    {
        # Sign-in and setup
        ("POST", "/api/account/password"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/sso/start"),
        ("POST", "/api/settings/sso/test"),
        ("POST", "/api/setup"),
        # Users and tokens
        ("PUT", "/api/sources/{source_id}/credentials"),
        ("POST", "/api/sources/{source_id}/otlp-token"),
        ("POST", "/api/sources/{source_id}/otlp-tokens"),
        ("DELETE", "/api/sources/{source_id}/otlp-tokens/{token_id}"),
        ("POST", "/api/sources/{source_id}/otlp-tokens/{token_id}/test"),
        ("POST", "/api/tokens"),
        ("DELETE", "/api/tokens/{token_id}"),
        ("POST", "/api/users"),
        ("PATCH", "/api/users/{user_id}"),
        ("POST", "/api/users/{user_id}/reset"),
        ("POST", "/api/users/{user_id}/signout"),
        # Exports and data sent out
        ("POST", "/api/handoff"),
        ("POST", "/api/query/export"),
        ("GET", "/api/ai/inventory/export"),
        ("GET", "/api/audit/{log}/export"),
        ("GET", "/api/searches/{search_id}/export"),
        # Admin and settings changes
        ("DELETE", "/api/ai/inventory/exclusions"),
        ("PUT", "/api/ai/inventory/exclusions"),
        ("PUT", "/api/ai/mcp-rules"),
        ("POST", "/api/ai/services"),
        ("DELETE", "/api/ai/services/{service_id}"),
        ("PUT", "/api/ai/services/{service_id}/data-level"),
        ("PUT", "/api/ai/services/{service_id}/status"),
        ("PUT", "/api/ai/watch"),
        ("POST", "/api/alert-targets"),
        ("DELETE", "/api/alert-targets/{target_id}"),
        ("PATCH", "/api/alert-targets/{target_id}"),
        ("POST", "/api/alert-targets/{target_id}/test"),
        ("POST", "/api/alerts/close"),
        ("DELETE", "/api/alerts/mutes/{mute_id}"),
        ("POST", "/api/alerts/{item_id}/close"),
        ("POST", "/api/alerts/{item_id}/mute"),
        ("POST", "/api/alerts/{item_id}/reopen"),
        ("POST", "/api/dashboards"),
        ("DELETE", "/api/dashboards/{dashboard_id}"),
        ("PATCH", "/api/dashboards/{dashboard_id}"),
        ("POST", "/api/dashboards/{dashboard_id}/acknowledge"),
        ("PUT", "/api/dashboards/{dashboard_id}/layout"),
        ("PUT", "/api/dashboards/{dashboard_id}/order"),
        ("DELETE", "/api/dashboards/{dashboard_id}/panels/{schedule_id}"),
        ("PUT", "/api/dashboards/{dashboard_id}/panels/{schedule_id}"),
        ("PATCH", "/api/dashboards/{dashboard_id}/sections"),
        ("PUT", "/api/enrichment/feeds/{feed_id}"),
        ("POST", "/api/enrichment/feeds/{feed_id}/update"),
        ("POST", "/api/enrichment/feeds/{feed_id}/upload"),
        ("PUT", "/api/enrichment/places"),
        ("PUT", "/api/enrichment/settings"),
        ("POST", "/api/groups"),
        ("POST", "/api/groups/suggestions/accept"),
        ("DELETE", "/api/groups/{group_id}"),
        ("PATCH", "/api/groups/{group_id}"),
        ("PUT", "/api/groups/{group_id}/members"),
        ("PUT", "/api/groups/{group_id}/sources"),
        ("POST", "/api/health-checks/devices"),
        ("DELETE", "/api/health-checks/devices/{device_id}"),
        ("PUT", "/api/health-checks/devices/{device_id}"),
        ("PUT", "/api/identities/aliases"),
        ("PUT", "/api/identities/domains"),
        ("PUT", "/api/install"),
        ("PUT", "/api/integrity/settings"),
        ("POST", "/api/integrity/verify"),
        ("POST", "/api/library/{pack_id}/dashboard"),
        ("POST", "/api/library/{pack_id}/{query_id}/copy"),
        ("POST", "/api/library/{pack_id}/{query_id}/replace"),
        ("PUT", "/api/mcp/settings"),
        ("DELETE", "/api/pins/{kind}/{target_id}"),
        ("PUT", "/api/pins/{kind}/{target_id}"),
        ("POST", "/api/providers"),
        ("DELETE", "/api/providers/{provider_id}"),
        ("PATCH", "/api/providers/{provider_id}"),
        ("POST", "/api/providers/{provider_id}/test"),
        ("PUT", "/api/rules/builtin/refusals"),
        ("POST", "/api/rules/enabled"),
        ("POST", "/api/rules/import"),
        ("POST", "/api/rules/import/sigmahq"),
        ("POST", "/api/rules/import/upload"),
        ("POST", "/api/schedules"),
        ("DELETE", "/api/schedules/{schedule_id}"),
        ("PATCH", "/api/schedules/{schedule_id}"),
        ("POST", "/api/schedules/{schedule_id}/run"),
        ("POST", "/api/searches"),
        ("POST", "/api/searches/import"),
        ("DELETE", "/api/searches/{search_id}"),
        ("PUT", "/api/searches/{search_id}"),
        ("PUT", "/api/searches/{search_id}/verified"),
        ("PUT", "/api/settings/ask-time-limit"),
        ("PUT", "/api/settings/auditor-sql"),
        ("PUT", "/api/settings/backups"),
        ("PUT", "/api/settings/live"),
        ("POST", "/api/sources"),
        ("POST", "/api/sources/api/test"),
        ("POST", "/api/sources/loki/test"),
        ("DELETE", "/api/sources/{source_id}"),
        ("PATCH", "/api/sources/{source_id}"),
        ("PUT", "/api/sources/{source_id}/alert-notify"),
        ("POST", "/api/sources/{source_id}/reparse"),
        ("POST", "/api/sources/{source_id}/reparse/{job_id}/rules"),
        ("POST", "/api/sources/{source_id}/claude-plugin"),
        ("PUT", "/api/sources/{source_id}/watch"),
        ("POST", "/api/templates/drafts"),
        ("DELETE", "/api/templates/drafts/{template_id}"),
        ("PUT", "/api/templates/drafts/{template_id}"),
        ("POST", "/api/templates/drafts/{template_id}/ai-draft"),
        ("POST", "/api/templates/drafts/{template_id}/approve"),
        ("DELETE", "/api/templates/{template_id}"),
    }
)

# Reads sent as POST (or ending a read): never recorded unless denied.
READ_ONLY: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/ai/watch/check"),
        ("POST", "/api/ask"),
        ("POST", "/api/ask/jobs"),
        ("POST", "/api/ask/{ask_id}/answer"),
        ("POST", "/api/ask/{ask_id}/drill"),
        ("POST", "/api/ask/{ask_id}/jobs"),
        ("POST", "/api/ask/{ask_id}/run"),
        ("POST", "/api/explain"),
        ("POST", "/api/query"),
        ("POST", "/api/query/refine"),
        ("POST", "/api/rules/{rule_id}/run"),
        ("POST", "/api/search/compile"),
        ("POST", "/api/search/facets"),
        ("DELETE", "/api/search/live/streams/{stream_id}"),
        ("POST", "/api/searches/{search_id}/run"),
        ("POST", "/api/sources/discover"),
        ("POST", "/api/templates/drafts/{template_id}/preview"),
    }
)


def wanted(method: str, route: str, status: int, blocked: bool = False) -> bool:
    """A request worth a record: on RECORDED, denied, or a query the guard blocked
    (`blocked`: a statement, table function, or function it never allows; a plain SQL
    error is not recorded). `route` is the route template."""
    if not route.startswith("/api/") or route.startswith(SKIP_PREFIXES):
        return False
    return blocked or (method, route) in RECORDED or status in DENIED


class _Budget:
    """MAX_PER_MINUTE a minute; returns how many were dropped since the last one let through."""

    def __init__(self) -> None:
        self._minute = 0
        self._sent = 0
        self._dropped = 0

    def drop(self) -> None:
        self._dropped += 1

    def take(self) -> int | None:
        minute = int(time.monotonic() // 60)
        if minute != self._minute:
            self._minute, self._sent = minute, 0
        if self._sent >= MAX_PER_MINUTE:
            self.drop()
            return None
        self._sent += 1
        dropped, self._dropped = self._dropped, 0
        return dropped


class ServerEvents:
    def __init__(
        self,
        spool: Spool,
        sources: SourceStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._spool = spool
        self._sources = sources
        self._clock = clock
        self._lock = threading.Lock()
        self._security = _Budget()
        self._requests = _Budget()
        self._queue: list[dict[str, Any]] = []
        self._ready = False

    def ensure_source(self) -> None:
        """Create the built-in source once. Admin-only like any new source (Q4)."""
        if any(s.source_id == SOURCE_ID for s in self._sources.list()):
            self._ready = True
            return
        self._sources.add(
            SourceConfig(
                source_id=SOURCE_ID,
                format="json",
                kind="otlp",
                template_id="server_events",
                classification="local_only",
            )
        )
        self._ready = True

    def _record(self, event: str, attr: dict[str, Any], dropped: int) -> dict[str, Any]:
        attr = {k: v for k, v in attr.items() if v is not None and v != ""}
        attr["dropped_since_last"] = dropped
        return {
            "signal": "log",
            "time": self._clock().astimezone(UTC).isoformat(),
            "service": SERVICE,
            "event": event,
            "attr": attr,
            "resource": {"service_name": SERVICE},
        }

    def refused(self, event: str, client: str | None, **attrs: Any) -> None:
        """Record one refusal at once: `event` is otlp_token, sign_in, sso, or api_token."""
        with self._lock:
            dropped = self._security.take()
        if dropped is None:
            return
        attr = attrs | {"client": client or ""}
        self._write([self._record(f"server.refused.{event}", attr, dropped)])

    def signed_in(
        self, user_id: str | None, username: str | None, client: str | None, how: str, kind: str
    ) -> None:
        """Queue one successful sign-in (`how`: password or sso; `kind`: browser or cli)."""
        attr = {"outcome": "success", "user_id": user_id, "username": username,
                "client": client or "", "method": how, "session": kind}  # fmt: skip
        self._queue_record("server.sign_in", attr, self._security)

    def request(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        user_id: str | None,
        username: str | None,
        client: str | None,
    ) -> None:
        """Queue one request record; the caller passes the route template, never a query."""
        attr = {
            "outcome": "success" if status < 400 else "failure",
            "method": method,
            "path": path.split("?", 1)[0][:MAX_PATH],
            "status": status,
            "duration_ms": duration_ms,
            "user_id": user_id,
            "username": username,
            "client": client or "",
        }
        self._queue_record("server.request", attr, self._requests)

    def _queue_record(self, event: str, attr: dict[str, Any], budget: _Budget) -> None:
        with self._lock:
            if len(self._queue) >= QUEUE_MAX:  # the writer is stuck: count it as dropped
                budget.drop()
                return
            dropped = budget.take()
            if dropped is None:
                return
            self._queue.append(self._record(event, attr, dropped))

    def flush(self) -> int:
        """Write what is queued; returns how many records. Run off the event loop."""
        with self._lock:
            records, self._queue = self._queue, []
        if records:
            self._write(records)
        return len(records)

    def _write(self, records: list[dict[str, Any]]) -> None:
        try:
            if not self._ready:
                self.ensure_source()
            self._spool.append(SOURCE_ID, lines(records), self._clock().astimezone(UTC))
        except (SpoolFullError, OSError, ValueError) as exc:  # never fails the request
            log.warning("server_events.dropped", error=type(exc).__name__, count=len(records))
