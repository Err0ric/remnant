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
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.alerts.dispatch import AlertDispatcher
from app.alerts.items import GAP_SEVERITY, AlertItems
from app.alerts.render import Alert
from app.auth.users import User
from app.core.branding import PRODUCT_NAME
from app.core.clock import utc_words
from app.core.errors import NotFoundError, ParamInvalidError, log_detail
from app.ingest.sources import inside_quiet_days
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

log = structlog.get_logger(__name__)

MIN_QUIET_S = 300  # 5 minutes
MAX_QUIET_S = 7 * 86400
MAX_TARGETS = 10
# How long a marked source's real last event is kept without a new read. It changes only when
# an event arrives, which the watch sees and which drops it at once; this only catches events
# the watch could not see (a reparse, a restore), and an hour is small against holds of days.
REAL_TTL = timedelta(hours=1)
# Alert if quiet is on for every new source (ADR-0037 owner answer 3), with a default by kind:
# API connectors deliver late and in batches, so they get longer. Editable afterwards.
DEFAULT_QUIET_S = 3600
DEFAULT_QUIET_BY_KIND = {"m365": 3 * 3600, "anthropic": 3 * 3600}


def default_quiet_s(kind: str) -> int:
    return DEFAULT_QUIET_BY_KIND.get(kind, DEFAULT_QUIET_S)


