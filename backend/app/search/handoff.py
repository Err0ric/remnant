"""Hand selected events to someone else's system through an alert target (ADR-0024).

The analyst picks up to MAX_EVENTS events they can already see, an alert target, and a
note. The events are read again here from the caller's own `events` view (rule 13), so
an id the caller cannot read is simply not found. Events from local_only sources go only
to a target whose every address is private (a webhook or mail server on the internal
network); for any other target they are withheld and counted. Webhooks get the events as
JSON (raw lines capped); chat and email get a short list with event ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.alerts.dispatch import AlertDispatcher
from app.alerts.render import Alert
from app.alerts.targets import TargetStore
from app.core.branding import PRODUCT_NAME
from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.audit import AuditLog

MAX_EVENTS = 100
EVENT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_RAW = 4096
MAX_VALUE = 512
COLUMNS = (
    "event_id",
    "time",
    "source_id",
    "classification",
    "severity_id",
    "class_uid",
    "message",
    "actor_user_name",
    "device_hostname",
    "src_endpoint_ip",
    "src_endpoint_port",
    "dst_endpoint_ip",
    "dst_endpoint_port",
    "dst_endpoint_hostname",
    "raw",
)


@dataclass(frozen=True, slots=True)
class HandoffResult:
    target_id: str
    sent: int
    withheld_local_only: int
    not_found: int


class HandoffService:
    def __init__(
        self,
        engine: QueryEngine,
        targets: TargetStore,
        dispatcher: AlertDispatcher,
        audit: AuditLog,
        link: str | None,
    ) -> None:
        self._engine = engine
        self._targets = targets
        self._dispatcher = dispatcher
        self._audit = audit
        self._link = link

    def send(
        self,
        user_id: str,
        username: str,
        scope: QueryScope,
        event_ids: list[str],
        target_id: str,
        note: str,
        ip: str | None,
    ) -> HandoffResult:
        ids = sorted({i.lower() for i in event_ids})
        if not ids or len(ids) > MAX_EVENTS:
            raise ParamInvalidError(f"Choose between 1 and {MAX_EVENTS} events to send")
        if not all(EVENT_ID.fullmatch(i) for i in ids):
            raise ParamInvalidError("Event ids must be UUIDs")
        target = self._targets.get(target_id)  # NotFoundError if it is gone
        events = self._fetch(ids, scope)
        private = self._targets.private(target_id)
        allowed = [e for e in events if private or e.get("classification") == "cloud_allowed"]
        withheld = len(events) - len(allowed)
        detail: dict[str, Any] = {
            "target_id": target_id,
            "target_kind": target.kind,
            "event_ids": [e["event_id"] for e in allowed],
            "withheld_local_only": withheld,
            "not_found": len(ids) - len(events),
            "sources_in_scope": sorted({str(e.get("source_id")) for e in allowed}),
        }
        if not allowed:
            self._audit.write("handoff.send", "denied", user_id, ip, detail)
            raise ParamInvalidError(
                "Nothing to send: the selected events are from local-only sources, and this"
                " target is outside your network"
                if withheld
                else "None of the selected events were found in the sources you can read"
            )
        alert = Alert(
            kind="handoff",
            title=f"Events from {username}"[:200],
            detail=note.strip()[:2000] or "No note",
            count=len(allowed),
            reason=f"{withheld} local-only events withheld" if withheld else None,
            range_start=None,
            range_end=None,
            link=f"{self._link}/search" if self._link else None,
            product=PRODUCT_NAME,
            events=tuple(allowed),
        )
        self._dispatcher.enqueue(alert, [target_id], None, None)
        self._audit.write("handoff.send", "success", user_id, ip, detail)
        return HandoffResult(target_id, len(allowed), withheld, len(ids) - len(events))

    def _fetch(self, ids: list[str], scope: QueryScope) -> list[dict[str, Any]]:
        listed = ", ".join(f"'{i}'" for i in ids)  # each one checked as a UUID above
        cols = ", ".join(f'"{c}"' for c in COLUMNS)
        result = self._engine.run(
            f"SELECT {cols} FROM events WHERE CAST(event_id AS VARCHAR) IN ({listed})"  # noqa: S608  # ids validated, columns fixed
            " ORDER BY coalesce(time, time_observed), event_id",
            scope,
            row_cap=MAX_EVENTS,
            intel=False,
        )
        out = []
        for row in result.rows:
            event: dict[str, Any] = {}
            for c, v in zip(result.columns, row, strict=True):
                if v is None:
                    continue
                if isinstance(v, str):
                    v = v[: MAX_RAW if c == "raw" else MAX_VALUE]
                event[c] = v
            event["event_id"] = str(event.get("event_id", ""))
            out.append(event)
        return out
