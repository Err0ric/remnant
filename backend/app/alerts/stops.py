"""A pause or failure that stops detection is never silent (D33 as amended, owner 2026-11-10).

Every path where detection stops on its own (a schedule or vendor alert source that pauses
itself, a source or connector that cannot read, an AI Watch step that fails, an intel feed
that cannot update, a failed integrity check, and later the triage self-pause) sends its
message through this module:

- `recipients(preferred)`: the thing's own alert targets when it has any, otherwise every
  alert target. A message is only lost when the install has no alert target at all, and
  Health still shows the problem then.
- `notify(alert, preferred)`: one message now, for paths that already decide when to send
  (they pause once and resume once).
- `failing(key, ...)` and `working(key)`: for paths that check on every pass. Callers call
  `failing` only for an error (a fetch that failed, a listener down, a full spool, a missing
  template), never for "no new events", lag, or a quiet period. The first failing call
  records when it started; once it has lasted `grace`, one "Detection stopped" message goes
  out, and when it works again one "Detection running again" message. A short blip inside
  the grace sends nothing. All audited.

Flap limit (owner, 2026-11-10): at most one stopped and running-again pair per path an
hour. A second stop within the hour sends one "Still flapping: N failures in the last hour"
message instead, and nothing more for that path until it has been stable for an hour; then
one message says where it settled (running again, or stopped).

Messages carry the thing's name and a short reason the app wrote, never event content.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from app.alerts.dispatch import AlertDispatcher
from app.alerts.render import Alert, AlertKind
from app.core.branding import PRODUCT_NAME
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

GRACE = timedelta(minutes=15)
FLAP_WINDOW = timedelta(hours=1)


class DetectionStops:
    def __init__(
        self,
        meta: MetaDB,
        dispatcher: AlertDispatcher | None,
        audit: AuditLog | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        link: str | None = None,
    ) -> None:
        self._meta = meta
        self._dispatcher = dispatcher
        self._audit = audit
        self._clock = clock
        self._link = link
        self._lock = threading.Lock()
        with meta.connect() as con:
            # Keys with state, so a working pass costs no query unless something was wrong.
            self._open = {r[0] for r in con.execute("SELECT key FROM detection_stops")}
            self._flapping = {
                r[0]
                for r in con.execute(
                    "SELECT key FROM detection_flaps WHERE flapping_since IS NOT NULL"
                )
            }

    def recipients(self, preferred: Iterable[str]) -> list[str]:
        chosen = list(preferred)
        if chosen:
            return chosen
        with self._meta.connect() as con:
            return [r[0] for r in con.execute("SELECT target_id FROM alert_targets")]

    def notify(
        self,
        alert: Alert,
        preferred: Iterable[str],
        schedule_id: str | None = None,
        run_id: str | None = None,
        source_id: str | None = None,
    ) -> None:
        if self._dispatcher is None:
            return
        targets = self.recipients(preferred)
        if targets:
            self._dispatcher.enqueue(alert, targets, schedule_id, run_id, source_id=source_id)

    def failing(
        self,
        key: str,
        title: str,
        reason: str,
        path: str = "health",
        preferred: Iterable[str] = (),
        grace: timedelta = GRACE,
    ) -> None:
        now = self._clock()
        cut = (now - FLAP_WINDOW).isoformat()
        send: tuple[AlertKind, str, str] | None = None
        with self._lock, self._meta.connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO detection_stops (key, title, since) VALUES (?, ?, ?)",
                (key, title[:200], now.isoformat()),
            )
            if cur.rowcount == 1:  # a new failure: counted for the flap message
                con.execute("DELETE FROM detection_starts WHERE key = ? AND at < ?", (key, cut))
                con.execute(
                    "INSERT INTO detection_starts (key, at) VALUES (?, ?)", (key, now.isoformat())
                )
                con.execute("UPDATE detection_flaps SET stable_since = NULL WHERE key = ?", (key,))
            self._open.add(key)
            since, sent = con.execute(
                "SELECT since, sent_at FROM detection_stops WHERE key = ?", (key,)
            ).fetchone()
            flap = con.execute(
                "SELECT last_pair_at, flapping_since FROM detection_flaps WHERE key = ?", (key,)
            ).fetchone()
            last_pair, flapping = (flap[0], flap[1]) if flap else (None, None)
            started = datetime.fromisoformat(since)
            if flapping is not None:
                if now - started < FLAP_WINDOW:
                    return  # still flapping: the one message has gone
                # Down without a break for an hour: settled, say so once.
                self._end_flap(con, key, now)
                self._sent(con, key, title, now)
                send = ("stopped", reason[:300], since)
            elif sent is not None or now - started < grace:
                return
            elif last_pair is not None and now - datetime.fromisoformat(last_pair) < FLAP_WINDOW:
                (n,) = con.execute(
                    "SELECT count(*) FROM detection_starts WHERE key = ? AND at >= ?", (key, cut)
                ).fetchone()
                con.execute(
                    "UPDATE detection_flaps SET flapping_since = ? WHERE key = ?",
                    (now.isoformat(), key),
                )
                con.execute(
                    "UPDATE detection_stops SET sent_at = ? WHERE key = ?", (now.isoformat(), key)
                )
                self._flapping.add(key)
                detail = f"Still flapping: {n} failures in the last hour. Last: {reason[:200]}"
                send = ("stopped_flapping", detail, cut)
            else:
                self._sent(con, key, title, now)
                send = ("stopped", reason[:300], since)
        if send is None:
            return
        kind, detail, start = send
        if self._audit is not None:
            action = "detection.flapping" if kind == "stopped_flapping" else "detection.stopped"
            self._audit.write(action, "failure", None, None, {"key": key})
        self.notify(self._alert(kind, title, detail, start, None, path), preferred)

    def working(self, key: str, path: str = "health", preferred: Iterable[str] = ()) -> None:
        if key not in self._open and key not in self._flapping:
            return
        now = self._clock()
        with self._lock, self._meta.connect() as con:
            row = con.execute(
                "SELECT title, since, sent_at FROM detection_stops WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                con.execute("DELETE FROM detection_stops WHERE key = ?", (key,))
                self._open.discard(key)
            if key in self._flapping:
                if row is not None:  # recovered: stable from now, if it holds
                    con.execute(
                        "UPDATE detection_flaps SET stable_since = ? WHERE key = ?",
                        (now.isoformat(), key),
                    )
                    return
                stable = con.execute(
                    "SELECT stable_since FROM detection_flaps WHERE key = ?", (key,)
                ).fetchone()
                if stable is None or stable[0] is None:
                    con.execute(
                        "UPDATE detection_flaps SET stable_since = ? WHERE key = ?",
                        (now.isoformat(), key),
                    )
                    return
                if now - datetime.fromisoformat(stable[0]) < FLAP_WINDOW:
                    return
                self._end_flap(con, key, now)
                (title,) = con.execute(
                    "SELECT title FROM detection_flaps WHERE key = ?", (key,)
                ).fetchone()
                since = stable[0]
            elif row is None or row[2] is None:
                return  # a blip inside the grace: nothing was sent, so nothing to clear
            else:
                title, since = row[0], row[1]
        if self._audit is not None:
            self._audit.write("detection.resumed", "success", None, None, {"key": key})
        alert = self._alert(
            "stopped_cleared", title, "Working again.", since, now.isoformat(), path
        )
        self.notify(alert, preferred)

    def forget(self, prefix: str, keep: Iterable[str]) -> None:
        """Drop state under `prefix` for things gone or turned off, without a message."""
        kept = set(keep)
        gone = {k for k in self._open | self._flapping if k.startswith(prefix) and k not in kept}
        if not gone:
            return
        with self._lock, self._meta.connect() as con:
            for table in ("detection_stops", "detection_flaps", "detection_starts"):
                # Table names are literals from this tuple.
                con.executemany(f"DELETE FROM {table} WHERE key = ?", [(k,) for k in gone])  # noqa: S608
            self._open -= gone
            self._flapping -= gone

    def _sent(self, con: sqlite3.Connection, key: str, title: str, now: datetime) -> None:
        """Record a stopped message: the start of this hour's one pair."""
        con.execute("UPDATE detection_stops SET sent_at = ? WHERE key = ?", (now.isoformat(), key))
        con.execute(
            "INSERT INTO detection_flaps (key, title, last_pair_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET last_pair_at = excluded.last_pair_at,"
            " title = excluded.title",
            (key, title[:200], now.isoformat()),
        )

    def _end_flap(self, con: sqlite3.Connection, key: str, now: datetime) -> None:
        con.execute(
            "UPDATE detection_flaps SET flapping_since = NULL, stable_since = NULL,"
            " last_pair_at = ? WHERE key = ?",
            (now.isoformat(), key),
        )
        self._flapping.discard(key)

    def _alert(
        self, kind: AlertKind, title: str, detail: str, start: str, end: str | None, path: str
    ) -> Alert:
        return Alert(
            kind=kind,
            title=title,
            detail=detail,
            count=None,
            reason=None,
            range_start=start,
            range_end=end,
            link=f"{self._link}/{path}" if self._link else None,
            product=PRODUCT_NAME,
        )