@dataclass(frozen=True, slots=True)
class LastEvent:
    """A source's newest event, from the lake: the time it is dated (at most when it
    arrived), which "Quiet is normal" counts from, and when its last record arrived."""

    newest: datetime
    received: datetime


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


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def quiet_text(real: LastEvent | None, seen: datetime, now: datetime) -> str:
    """What a quiet alert says. Usually the newest event arrived when it was dated (or the
    lake was not read): "No events received for 7 d", from the older of that event and the
    watch's own clock. When records arrived well after the newest event's date (an offline
    queue, an import), both times are named, so neither reads as the other."""
    if real is None or real.received - real.newest < timedelta(hours=1):
        start = real.newest if real is not None and real.newest < seen else seen
        return f"No events received for {human((now - start).total_seconds())}"
    return (
        f"No new events for {human((now - real.newest).total_seconds())}. Newest event dated"
        f" {utc_words(real.newest)}; last data arrived {utc_words(real.received)}."
    )


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
        quiet_days: Callable[[], dict[str, int | None]] = dict,
        last_event: Callable[[str, int, datetime], LastEvent | None] | None = None,
        shared: Callable[[], dict[str, str]] = dict,
    ) -> None:
        # Sources whose every file another source reads, and that source (SPEC 3.5): silent
        # by design, so their quiet alert never fires, and one already open is resolved.
        self._shared = shared
        self._items = items
        # Each source's "Quiet is normal for up to N days" (D260): its quiet alert is held
        # while the silence is inside those days, and fires once they pass (D262).
        self._quiet_days = quiet_days
        # The newest event a source really delivered, from the lake, as Health reads it.
        # Never the watch's own last_seen, which starts at the time the watch was turned on.
        self._last_event = last_event or (lambda _sid, _days, _now: None)
        # Per source: (that event, when it was read, the watch's last_seen then). Read once
        # when a marked source's alert first becomes due, and kept until an event arrives
        # or REAL_TTL passes. In memory: a restart reads it once again.
        self._real: dict[str, tuple[LastEvent | None, datetime, datetime]] = {}
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

    # --- one-time fixes ---------------------------------------------------------------------

    def retire_push_defaults(self) -> list[str]:
        """Once per install (D168, owner 2026-11-02): turn off the source-level quiet alert
        on existing push (OTLP) sources that still have the default an install gave them at
        creation. Claude Code telemetry and the hooks plugin send only while people use
        Claude Code, so that default alerted every evening. A watch someone changed (another
        quiet time, alert targets, or any later edit) is left alone. Each change is audited
        `source.quiet_alert_change` with no user and the reason. Returns the sources."""
        fix = "quiet_push_default_off"
        now = self._clock().astimezone(UTC).isoformat()
        changed: list[dict[str, Any]] = []
        with self._meta.connect() as con:
            if con.execute("SELECT 1 FROM one_time_fixes WHERE fix_id = ?", (fix,)).fetchone():
                return []
            rows = con.execute(
                "SELECT w.source_id, w.quiet_after_s, w.target_ids FROM source_watches w"
                " JOIN sources s ON s.source_id = w.source_id"
                " WHERE s.kind = 'otlp' AND w.quiet_after_s = ? AND w.target_ids = '[]'"
                " AND w.updated_at = w.created_at",
                (default_quiet_s("otlp"),),
            ).fetchall()
            for r in rows:
                con.execute("DELETE FROM source_watches WHERE source_id = ?", (r[0],))
                changed.append({"source_id": r[0], "from": {"quiet_after_s": r[1], "targets": []}})
            con.execute(
                "INSERT INTO one_time_fixes (fix_id, applied_at, changed) VALUES (?, ?, ?)",
                (fix, now, len(changed)),
            )
        for c in changed:
            self._audit.write(
                "source.quiet_alert_change",
                "success",
                None,
                None,
                {
                    "source_id": c["source_id"],
                    "from": c["from"],
                    "to": None,
                    "reason": "one-time fix: the default quiet alert is off for push sources",
                },
            )
        return [c["source_id"] for c in changed]

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
        days = {k: v for k, v in self._quiet_days().items() if v}
        shared = self._shared()
        changed = 0
        for w in watches:
            before = _parse(w.last_seen)
            seen = _latest(received.get(w.source_id), before)
            if seen is not None and seen != before:
                self._update(w.source_id, last_seen=seen.isoformat())
            if w.source_id in shared:
                if w.state == "quiet" and self._move(
                    w.source_id, "quiet", state="ok", quiet_since=None
                ):
                    text = (
                        f"Its files are read by source {shared[w.source_id]} now, so nothing is"
                        " expected from it"
                    )
                    if self._items is not None and w.quiet_since:
                        self._items.resolve(
                            "gap",
                            f"{w.source_id}@{w.quiet_since}",
                            text,
                            group=(w.source_id, "gap"),
                        )
                    self._alert(w, "resumed", text, seen or now)
                    changed += 1
                continue
            if seen is None:
                continue
            quiet_for = (now - seen).total_seconds()
            due = w.state == "ok" and quiet_for >= w.quiet_after_s
            # Held: the source is marked "Quiet is normal" and its newest real event is inside
            # its days (a source that never sent is never held). Nothing is stored for a hold,
            # so a restart reads the same, and the one ok-to-quiet move below raises it once
            # when the days pass or the mark is taken off (D262). A watch already quiet stays.
            real = self._real_last(w.source_id, days.get(w.source_id), seen, now) if due else None
            if real is not None and inside_quiet_days(days.get(w.source_id), real.newest, now):
                due = False
            if due:
                # One alert per source per quiet episode (owner 2026-11-02: two at the same
                # minute): only the tick that moves the row from ok to quiet alerts.
                if not self._move(w.source_id, "ok", state="quiet", quiet_since=now.isoformat()):
                    continue
                # The range starts at the newest event when it is known and older than the
                # watch's own clock (the watch's clock starts when the watch is turned on).
                start = real.newest if real is not None and real.newest < seen else seen
                self._alert(
                    w,
                    "quiet",
                    quiet_text(real, seen, now),
                    start,
                    now,
                    received=real.received if real is not None else None,
                    newest=real.newest if real is not None else None,
                )
                changed += 1
            elif w.state == "quiet" and before is not None and seen > before:
                gap = (seen - before).total_seconds()
                if not self._move(w.source_id, "quiet", state="ok", quiet_since=None):
                    continue
                text = f"Events arriving again after {human(gap)}"
                if self._items is not None and w.quiet_since:
                    self._items.resolve(
                        "gap", f"{w.source_id}@{w.quiet_since}", text, group=(w.source_id, "gap")
                    )
                self._alert(w, "resumed", text, seen)
                changed += 1
        return changed

    def _real_last(
        self, source_id: str, days: int | None, seen: datetime, now: datetime
    ) -> LastEvent | None:
        """The newest event this marked source really delivered, or None: not marked, never
        sent, or the read failed with nothing read earlier in this silence. Such a failed read
        holds nothing (never silent, D236): the alert is judged by its own threshold, and the
        other watches are checked as usual."""
        if not days:
            return None
        kept = self._real.get(source_id)
        if kept and kept[2] == seen and now - kept[1] < REAL_TTL:
            return kept[0]
        try:
            # A day past its days, so the alert that fires when they pass can still name it.
            found = self._last_event(source_id, days + 1, now)
        except Exception as exc:
            log.warning("quiet_watch.last_event_failed", source_id=source_id, **log_detail(exc))
            if kept and kept[2] == seen:
                # Read earlier in this same silence: that event is still the newest, so the
                # hold stands on it and the days are still counted from a real event.
                self._real[source_id] = (kept[0], now, seen)
                return kept[0]
            return None
        if found is None and kept and kept[2] == seen:
            found = kept[0]  # read earlier in this silence and since past the lookup
        self._real[source_id] = (found, now, seen)
        return found

    def _alert(
        self,
        w: Watch,
        kind: str,
        detail: str,
        seen: datetime | None,
        now: datetime | None = None,
        received: datetime | None = None,
        newest: datetime | None = None,
    ) -> None:
        """`seen` starts the alert's range (the newest event when known). The audit row keeps
        `last_received` as when a record last arrived and, when known, `newest_event`."""
        action = "source.quiet" if kind == "quiet" else "source.resumed"
        link = f"{self._link}/health#source={w.source_id}" if self._link else None
        severity: str | None = None
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
                group=(w.source_id, "gap"),
                severity=GAP_SEVERITY,  # every gap shows its severity (ADR-0043 row 15)
                change=detail,
            )
            severity = item.severity  # the message says what the alert says
            if item.state == "closed" or not (item.fresh or item.rose):
                kind = "muted"  # muted, or a repeat on today's open gap: not sent again
            elif self._link:
                link = f"{self._link}/alerts#item={item.item_id}"
        self._audit.write(
            action,
            "success",
            None,
            None,
            {
                "source_id": w.source_id,
                "last_received": _iso(received or seen),
                **({"newest_event": newest.isoformat()} if newest else {}),
            },
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
            severity=severity,
        )
        self._dispatcher.enqueue(alert, w.target_ids, None, None, source_id=w.source_id)

    def _move(self, source_id: str, from_state: str, **fields: Any) -> bool:
        """Change the row only if it is still in `from_state`; True when this call did."""
        sets = ", ".join(f"{k} = ?" for k in fields)  # keys are literals from this module
        with self._meta.connect() as con:
            cur = con.execute(
                f"UPDATE source_watches SET {sets} WHERE source_id = ? AND state = ?",  # noqa: S608  # literal column names
                (*fields.values(), source_id, from_state),
            )
            return cur.rowcount == 1

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
