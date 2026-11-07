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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.auth.users import User
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ParamInvalidError
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

Kind = Literal["schedule", "rule", "ai_watch", "gap"]
Reason = Literal["expected", "approved", "false_positive", "resolved"]
# The reasons a person picks (ADR-0043 row 16), in the order shown.
REASONS: dict[str, str] = {
    "expected": "Expected",
    "approved": "Approved",
    "false_positive": "False positive",
    "resolved": "Resolved",
}
# How stored reasons from before read now (ADR-0043 answer 4), and the system's own.
LABELS: dict[str, str] = {
    **REASONS,
    "true_positive": "Resolved",
    "benign": "Expected",
    "follow_up": "Resolved",
    "muted": "Muted",
    "merged": "Merged",
    "superseded": "Superseded by rule change",
}
SUPERSEDED_NOTE = "Superseded by rule change"  # D213: closed by the server on upgrade
NOTE_REQUIRED = frozenset({"false_positive"})
MUTE_DAYS = (7, 30)  # ADR-0043 row 18


def label(reason: str | None) -> str | None:
    return LABELS.get(reason, reason) if reason else None


MAX_NOTE = 2_000
MAX_MUTE_DAYS = max(MUTE_DAYS)
MAX_CHANGES = 20  # lines kept on a grouped item, newest first (ADR-0043 row 2)
RANK = {None: 0, "info": 0, "low": 1, "medium": 2, "high": 3}
# The one severity a source gap carries (ADR-0043 row 15: as set on the source, today
# medium). Stored on the item; every surface reads the item's field, none re-derives it.
GAP_SEVERITY = "medium"


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
    severity: str | None = None  # high | medium, as stored; None for schedules and rules
    # Who and which devices the item is about, from the rows that fired (ADR-0038 row 28).
    people: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    history: list[ItemEvent] = field(default_factory=list)
    # The group (ADR-0043 row 1): one open item per entity, rule, and day; repeats add to
    # `count` and `changes` and move `last_seen`.
    entity: str | None = None
    rule: str | None = None
    day: str | None = None
    last_seen: str | None = None
    changes: list[str] = field(default_factory=list)
    more: int = 0  # changes beyond MAX_CHANGES
    # What this raise did: created the item, or raised its severity. Only these notify
    # (row 4); a repeat that only adds to the count does not.
    fresh: bool = False
    rose: bool = False


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
        tz: str = "UTC",
        gap_min_back: timedelta = timedelta(minutes=15),
        gap_max_notify: int = 3,
    ) -> None:
        # Flap guard for gaps (owner, 2026-11-03): see SourcesConfig.
        self._gap_min_back = gap_min_back
        self._gap_max_notify = gap_max_notify
        self._meta = meta
        self._audit = audit
        self._clock = clock
        try:  # the install's time zone draws the day boundary (ADR-0043 answer 1)
            self._tz = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            self._tz = ZoneInfo("UTC")

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    def day_of(self, at: datetime | str) -> str:
        """The install-time-zone day of an instant, YYYY-MM-DD."""
        when = datetime.fromisoformat(at) if isinstance(at, str) else at
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(self._tz).date().isoformat()

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
        refresh: bool = False,
        people: list[str] | None = None,
        devices: list[str] | None = None,
        group: tuple[str, str] | None = None,
        change: str | None = None,
    ) -> AlertItem:
        """Write an item (once per kind and ref id). A muted subject closes it at once.
        With `refresh`, an existing open item takes the new wording and counts.

        With `group` (entity, rule), at most one item per kind, entity, rule, and day is
        open (ADR-0043): a repeat adds its count and `change` line to that item instead of
        writing a new one, and raises its severity when the repeat is more severe."""
        now = self._now()
        item_id = str(uuid.uuid4())
        who = _names(people)
        dev = _names(devices)
        line = (change or why or title)[:300]
        with self._meta.connect() as con:
            if ref_id is not None:
                had = con.execute(
                    "SELECT item_id FROM alert_items WHERE kind = ? AND ref_id = ?",
                    (kind, ref_id),
                ).fetchone()
                if had and refresh:
                    # An open item is kept current (who used it, its wording, its sources);
                    # a closed one stays as it was decided (owner, 2026-10-23).
                    con.execute(
                        "UPDATE alert_items SET title = ?, detail = ?, why = ?, count = ?,"
                        " sources = ?, range_end = coalesce(?, range_end),"
                        " severity = coalesce(?, severity),"
                        " people = coalesce(?, people), devices = coalesce(?, devices)"
                        " WHERE item_id = ? AND state = 'open'",
                        (
                            title[:300],
                            detail[:1_000],
                            (why or "")[:500] or None,
                            count,
                            json.dumps(sorted(set(sources or []))),
                            range_end,
                            severity,
                            who,
                            dev,
                            had["item_id"],
                        ),
                    )
                if had:
                    return self._load(con, had["item_id"])
            if group is not None:
                grown = self._grow(
                    con, kind, group, self.day_of(now), line, count, severity, who, dev, now,
                    range_end,
                )  # fmt: skip
                if grown is not None:
                    return grown
            entity, rule = group if group is not None else (None, None)
            group_day = self.day_of(now) if group is not None else None
            if group is not None:
                earlier = con.execute(
                    "SELECT close_reason FROM alert_items WHERE kind = ? AND entity = ?"
                    " AND rule = ? AND day = ? AND state = 'closed' ORDER BY closed_at DESC",
                    (kind, entity, rule, group_day),
                ).fetchone()
                if earlier is not None:  # row 3: a new item, linked to the decision
                    said = label(earlier["close_reason"]) or "closed"
                    detail = f"Closed earlier today as {said}. {detail}".strip()
            con.execute(
                "INSERT INTO alert_items (item_id, kind, subject, ref_id, title, detail, why,"
                " count, sources, owner_id, shared, range_start, range_end, created_at, severity,"
                " people, devices, entity, rule, day, last_seen, changes)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    who,
                    dev,
                    entity,
                    rule,
                    group_day,
                    now if group is not None else None,
                    json.dumps({"lines": [line], "more": 0}) if group is not None else None,
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
            out = self._load(con, item_id)
        out.fresh = True
        return out

    def _grow(
        self,
        con: sqlite3.Connection,
        kind: str,
        group: tuple[str, str],
        day: str,
        line: str,
        count: int | None,
        severity: str | None,
        who: str | None,
        dev: str | None,
        now: str,
        range_end: str | None,
    ) -> AlertItem | None:
        """Add a repeat to the open item of its group, if there is one (ADR-0043 row 2)."""
        r = con.execute(
            "SELECT * FROM alert_items WHERE kind = ? AND entity = ? AND rule = ? AND day = ?"
            " AND state = 'open'",
            (kind, group[0], group[1], day),
        ).fetchone()
        if r is None:
            return None
        log = _changes(r["changes"])
        lines, more = log
        if line not in lines:
            lines.insert(0, line)
            more += max(0, len(lines) - MAX_CHANGES)
            lines = lines[:MAX_CHANGES]
        rose = RANK.get(severity, 0) > RANK.get(r["severity"], 0)
        # The condition had ended (a quiet source sending again) and is back: say so again,
        # unless it is flapping. A gap notifies again only when the source was back long
        # enough, and at most so many times a day; after that the title says so.
        title = r["title"]
        notified = _notified(r["changes"])
        back = False
        if r["resolved"] is not None:
            away = _since(r["resolved_at"], now)
            steady = kind != "gap" or (away is not None and away >= self._gap_min_back)
            if steady and (kind != "gap" or notified < self._gap_max_notify):
                back, notified = True, notified + 1
            elif kind == "gap" and notified >= self._gap_max_notify and "(flapping)" not in title:
                title = f"{title} (flapping)"[:300]
        people = sorted({*json.loads(r["people"] or "[]"), *json.loads(who or "[]")})
        devices = sorted({*json.loads(r["devices"] or "[]"), *json.loads(dev or "[]")})
        con.execute(
            "UPDATE alert_items SET count = coalesce(count, 1) + ?, changes = ?, last_seen = ?,"
            " severity = ?, people = ?, devices = ?, range_end = coalesce(?, range_end),"
            " resolved = NULL, resolved_at = NULL, title = ? WHERE item_id = ?",
            (
                count or 1,
                json.dumps({"lines": lines, "more": more, "notified": notified}),
                now,
                severity if rose else r["severity"],
                _names(people),
                _names(devices),
                range_end,
                title,
                r["item_id"],
            ),
        )
        item = self._load(con, r["item_id"])
        item.rose = rose or back
        return item

    def merge_open_duplicates(self) -> int:
        """Once at start (ADR-0043 row 5): give open items raised before grouping their
        group, and merge open items of the same group into the oldest. The others close as
        Merged with a note naming the item they joined; each merge is audited. Closed items
        are not touched. Returns how many were merged."""
        merged: list[tuple[str, str]] = []
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT * FROM alert_items WHERE state = 'open' AND entity IS NULL"
                " ORDER BY created_at, rowid"
            ).fetchall()
            for r in rows:
                key = backfill_group(r["kind"], r["subject"], r["ref_id"])
                if key is None:
                    continue
                day = self.day_of(r["created_at"])
                into = con.execute(
                    "SELECT * FROM alert_items WHERE kind = ? AND entity = ? AND rule = ?"
                    " AND day = ? AND state = 'open'",
                    (r["kind"], key[0], key[1], day),
                ).fetchone()
                if into is None:
                    line = (r["why"] or r["title"])[:300]
                    con.execute(
                        "UPDATE alert_items SET entity = ?, rule = ?, day = ?, last_seen = ?,"
                        " changes = ? WHERE item_id = ?",
                        (key[0], key[1], day, r["created_at"],
                         json.dumps({"lines": [line], "more": 0}), r["item_id"]),
                    )  # fmt: skip
                    continue
                lines, more = _changes(into["changes"])
                line = (r["why"] or r["title"])[:300]
                if line not in lines:
                    lines.append(line)
                    more += max(0, len(lines) - MAX_CHANGES)
                    lines = lines[:MAX_CHANGES]
                worse = RANK.get(r["severity"], 0) > RANK.get(into["severity"], 0)
                con.execute(
                    "UPDATE alert_items SET count = coalesce(count, 1) + coalesce(?, 1),"
                    " changes = ?, last_seen = max(coalesce(last_seen, ''), ?), severity = ?"
                    " WHERE item_id = ?",
                    (r["count"], json.dumps({"lines": lines, "more": more}), r["created_at"],
                     r["severity"] if worse else into["severity"], into["item_id"]),
                )  # fmt: skip
                self._set_closed(con, r["item_id"], None, "merged",
                                 f"Merged into alert {into['item_id']}", self._now())  # fmt: skip
                merged.append((r["item_id"], into["item_id"]))
        for item_id, into_id in merged:
            self._audit.write(
                "alert.merge", "success", None, None, {"item_id": item_id, "into": into_id}
            )
        return len(merged)

    def fill_severity(self) -> int:
        """At start: gap items stored before gaps carried a severity get the gap's one
        (ADR-0043 row 15), so the Dashboard, the Alerts strip, and the list read the same
        stored value. Idempotent; returns how many items changed."""
        with self._meta.connect() as con:
            cur = con.execute(
                "UPDATE alert_items SET severity = ? WHERE kind = 'gap' AND severity IS NULL",
                (GAP_SEVERITY,),
            )
            return cur.rowcount

    def open_gaps(self) -> dict[str, tuple[str, str]]:
        """Each source's open, unresolved source gap alert: source id to (item id, when it
        last fired). What the Dashboard footer and Health count as a gap, so they agree with
        the Alerts page (review item 3, 2026-11-06). Gaps of one machine's queue
        (`source/machine`) are not a source's gap."""
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT subject, item_id, coalesce(last_seen, created_at) AS at"
                " FROM alert_items WHERE kind = 'gap' AND state = 'open' AND resolved IS NULL"
                " AND instr(subject, '/') = 0 ORDER BY created_at"
            ).fetchall()
        return {r["subject"]: (r["item_id"], r["at"]) for r in rows}

    def close_superseded(self, still_raised: Callable[[AlertItem], bool], fix_id: str) -> list[str]:
        """Once per `fix_id` (D213, proposed): close each open alert `still_raised` says the
        current rules would not raise now, as Superseded by rule change, by the server (no
        user), one `alert.close` audit row each. An alert someone acted on (a decision in
        its history or a note) is never touched. Returns the closed item ids."""
        closed: list[AlertItem] = []
        with self._meta.connect() as con:
            if con.execute("SELECT 1 FROM one_time_fixes WHERE fix_id = ?", (fix_id,)).fetchone():
                return []
            rows = con.execute(
                "SELECT a.*, NULL AS run_schedule FROM alert_items a WHERE a.state = 'open'"
                " AND a.note IS NULL AND NOT EXISTS (SELECT 1 FROM alert_item_history h"
                " WHERE h.item_id = a.item_id AND h.user_id IS NOT NULL)"
                " ORDER BY a.created_at, a.rowid"
            ).fetchall()
            now = self._now()
            for r in rows:
                item = _item(r)
                if still_raised(item):
                    continue
                self._set_closed(con, item.item_id, None, "superseded", SUPERSEDED_NOTE, now)
                closed.append(item)
            con.execute(
                "INSERT INTO one_time_fixes (fix_id, applied_at, changed) VALUES (?, ?, ?)",
                (fix_id, now, len(closed)),
            )
        for item in closed:
            self._audit.write(
                "alert.close",
                "success",
                None,
                None,
                {
                    "item_id": item.item_id,
                    "kind": item.kind,
                    "subject": item.subject,
                    "reason": "superseded",
                    "note": SUPERSEDED_NOTE,
                    "fix": fix_id,
                },
            )
        return [i.item_id for i in closed]

    def resolve(
        self, kind: Kind, ref_id: str, text: str, group: tuple[str, str] | None = None
    ) -> None:
        """Note that the condition ended (a quiet source sending again); the item stays open
        until someone closes it. With `group`, the open item of that group is the one: a
        repeat joined it under another ref."""
        now = self._now()
        with self._meta.connect() as con:
            con.execute(
                "UPDATE alert_items SET resolved = ?, resolved_at = ?"
                " WHERE kind = ? AND (ref_id = ? OR (entity = ? AND rule = ? AND state = 'open'))",
                (text[:300], now, kind, ref_id, *(group or (None, None))),
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
        self,
        item_id: str,
        user: User,
        reason: str,
        note: str | None,
        ip: str | None,
        bulk: bool = False,
    ) -> AlertItem:
        if reason not in REASONS:
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
                **({"bulk": True} if bulk else {}),
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
        if days not in MUTE_DAYS:
            raise ParamInvalidError("Mute for 7 or 30 days")
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
        people=json.loads(r["people"] or "[]"),
        devices=json.loads(r["devices"] or "[]"),
        entity=r["entity"],
        rule=r["rule"],
        day=r["day"],
        last_seen=r["last_seen"],
        changes=_changes(r["changes"])[0],
        more=_changes(r["changes"])[1],
    )


