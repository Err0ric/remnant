"""The server's own security events in the lake (ADR-0040, owner 2026-10-30).

Every refusal of a credential this server checks becomes an event in a built-in source,
`server_events`, written through the OTLP spool like any pushed record and parsed by the
`server_events` template (OCSF Authentication, status failed): refused ingest tokens,
refused sign-ins (passwords, rate limits, single sign-on), and refused API tokens. A
built-in detection reads them (`app.search.refusals`).

Rate-capped: at most MAX_PER_MINUTE events a minute; past that they are counted and the
count rides on the next event, so a flood cannot fill the disk. Never a password or a
token: at most a token's id or its first 8 characters.
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
        self._minute = 0
        self._sent = 0
        self._dropped = 0
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

    def refused(self, event: str, client: str | None, **attrs: Any) -> None:
        """Record one refusal: `event` is otlp_token, sign_in, sso, or api_token."""
        now = self._clock().astimezone(UTC)
        with self._lock:
            minute = int(time.monotonic() // 60)
            if minute != self._minute:
                self._minute, self._sent = minute, 0
            if self._sent >= MAX_PER_MINUTE:
                self._dropped += 1
                return
            self._sent += 1
            dropped, self._dropped = self._dropped, 0
        attr = {k: v for k, v in attrs.items() if v is not None and v != ""}
        attr |= {"client": client or "", "dropped_since_last": dropped}
        record = {
            "signal": "log",
            "time": now.isoformat(),
            "service": SERVICE,
            "event": f"server.refused.{event}",
            "attr": attr,
            "resource": {"service_name": SERVICE},
        }
        try:
            if not self._ready:
                self.ensure_source()
            self._spool.append(SOURCE_ID, lines([record]), now)
        except (SpoolFullError, OSError, ValueError) as exc:  # never fails the request
            log.warning("server_events.dropped", error=type(exc).__name__)
