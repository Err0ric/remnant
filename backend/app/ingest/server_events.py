"""The server's own sign-ins, requests, and refusals in the lake (ADR-0040, handoff item 9).

The built-in source `server_events` is written through the OTLP spool like any pushed record
and parsed by the `server_events` template, so "who is this address" can be answered in
Logs, not only in the journal:

- refusals of a credential this server checks (`server.refused.*`, OCSF Authentication,
  failed): refused ingest tokens, sign-ins (passwords, rate limits, single sign-on), and
  API tokens. A built-in detection reads them (`app.search.refusals`).
- sign-ins that succeeded (`server.sign_in`, OCSF Authentication, success).
- requests that change something or export data (`server.request`, OCSF API Activity):
  every non-GET API request plus exports, never health polling, reads, static assets, or
  machine pushes to the ingest endpoints.

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
# Requests recorded besides every non-GET: exports read data out of the server.
EXPORT_SUFFIX = "/export"
# Never recorded: machine pushes (their refusals are) and the browser's own error reports.
SKIP_PREFIXES = ("/api/otlp/", "/api/client-errors")
READS = frozenset({"GET", "HEAD", "OPTIONS"})


def wanted(method: str, path: str) -> bool:
    """A request worth a record: an API change or an export, never a read or a push."""
    if not path.startswith("/api/") or path.startswith(SKIP_PREFIXES):
        return False
    return method not in READS or (method == "GET" and path.endswith(EXPORT_SUFFIX))


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
