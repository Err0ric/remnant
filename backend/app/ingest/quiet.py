"""Alerts when a source goes quiet (ADR-0014).

An administrator sets, per source, how long without received events counts as quiet and
which alert targets to tell. Every tick compares each watched source's last *received*
time (from ingest status, kept in the table so a restart does not lose it) with now. A
source sends one alert when it goes quiet and one when events resume; nothing in between.
Reads counts and times only, never event content, so no person's source access is used.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.alerts.dispatch import AlertDispatcher
from app.alerts.items import AlertItems
from app.alerts.render import Alert
from app.auth.users import User
from app.core.branding import PRODUCT_NAME
from app.core.errors import NotFoundError, ParamInvalidError
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

MIN_QUIET_S = 300  # 5 minutes
MAX_QUIET_S = 7 * 86400
MAX_TARGETS = 10
# Alert if quiet is on for every new source (ADR-0037 owner answer 3), with a default by kind:
# API connectors deliver late and in batches, so they get longer. Editable afterwards.
DEFAULT_QUIET_S = 3600
DEFAULT_QUIET_BY_KIND = {"m365": 3 * 3600, "anthropic": 3 * 3600}


def default_quiet_s(kind: str) -> int:
    return DEFAULT_QUIET_BY_KIND.get(kind, DEFAULT_QUIET_S)


@dataclass(frozen=True, slots=True)
class Watch:
    source_id: str
    quiet_after_s: int
    target_ids: list[str]
    state: str  # "ok" or "quiet"
    quiet_since: str | None
    last_seen: str | None
    updated_at: str
    updated_by: str | None


def human(seconds: float) -> str:
    """5 min, 2 h, 1 d 3 h: for alert text."""
    s = int(seconds)
    if s < 3600:
        return f"{max(1, s // 60)} min"
    if s < 86400:
        h, m = divmod(s // 60, 60)
        return f"{h} h" + (f" {m} min" if m else "")
    d, h = divmod(s // 3600, 24)
    return f"{d} d" + (f" {h} h" if h else "")


class QuietWatch:
    def __init__(
        self,
        meta: MetaDB,
        received: Callable[[], dict[str, datetime | None]],
        source_ids: Callable[[], set[str]],
        dispatcher: AlertDispatcher,
        audit: AuditLog,
        link: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        items: AlertItems | None = None,
    ) -> None:
        self._items = items
        self._meta = meta
        self._received = received
        self._source_ids = source_ids
        self._dispatcher = dispatcher
        self._audit = audit
        self._link = link
        self._clock = clock

    # --- settings --------------------------------------------------------------------------

    def all(self) -> list[Watch]:
        with self._meta.connect() as con:
            rows = con.execute("SELECT * FROM source_watches ORDER BY source_id").fetchall()
        return [_watch(r) for r in rows]

    def set(
        self,
        source_id: str,
        quiet_after_s: int | None,
        target_ids: list[str],
        actor: User,
        ip: str | None,
    ) -> Watch | None:
        """Turn the watch on or change it; `quiet_after_s=None` turns it off."""
        if source_id not in self._source_ids():
            raise NotFoundError("No such source")
        old = next((w for w in self.all() if w.source_id == source_id), None)
        now = self._clock().astimezone(UTC).isoformat()
        if quiet_after_s is None:
            with self._meta.connect() as con:
                con.execute("DELETE FROM source_watches WHERE source_id = ?", (source_id,))
            new = None
        else:
            if not MIN_QUIET_S <= quiet_after_s <= MAX_QUIET_S:
                raise ParamInvalidError("Quiet time must be between 5 minutes and 7 days")
            wanted = sorted(set(target_ids))
            if len(wanted) > MAX_TARGETS:
                raise ParamInvalidError(f"At most {MAX_TARGETS} alert targets")
            with self._meta.connect() as con:
                known = {r[0] for r in con.execute("SELECT target_id FROM alert_targets")}
                if set(wanted) - known:
                    raise ParamInvalidError("Unknown alert target")
                # A change restarts the clock from now, so turning a watch on for a source
                # that has been quiet for days does not alert the moment it is saved.
                con.execute(
                    "INSERT INTO source_watches (source_id, quiet_after_s, target_ids, state,"
                    " quiet_since, last_seen, created_at, updated_at, updated_by)"
                    " VALUES (?, ?, ?, 'ok', NULL, ?, ?, ?, ?)"
                    " ON CONFLICT (source_id) DO UPDATE SET quiet_after_s = excluded.quiet_after_s,"
                    " target_ids = excluded.target_ids, updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (source_id, quiet_after_s, json.dumps(wanted), now, now, now, actor.user_id),
                )
            new = next(w for w in self.all() if w.source_id == source_id)
        self._audit.write(
            "source.quiet_alert_change",
            "success",
            actor.user_id,
            ip,
            {
                "source_id": source_id,
                "from": _setting(old),
                "to": _setting(new),
            },
        )
        return new

    # --- checking --------------------------------------------------------------------------

    def tick(self) -> int:
        """Check every watch; returns how many changed state (and alerted)."""
        watches = self.all()
        if not watches:
            return 0
        known = self._source_ids()
        gone = [w.source_id for w in watches if w.source_id not in known]
        if gone:  # the source was deleted: its watch goes with it
            with self._meta.connect() as con:
                con.executemany(
                    "DELETE FROM source_watches WHERE source_id = ?", [(g,) for g in gone]
                )
            watches = [w for w in watches if w.source_id in known]
        now = self._clock().astimezone(UTC)
        received = self._received()
        changed = 0
        for w in watches:
            before = _parse(w.last_seen)
            seen = _latest(received.get(w.source_id), before)
            if seen is not None and seen != before:
                self._update(w.source_id, last_seen=seen.isoformat())
            if seen is None:
                continue
            quiet_for = (now - seen).total_seconds()
            if w.state == "ok" and quiet_for >= w.quiet_after_s:
                self._update(w.source_id, state="quiet", quiet_since=now.isoformat())
                self._alert(w, "quiet", f"No events received for {human(quiet_for)}", seen, now)
                changed += 1
            elif w.state == "quiet" and before is not None and seen > before:
                gap = (seen - before).total_seconds()
                self._update(w.source_id, state="ok", quiet_since=None)
                text = f"Events arriving again after {human(gap)}"
                if self._items is not None and w.quiet_since:
                    self._items.resolve("gap", f"{w.source_id}@{w.quiet_since}", text)
                self._alert(w, "resumed", text, seen)
                changed += 1
        return changed

    def _alert(
        self,
        w: Watch,
        kind: str,
        detail: str,
        seen: datetime | None,
        now: datetime | None = None,
    ) -> None:
        action = "source.quiet" if kind == "quiet" else "source.resumed"
        link = f"{self._link}/health#source={w.source_id}" if self._link else None
        if kind == "quiet" and self._items is not None and now is not None:
            # A gap on a watched source is an alert item (ADR-0037 owner answer 3).
            item = self._items.raise_item(
                "gap",
                w.source_id,
                f"{w.source_id} stopped sending",
                ref_id=f"{w.source_id}@{now.isoformat()}",
                detail=detail,
                sources=[w.source_id],
                range_start=seen.isoformat() if seen else None,
            )
            if item.state == "closed":
                kind = "muted"
            elif self._link:
                link = f"{self._link}/alerts#item={item.item_id}"
        self._audit.write(
            action,
            "success",
            None,
            None,
            {"source_id": w.source_id, "last_received": seen.isoformat() if seen else None},
        )
        if not w.target_ids or kind == "muted":
            return
        alert = Alert(
            kind="quiet" if kind == "quiet" else "resumed",
            title=w.source_id,
            detail=detail,
            count=None,
            reason=None,
            range_start=seen.isoformat() if seen else None,
            range_end=None,
            link=link,
            product=PRODUCT_NAME,
        )
        self._dispatcher.enqueue(alert, w.target_ids, None, None, source_id=w.source_id)

    def _update(self, source_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys are literals from this module
        with self._meta.connect() as con:
            con.execute(
                f"UPDATE source_watches SET {sets} WHERE source_id = ?",  # noqa: S608  # literal column names
                (*fields.values(), source_id),
            )


def _setting(w: Watch | None) -> dict[str, Any] | None:
    return None if w is None else {"quiet_after_s": w.quiet_after_s, "targets": w.target_ids}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _latest(*values: datetime | None) -> datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _watch(r: Any) -> Watch:
    return Watch(
        r["source_id"],
        int(r["quiet_after_s"]),
        list(json.loads(r["target_ids"] or "[]")),
        r["state"],
        r["quiet_since"],
        r["last_seen"],
        r["updated_at"],
        r["updated_by"],
    )
