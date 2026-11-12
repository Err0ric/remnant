"""Vendor alert limits and messages per source (ADR-0049 0b, D231).

Cap: a source may create at most CAP new alert items in any rolling hour. Past it the
source is paused: High and Critical alerts still raise (they skip the cap); Medium and
below are held, which means stored and searchable but not raised. The pause ends on its
own once the last hour is back under the cap, and one notice then says how long it lasted
and how many alerts were held, by severity. Health shows a pause while it lasts.

Notify: off by default, because vendors usually send their own messages. When an admin
turns it on for a source, a new vendor alert item, or a rise in an item's severity, goes
to the source's chosen targets if it is at or above the minimum severity (default High).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from app.auth.users import User
from app.core.errors import NotFoundError, ParamInvalidError
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

CAP = 100
WINDOW = timedelta(hours=1)
MAX_TARGETS = 10
Level = Literal["critical", "high", "medium", "low", "info"]
LEVELS: dict[str, int] = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
DEFAULT_MIN: Level = "high"


def level(severity_id: object) -> int:
    """OCSF severity_id to 1 (info) .. 5 (critical); 6 (fatal) counts as critical."""
    try:
        n = int(str(severity_id))
    except ValueError:
        return 1
    return max(1, min(n, 5))


def level_name(n: int) -> str:
    return next(k for k, v in LEVELS.items() if v == max(1, min(n, 5)))


@dataclass(frozen=True, slots=True)
class Notify:
    source_id: str
    notify: bool
    target_ids: list[str]
    min_severity: Level
    updated_at: str | None
    updated_by: str | None


@dataclass(frozen=True, slots=True)
class Pause:
    paused_since: str
    held: dict[str, int]  # severity name to count, only those with any


class ExternalAlertSettings:
    def __init__(
        self,
        meta: MetaDB,
        audit: AuditLog,
        source_ids: Callable[[], set[str]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._audit = audit
        self._source_ids = source_ids
        self._clock = clock

    # --- notify settings -------------------------------------------------------------------

    def get(self, source_id: str) -> Notify:
        with self._meta.connect() as con:
            r = con.execute(
                "SELECT * FROM external_alert_settings WHERE source_id = ?", (source_id,)
            ).fetchone()
        if r is None:
            return Notify(source_id, False, [], DEFAULT_MIN, None, None)
        return Notify(
            source_id,
            bool(r["notify"]),
            list(json.loads(r["target_ids"] or "[]")),
            cast(Level, r["min_severity"]),  # the table CHECKs the value
            r["updated_at"],
            r["updated_by"],
        )

    def set(
        self,
        source_id: str,
        notify: bool,
        target_ids: list[str],
        min_severity: str,
        actor: User,
        ip: str | None,
    ) -> Notify:
        if source_id not in self._source_ids():
            raise NotFoundError("No such source")
        if min_severity not in LEVELS:
            raise ParamInvalidError("Minimum severity must be critical, high, medium, low, or info")
        wanted = sorted(set(target_ids))
        if len(wanted) > MAX_TARGETS:
            raise ParamInvalidError(f"At most {MAX_TARGETS} alert targets")
        old = self.get(source_id)
        now = self._clock().astimezone(UTC).isoformat()
        with self._meta.connect() as con:
            known = {r[0] for r in con.execute("SELECT target_id FROM alert_targets")}
            if set(wanted) - known:
                raise ParamInvalidError("Unknown alert target")
            con.execute(
                "INSERT INTO external_alert_settings (source_id, notify, target_ids,"
                " min_severity, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (source_id) DO UPDATE SET notify = excluded.notify,"
                " target_ids = excluded.target_ids, min_severity = excluded.min_severity,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (source_id, int(notify), json.dumps(wanted), min_severity, now, actor.user_id),
            )
        new = self.get(source_id)
        self._audit.write(
            "source.vendor_alert_change",
            "success",
            actor.user_id,
            ip,
            {"source_id": source_id, "from": _setting(old), "to": _setting(new)},
        )
        return new

    # --- cap state -------------------------------------------------------------------------

    def pauses(self) -> dict[str, Pause]:
        """Sources paused by the cap right now, with what they have held so far."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT p.source_id, p.paused_since, h.severity, count(h.alert_id)"
                " FROM external_alert_pauses p LEFT JOIN external_alert_held h"
                " ON h.source_id = p.source_id AND h.held_at >= p.paused_since"
                " GROUP BY p.source_id, p.paused_since, h.severity"
            ).fetchall()
        out: dict[str, Pause] = {}
        for sid, since, sev, n in rows:
            p = out.setdefault(sid, Pause(since, {}))
            if sev is not None:
                p.held[sev] = int(n)
        return out


def _setting(n: Notify) -> dict[str, object]:
    return {"notify": n.notify, "targets": n.target_ids, "min_severity": n.min_severity}