def _notified(raw: str | None) -> int:
    """Notifications an item has sent: its first, plus each repeat that notified."""
    try:
        return int(json.loads(raw or "{}").get("notified", 1))
    except (ValueError, AttributeError):
        return 1


def _since(at: str | None, now: str) -> timedelta | None:
    if not at:
        return None
    return datetime.fromisoformat(now) - datetime.fromisoformat(at)


def _changes(raw: str | None) -> tuple[list[str], int]:
    try:
        v = json.loads(raw or "{}")
    except ValueError:
        return [], 0
    return [str(x) for x in v.get("lines", [])], int(v.get("more", 0))


def backfill_group(kind: str, subject: str, ref_id: str | None) -> tuple[str, str] | None:
    """The group of an item raised before grouping (ADR-0043 row 5), from how each raiser
    named it; None for standing review items, which stay one per subject."""
    if kind == "ai_watch":
        if subject.startswith("agent:") and ref_id and ref_id.startswith(subject + ":"):
            what = ref_id[len(subject) + 1 :]
            if what == "agent":
                return None
            return subject, "agent_busy" if what.startswith("busy:") else "agent_change"
        if subject.startswith("sensitive:"):
            return subject, "sensitive"
        return None
    if kind == "gap":
        return subject, "queue" if "/" in subject else "gap"
    if kind == "rule" and subject.startswith("refusals:"):
        return subject, "refusals"
    return subject, kind


MAX_NAMES = 20


def _names(values: list[str] | None) -> str | None:
    """Distinct, non-empty, at most MAX_NAMES, as stored; None when none were given."""
    if not values:
        return None
    out: list[str] = []
    for v in values:
        s = str(v).strip()[:256]
        if s and s not in out:
            out.append(s)
        if len(out) >= MAX_NAMES:
            break
    return json.dumps(out) if out else None
