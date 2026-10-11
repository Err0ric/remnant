"""Queue and deliver alerts with retries (ADR-0007 rows 3 and 6).

Schedules enqueue one delivery per target. The server's schedule loop calls `tick()`,
which sends what is due. A failed delivery is retried after 1, 5, and 15 minutes, then
marked failed; every attempt's error is kept on the delivery (never the URL), and the
target's own health counters move with it.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from app.alerts.render import Alert
from app.alerts.send import SendError
from app.alerts.targets import TargetStore
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.meta.db import MetaDB

RETRY_AFTER = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))
DUE_PER_TICK = 50
KEEP_PER_SCHEDULE = 200


@dataclass(frozen=True, slots=True)
class Delivery:
    delivery_id: str
    target_id: str
    target_name: str | None  # None once the target is deleted
    schedule_id: str | None
    run_id: str | None
    kind: str
    status: str
    attempts: int
    next_attempt_at: str | None
    last_error: str | None
    created_at: str
    sent_at: str | None


class AlertDispatcher:
    def __init__(
        self,
        meta: MetaDB,
        targets: TargetStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._targets = targets
        self._clock = clock

    def enqueue(
        self, alert: Alert, target_ids: list[str], schedule_id: str | None, run_id: str | None
    ) -> list[str]:
        now = self._clock().astimezone(UTC).isoformat()
        ids = []
        with self._meta.connect() as con:
            for tid in sorted(set(target_ids)):
                did = new_id()
                con.execute(
                    "INSERT INTO alert_deliveries (delivery_id, target_id, schedule_id, run_id,"
                    " alert, status, attempts, next_attempt_at, created_at)"
                    " VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
                    (did, tid, schedule_id, run_id, json.dumps(asdict(alert)), now, now),
                )
                ids.append(did)
            if schedule_id is not None:
                con.execute(
                    "DELETE FROM alert_deliveries WHERE schedule_id = ? AND status != 'pending'"
                    " AND delivery_id NOT IN (SELECT delivery_id FROM alert_deliveries"
                    " WHERE schedule_id = ? ORDER BY created_at DESC LIMIT ?)",
                    (schedule_id, schedule_id, KEEP_PER_SCHEDULE),
                )
        return ids

    def tick(self) -> int:
        """Send every due delivery. Returns how many were attempted."""
        now = self._clock().astimezone(UTC)
        with self._meta.connect() as con:
            due = con.execute(
                "SELECT delivery_id, target_id, alert, attempts FROM alert_deliveries"
                " WHERE status = 'pending' AND next_attempt_at <= ?"
                " ORDER BY next_attempt_at LIMIT ?",
                (now.isoformat(), DUE_PER_TICK),
            ).fetchall()
        for row in due:
            self._attempt(row["delivery_id"], row["target_id"], row["alert"], row["attempts"])
        return len(due)

    def _attempt(self, delivery_id: str, target_id: str, alert_json: str, attempts: int) -> None:
        alert = Alert(**json.loads(alert_json))
        attempts += 1
        now = self._clock().astimezone(UTC)
        try:
            self._targets.send(target_id, alert)
        except NotFoundError:
            self._finish(delivery_id, "failed", attempts, None, "The target was deleted")
            return
        except SendError as exc:
            if attempts <= len(RETRY_AFTER):
                retry = (now + RETRY_AFTER[attempts - 1]).isoformat()
                self._finish(delivery_id, "pending", attempts, retry, str(exc)[:300])
            else:
                self._finish(delivery_id, "failed", attempts, None, str(exc)[:300])
            return
        with self._meta.connect() as con:
            con.execute(
                "UPDATE alert_deliveries SET status = 'sent', attempts = ?, next_attempt_at = NULL,"
                " sent_at = ? WHERE delivery_id = ?",
                (attempts, now.isoformat(), delivery_id),
            )

    def _finish(
        self, delivery_id: str, status: str, attempts: int, retry: str | None, error: str
    ) -> None:
        with self._meta.connect() as con:
            con.execute(
                "UPDATE alert_deliveries SET status = ?, attempts = ?, next_attempt_at = ?,"
                " last_error = ? WHERE delivery_id = ?",
                (status, attempts, retry, error, delivery_id),
            )

    def failed_since(self, since: datetime) -> int:
        """Deliveries that gave up after their retries, made at or after `since`."""
        with self._meta.connect() as con:
            (n,) = con.execute(
                "SELECT count(*) FROM alert_deliveries WHERE status = 'failed' AND created_at >= ?",
                (since.astimezone(UTC).isoformat(),),
            ).fetchone()
        return int(n)

    def deliveries(self, schedule_id: str, limit: int = 50) -> list[Delivery]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT d.*, t.name AS target_name FROM alert_deliveries d"
                " LEFT JOIN alert_targets t ON t.target_id = d.target_id"
                " WHERE d.schedule_id = ? ORDER BY d.created_at DESC LIMIT ?",
                (schedule_id, limit),
            ).fetchall()
        return [
            Delivery(
                delivery_id=r["delivery_id"],
                target_id=r["target_id"],
                target_name=r["target_name"],
                schedule_id=r["schedule_id"],
                run_id=r["run_id"],
                kind=json.loads(r["alert"]).get("kind", ""),
                status=r["status"],
                attempts=r["attempts"],
                next_attempt_at=r["next_attempt_at"],
                last_error=r["last_error"],
                created_at=r["created_at"],
                sent_at=r["sent_at"],
            )
            for r in rows
        ]
