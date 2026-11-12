"""A source storing events without its parser (ADR-0050 rows 5 and 6, slice 2).

When a source's configured template is not available, the source keeps storing its events
with the generic parser (slice 1). This module tells people, once each way:
- `source_fallback` to every alert target when a source starts storing without its parser,
  saying that rules and searches using the template's fields miss these events until they
  are reparsed;
- `source_fallback_cleared` when the template loads again, with how many events were
  stored without it.
No repeat while it lasts, across restarts (`source_fallbacks` in the metadata database).
Once cleared, the row stays with `cleared_at` set until a reparse of the source finishes, so
Sources can offer the reparse without reading the lake (review on #500). Both audited.
Messages carry the source and template ids and a count, never event content.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from app.alerts.render import Alert, AlertKind
from app.alerts.stops import DetectionStops
from app.core.branding import PRODUCT_NAME
from app.meta.audit import AuditLog
from app.meta.db import MetaDB


def fallback_error(source_id: str, template_id: str) -> str:
    """The words Health, Sources, and the start message use (ADR-0050 rows 4 and 6)."""
    return (
        f"Source {source_id} is storing events without its parser: template {template_id} is"
        " not available. Rules and searches that use its fields miss these events until"
        " they are reparsed."
    )


_EXACT = re.compile(
    r"Source [a-z0-9][a-z0-9_]{0,63} is storing events without its parser: template"
    r" [^\s:]+ is not available\. Rules and searches that use its fields miss these events"
    r" until they are reparsed\."
)


def is_fallback_error(text: str | None) -> bool:
    """Exactly the fallback text: an error that only contains the phrase (a file name in a
    "Cannot read" error, say) is not, so it is never shown unredacted or cleared by it."""
    return bool(text) and _EXACT.fullmatch(str(text)) is not None


class SourceFallbacks:
    def __init__(
        self,
        meta: MetaDB,
        stops: DetectionStops | None,
        audit: AuditLog | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        link: str | None = None,
    ) -> None:
        self._meta = meta
        self._stops = stops
        self._audit = audit
        self._clock = clock
        self._link = link

    def update(
        self, source_id: str, missing: str | None, stored: int, current: str | None = None
    ) -> None:
        """One pass of one source. `missing`: the template id it lacks now (None: it has its
        template or needs none). `stored`: events it wrote this pass without its parser
        (the template was missing when the pass started). `current`: its configured
        template now, for the cleared message when the source was switched."""
        now = self._clock()
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT template_id, since, events, cleared_at FROM source_fallbacks"
                " WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is not None and row[3] is not None:
                row = None  # cleared, kept for the reparse offer: not an outage now
            elif row is not None and missing == row[0]:
                con.execute(
                    "UPDATE source_fallbacks SET events = events + ? WHERE source_id = ?",
                    (max(0, stored), source_id),
                )
                return
            if row is None and missing is None:
                return
            if missing is not None:
                # A new outage, also after a cleared one: the row starts over.
                con.execute(
                    "INSERT INTO source_fallbacks (source_id, template_id, since, events)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (source_id) DO UPDATE SET"
                    " template_id = excluded.template_id, since = excluded.since,"
                    " events = excluded.events, cleared_at = NULL",
                    (source_id, missing, now.isoformat(), 0 if row is not None else max(0, stored)),
                )
            else:
                # Cleared: kept, with its count, until a reparse of the source is done.
                con.execute(
                    "UPDATE source_fallbacks SET cleared_at = ?, events = events + ?"
                    " WHERE source_id = ?",
                    (now.isoformat(), max(0, stored), source_id),
                )
        if row is not None:
            old, since = str(row[0]), str(row[1])
            events = int(row[2]) + (max(0, stored) if missing is None else 0)
            if missing is None and current == old:
                head = f"Template {old} loads again."
            else:
                now_uses = missing or current
                head = (
                    f"The source now uses template {now_uses} instead of {old}."
                    if now_uses
                    else f"The source no longer uses template {old}."
                )
            detail = (
                f"{head} {events} events were stored without {old}"
                f" since {since[:16].replace('T', ' ')} UTC; rules and searches that use its"
                " fields miss those events until they are reparsed."
            )
            self._send("source_fallback_cleared", source_id, detail, now, since)
            self._audit_row(
                "source.fallback_cleared",
                {"source_id": source_id, "template_id": old, "events": events},
            )
        if missing is not None:
            self._send("source_fallback", source_id, fallback_error(source_id, missing), now)
            self._audit_row("source.fallback", {"source_id": source_id, "template_id": missing})

    def reparse_offers(self) -> dict[str, str]:
        """Sources whose outage has cleared and whose events stored meanwhile are not
        reparsed yet, with the template they lacked. One small table read: Sources asks for
        the exact count only for these."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT source_id, template_id FROM source_fallbacks WHERE cleared_at IS NOT NULL"
            ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def reparsed(self, source_id: str, template_id: str) -> None:
        """A reparse of the source with that template finished: no offer left. An outage
        in progress keeps its row (its messages are not sent yet)."""
        with self._meta.connect() as con:
            con.execute(
                "DELETE FROM source_fallbacks WHERE source_id = ? AND template_id = ?"
                " AND cleared_at IS NOT NULL",
                (source_id, template_id),
            )

    def forget(self, keep: Iterable[str]) -> None:
        """Drop rows of sources that no longer exist or are turned off, without a message."""
        kept = set(keep)
        with self._meta.connect() as con:
            for (sid,) in con.execute("SELECT source_id FROM source_fallbacks").fetchall():
                if sid not in kept:
                    con.execute("DELETE FROM source_fallbacks WHERE source_id = ?", (sid,))

    def _send(
        self,
        kind: AlertKind,
        source_id: str,
        detail: str,
        now: datetime,
        since: str | None = None,
    ) -> None:
        if self._stops is None:
            return
        alert = Alert(
            kind=kind,
            title=f"Source {source_id}",
            detail=detail,
            count=None,
            reason=None,
            range_start=since or now.isoformat(),
            range_end=now.isoformat() if since else None,
            link=f"{self._link}/health#source={source_id}" if self._link else None,
            product=PRODUCT_NAME,
        )
        self._stops.notify(alert, (), source_id=source_id)  # every alert target (row 5)

    def _audit_row(self, action: str, detail: dict[str, object]) -> None:
        if self._audit is not None:
            self._audit.write(action, "success", None, detail=detail)
