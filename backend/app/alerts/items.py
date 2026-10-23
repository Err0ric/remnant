"""Alert items: one queue for everything that fires and needs a decision (ADR-0037).

An item is written when the thing happens: a flagged schedule run, a scheduled rule run with
matches, an AI Watch alert, or a gap on a source with Alert if quiet on. It stays open until
someone closes it with a reason; it can be reopened, and its history is kept.

Visibility follows the thing that fired: a schedule's items are seen by its owner, by
everyone when it is shared, and by admins; items the system raised (gaps, AI Watch) are seen
by everyone. On top of that, an item whose run read a source the viewer may not read is
Restricted: counted, never shown (ADR-0034 row 9). Mutes are admin only, at most 30 days,
and expire on their own: a new item with a muted subject is closed at once with reason
Muted, so the record stays (ADR-0037 owner answer 2).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.auth.users import User
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ParamInvalidError
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

Kind = Literal["schedule", "rule", "ai_watch", "gap"]
Reason = Literal["true_positive", "benign", "false_positive", "follow_up"]
REASONS: dict[str, str] = {
    "true_positive": "True positive",
    "benign": "Benign or expected",
    "false_positive": "False positive (tune the rule)",
    "follow_up": "Needs follow-up",
    "muted": "Muted",
}
NOTE_REQUIRED = frozenset({"false_positive", "follow_up"})
MAX_NOTE = 2_000
MAX_MUTE_DAYS = 30


@dataclass(slots=True)
class ItemEvent:
    at: str
    user_id: str | None
    action: str  # close | reopen
    reason: str | None
    note: str | None


@dataclass(slots=True)
class AlertItem:
    item_id: str
    kind: str
    subject: str
    ref_id: str | None
    title: str
    detail: str
    why: str | None
    count: int | None
    sources: list[str]
    owner_id: str | None
    shared: bool
    range_start: str | None
    range_end: str | None
    created_at: str
    state: str  # open | closed
    closed_at: str | None
    closed_by: str | None
    close_reason: str | None
    note: str | None
    resolved: str | None  # the condition ended (a quiet source sending again)
    schedule_id: str | None = None  # the schedule whose run fired, for its rows
    severity: str | None = None  # high | medium (AI Watch); None for the rest
    history: list[ItemEvent] = field(default_factory=list)


@dataclass(slots=True)
class Mute:
    mute_id: str
    kind: str
    subject: str
    title: str
    until: str
    created_by: str | None
    created_at: str


class AlertItems:
    def __init__(
        self,
        meta: MetaDB,
        audit: AuditLog,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._audit = audit
        self._clock = clock

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    # --- raising ------------------------------------------------------------------------

    def raise_item(
        self,
        kind: Kind,
        subject: str,
        title: str,
        *,
        ref_id: str | None = None,
        detail: str = "",
        why: str | None = None,
        count: int | None = None,
        sources: list[str] | None = None,
        owner_id: str | None = None,
        shared: bool = True,
        range_start: str | None = None,
        range_end: str | None = None,
        severity: str | None = None,
    ) -> AlertItem:
        """Write an item (once per kind and ref id). A muted subject closes it at once."""
        now = self._now()
        item_id = str(uuid.uuid4())
        with self._meta.connect() as con:
            if ref_id is not None:
                had = con.execute(
                    "SELECT item_id FROM alert_items WHERE kind = ? AND ref_id = ?",
                    (kind, ref_id),
                ).fetchone()
                if had:
                    return self._load(con, had["item_id"])
            con.execute(
                "INSERT INTO alert_items (item_id, kind, subject, ref_id, title, detail, why,"
                " count, sources, owner_id, shared, range_start, range_end, created_at, severity)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    kind,
                    subject,
                    ref_id,
                    title[:300],
                    detail[:1_000],
                    (why or "")[:500] or None,
                    count,
                    json.dumps(sorted(set(sources or []))),
                    owner_id,
                    int(shared),
                    range_start,
                    range_end,
                    now,
                    severity,
                ),
            )
            mute = con.execute(
                "SELECT until FROM alert_mutes WHERE kind = ? AND subject = ?"
                " AND ended_at IS NULL AND until > ?",
                (kind, subject, now),
            ).fetchone()
            if mute:
                note = f"Muted until {mute['until'][:10]}"
                self._set_closed(con, item_id, None, "muted", note, now)
        if mute:
            self._audit.write(
                "alert.close",
                "success",
                None,
                None,
                {"item_id": item_id, "kind": kind, "subject": subject, "reason": "muted"},
            )
        with self._meta.connect() as con:
            return self._load(con, item_id)

    def resolve(self, kind: Kind, ref_id: str, text: str) -> None:
        """Note that the condition ended (a quiet source sending again); the item stays open
        until someone closes it."""
        with self._meta.connect() as con:
            con.execute(
                "UPDATE alert_items SET resolved = ? WHERE kind = ? AND ref_id = ?",
                (text[:300], kind, ref_id),
            )

    # --- reading ------------------------------------------------------------------------

    def sees(self, item: AlertItem, user: User) -> bool:
        """May the viewer know the item exists (before the Restricted check)?"""
        return (
            item.owner_id is None
            or item.shared
            or user.role == "admin"
            or item.owner_id == user.user_id
        )

    def items(self, user: User, state: str = "open", limit: int = 200) -> list[AlertItem]:
        base = (
            "SELECT a.*, r.schedule_id AS run_schedule FROM alert_items a"
            " LEFT JOIN schedule_runs r ON r.run_id = a.ref_id"
        )
        with self._meta.connect() as con:
            if state == "all":
                rows = con.execute(
                    base + " ORDER BY a.created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = con.execute(
                    base + " WHERE a.state = ? ORDER BY a.created_at DESC LIMIT ?",
                    (state, limit),
                ).fetchall()
        return [i for i in (_item(r) for r in rows) if self.sees(i, user)]

    def get(self, item_id: str, user: User) -> AlertItem:
        with self._meta.connect() as con:
            item = self._load(con, item_id)
        if not self.sees(item, user):
            raise NotFoundError("No such alert")
        return item

    def _load(self, con: sqlite3.Connection, item_id: str) -> AlertItem:
        r = con.execute(
            "SELECT a.*, r.schedule_id AS run_schedule FROM alert_items a"
            " LEFT JOIN schedule_runs r ON r.run_id = a.ref_id WHERE a.item_id = ?",
            (item_id,),
        ).fetchone()
        if r is None:
            raise NotFoundError("No such alert")
        item = _item(r)
        item.history = [
            ItemEvent(h["at"], h["user_id"], h["action"], h["reason"], h["note"])
            for h in con.execute(
                "SELECT * FROM alert_item_history WHERE item_id = ? ORDER BY at, rowid",
                (item_id,),
            )
        ]
        return item

    # --- deciding -----------------------------------------------------------------------

    def close(
        self, item_id: str, user: User, reason: str, note: str | None, ip: str | None
    ) -> AlertItem:
        if reason not in REASONS or reason == "muted":
            raise ParamInvalidError("Choose a reason")
        note = (note or "").strip() or None
        if reason in NOTE_REQUIRED and not note:
            raise ParamInvalidError(f"Add a note for {REASONS[reason]}")
        if note and len(note) > MAX_NOTE:
            raise ParamInvalidError(f"Notes are at most {MAX_NOTE:,} characters")
        item = self.get(item_id, user)
        if item.state == "closed":
            raise ConflictError("This alert is already closed")
        with self._meta.connect() as con:
            self._set_closed(con, item_id, user.user_id, reason, note, self._now())
            item = self._load(con, item_id)
        self._audit.write(
            "alert.close",
            "success",
            user.user_id,
            ip,
            {
                "item_id": item_id,
                "kind": item.kind,
                "subject": item.subject,
                "reason": reason,
                "note": note,
            },
        )
        return item

    def _set_closed(
        self,
        con: sqlite3.Connection,
        item_id: str,
        user_id: str | None,
        reason: str,
        note: str | None,
        now: str,
    ) -> None:
        con.execute(
            "UPDATE alert_items SET state = 'closed', closed_at = ?, closed_by = ?,"
            " close_reason = ?, note = ? WHERE item_id = ?",
            (now, user_id, reason, note, item_id),
        )
        con.execute(
            "INSERT INTO alert_item_history (item_id, at, user_id, action, reason, note)"
            " VALUES (?, ?, ?, 'close', ?, ?)",
            (item_id, now, user_id, reason, note),
        )

    def open_subjects(self, kind: Kind, prefix: str) -> set[str]:
        """Subjects of open items of one kind starting with `prefix` ("mcp:")."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT DISTINCT subject FROM alert_items WHERE kind = ? AND state = 'open'"
                " AND substr(subject, 1, ?) = ?",
                (kind, len(prefix), prefix),
            ).fetchall()
        return {r["subject"] for r in rows}

    def close_subject(
        self, kind: Kind, subject: str, user: User, reason: str, note: str, ip: str | None
    ) -> int:
        """Close every open item about one subject, for a decision made elsewhere: marking
        an AI service or MCP server approved or not approved answers its review items
        (ADR-0035 row 11). Each close is audited like one made on Alerts."""
        with self._meta.connect() as con:
            ids = [
                r["item_id"]
                for r in con.execute(
                    "SELECT item_id FROM alert_items WHERE kind = ? AND subject = ?"
                    " AND state = 'open'",
                    (kind, subject),
                )
            ]
            now = self._now()
            for item_id in ids:
                self._set_closed(con, item_id, user.user_id, reason, note, now)
        for item_id in ids:
            self._audit.write(
                "alert.close",
                "success",
                user.user_id,
                ip,
                {
                    "item_id": item_id,
                    "kind": kind,
                    "subject": subject,
                    "reason": reason,
                    "note": note,
                },
            )
        return len(ids)

    def reopen(self, item_id: str, user: User, ip: str | None) -> AlertItem:
        item = self.get(item_id, user)
        if item.state == "open":
            raise ConflictError("This alert is already open")
        now = self._now()
        with self._meta.connect() as con:
            con.execute(
                "UPDATE alert_items SET state = 'open', closed_at = NULL, closed_by = NULL,"
                " close_reason = NULL, note = NULL WHERE item_id = ?",
                (item_id,),
            )
            con.execute(
                "INSERT INTO alert_item_history (item_id, at, user_id, action)"
                " VALUES (?, ?, ?, 'reopen')",
                (item_id, now, user.user_id),
            )
            item = self._load(con, item_id)
        self._audit.write(
            "alert.reopen",
            "success",
            user.user_id,
            ip,
            {"item_id": item_id, "kind": item.kind, "subject": item.subject},
        )
        return item

    # --- muting (admins only; checked here as well as on the route) ---------------------

    def mutes(self) -> list[Mute]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM alert_mutes WHERE ended_at IS NULL AND until > ? ORDER BY until",
                (self._now(),),
            ).fetchall()
        return [
            Mute(
                r["mute_id"],
                r["kind"],
                r["subject"],
                r["title"],
                r["until"],
                r["created_by"],
                r["created_at"],
            )
            for r in rows
        ]

    def mute(self, item_id: str, days: int, user: User, ip: str | None) -> Mute:
        """Mute new items like this one (same kind and subject) for `days`."""
        if user.role != "admin":
            raise ForbiddenError("Only administrators can mute alerts")
        if not 1 <= days <= MAX_MUTE_DAYS:
            raise ParamInvalidError(f"Mute for 1 to {MAX_MUTE_DAYS} days")
        item = self.get(item_id, user)
        now = self._clock().astimezone(UTC)
        until = (now + timedelta(days=days)).isoformat()
        mute_id = str(uuid.uuid4())
        with self._meta.connect() as con:
            # One mute per subject: a new one replaces the old.
            con.execute(
                "UPDATE alert_mutes SET ended_at = ?, ended_by = ?"
                " WHERE kind = ? AND subject = ? AND ended_at IS NULL",
                (now.isoformat(), user.user_id, item.kind, item.subject),
            )
            con.execute(
                "INSERT INTO alert_mutes (mute_id, kind, subject, title, until, created_by,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    mute_id,
                    item.kind,
                    item.subject,
                    item.title,
                    until,
                    user.user_id,
                    now.isoformat(),
                ),
            )
        self._audit.write(
            "alert.mute",
            "success",
            user.user_id,
            ip,
            {"kind": item.kind, "subject": item.subject, "days": days, "until": until},
        )
        return next(m for m in self.mutes() if m.mute_id == mute_id)

    def unmute(self, mute_id: str, user: User, ip: str | None) -> None:
        if user.role != "admin":
            raise ForbiddenError("Only administrators can mute alerts")
        with self._meta.connect() as con:
            r = con.execute(
                "SELECT kind, subject FROM alert_mutes WHERE mute_id = ? AND ended_at IS NULL",
                (mute_id,),
            ).fetchone()
            if r is None:
                raise NotFoundError("No such mute")
            con.execute(
                "UPDATE alert_mutes SET ended_at = ?, ended_by = ? WHERE mute_id = ?",
                (self._now(), user.user_id, mute_id),
            )
        self._audit.write(
            "alert.unmute",
            "success",
            user.user_id,
            ip,
            {"kind": r["kind"], "subject": r["subject"]},
        )


def _item(r: sqlite3.Row) -> AlertItem:
    return AlertItem(
        item_id=r["item_id"],
        kind=r["kind"],
        subject=r["subject"],
        ref_id=r["ref_id"],
        title=r["title"],
        detail=r["detail"],
        why=r["why"],
        count=r["count"],
        sources=json.loads(r["sources"] or "[]"),
        owner_id=r["owner_id"],
        shared=bool(r["shared"]),
        range_start=r["range_start"],
        range_end=r["range_end"],
        created_at=r["created_at"],
        state=r["state"],
        closed_at=r["closed_at"],
        closed_by=r["closed_by"],
        close_reason=r["close_reason"],
        note=r["note"],
        resolved=r["resolved"],
        schedule_id=r["run_schedule"],
        severity=r["severity"],
    )
