"""External alerts (ADR-0049 3.1, Phase 0): alerts from other products become alert items.

An approved template with `emits: alerts` (ADR-0005) parses a vendor's alert into a
Detection Finding; a complete one carries its key (product and vendor alert ID) in
`unmapped`. Each minute this reads the alerts stored since the last look, through the
guard like every built-in check, and raises one item per new key. Items group as D200
says (one open item per entity, alert title, and day; a repeat adds to it). The key is
remembered, so a vendor resending the same alert raises nothing new, and a resend at a
higher severity raises the open item's severity (D200 row 4). The vendor's words are data:
stored as text, never parsed or run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.alerts.dispatch import AlertDispatcher
from app.alerts.external_cap import CAP, LEVELS, WINDOW, ExternalAlertSettings, level, level_name
from app.alerts.items import RANK, AlertItems
from app.alerts.render import Alert, AlertKind
from app.alerts.stops import DetectionStops
from app.core import clock
from app.core.branding import PRODUCT_NAME
from app.engine.duckdb import QueryEngine, QueryResult, QueryScope
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.templates.alerts import ALERT_KEY
from app.templates.registry import TemplateRegistry

EVERY = timedelta(minutes=1)
# Events are filed by the day of their own time: an alert whose time is older than this
# when it arrives is stored and searchable, but raises no item.
LOOKBACK = timedelta(days=7)
FIRST_LOOK = timedelta(days=1)  # after a restart, keys already seen raise nothing again
PER_TICK = 1_000

ALERTS_SQL = f"""
SELECT event_id, source_id, coalesce(time, time_observed) AS t, time_observed,
       json_extract_string(unmapped, '$.{ALERT_KEY}.product') AS product,
       json_extract_string(unmapped, '$.{ALERT_KEY}.id') AS alert_id,
       message, severity_id, src_endpoint_ip, src_endpoint_hostname, actor_user_name,
       device_hostname, template_id
FROM events
WHERE template_id IN (SELECT unnest($templates)) AND class_uid = 2004
  AND parse_status = 'ok' AND time_observed > $since
  AND json_extract_string(unmapped, '$.{ALERT_KEY}.id') IS NOT NULL
ORDER BY time_observed, event_id
LIMIT {PER_TICK}"""  # noqa: S608  # fixed SQL text; values are parameters

# An item's own alert events (D228, 0b): the item's stored keys are bound as one list
# parameter, never written into the SQL, so an item with thousands of grouped alerts runs
# the same query. Keys are "<product>\x1f<vendor alert id>".
EVENTS_SQL = f"""
SELECT event_id, coalesce(time, time_observed) AS time, source_id, message, severity_id,
       src_endpoint_ip, actor_user_name, json_extract_string(unmapped, '$.{ALERT_KEY}.id')
         AS alert_id, raw
FROM events
WHERE class_uid = 2004
  AND json_extract_string(unmapped, '$.{ALERT_KEY}.product') || chr(31)
      || json_extract_string(unmapped, '$.{ALERT_KEY}.id') IN (SELECT unnest($keys))
ORDER BY time DESC, event_id
LIMIT $limit OFFSET $offset"""  # noqa: S608  # fixed SQL text; values are parameters
SHOWN_IDS = 50  # vendor alert IDs on an item's detail; the rest page through the API
MAX_PAGE = 200


def alert_ids(
    meta: MetaDB, item_id: str, offset: int = 0, limit: int = SHOWN_IDS
) -> tuple[int, list[tuple[str, str]]]:
    """(how many vendor alerts an item holds, a page of (product, alert id), oldest first)."""
    limit = max(1, min(limit, MAX_PAGE))
    with meta.connect() as con:
        n = con.execute(
            "SELECT count(*) FROM external_alert_keys WHERE item_id = ?", (item_id,)
        ).fetchone()[0]
        rows = con.execute(
            "SELECT product, alert_id FROM external_alert_keys WHERE item_id = ?"
            " ORDER BY first_seen, rowid LIMIT ? OFFSET ?",
            (item_id, limit, max(0, offset)),
        ).fetchall()
    return int(n), [(str(r[0]), str(r[1])) for r in rows]


def item_keys(meta: MetaDB, item_id: str) -> list[str]:
    with meta.connect() as con:
        rows = con.execute(
            "SELECT product, alert_id FROM external_alert_keys WHERE item_id = ?", (item_id,)
        ).fetchall()
    return [f"{r[0]}\x1f{r[1]}" for r in rows]


def item_severity(severity_id: Any) -> str:
    """OCSF severity_id 1..6 to the vendor's level. Items carry high or medium (the Alerts
    page's two); a low or informational alert is raised with no severity and says its level
    in why, while its key keeps the level so a later rise is seen."""
    n = int(severity_id or 0)
    return "high" if n >= 4 else {3: "medium", 2: "low"}.get(n, "info")


@dataclass(slots=True)
class _Alert:
    event_id: str
    source_id: str
    at: datetime
    observed: datetime
    product: str
    alert_id: str
    title: str
    severity: str
    level: int  # 1 (info) .. 5 (critical), for the cap and the notify minimum
    ip: str | None
    host: str | None
    user: str | None


class ExternalAlerts:
    def __init__(
        self,
        engine: QueryEngine,
        meta: MetaDB,
        items: AlertItems,
        registry: TemplateRegistry,
        settings: ExternalAlertSettings | None = None,
        dispatcher: AlertDispatcher | None = None,
        audit: AuditLog | None = None,
        link: str | None = None,
        stops: DetectionStops | None = None,
    ) -> None:
        self._engine = engine
        self._meta = meta
        self._items = items
        self._registry = registry
        self._settings = settings
        self._dispatcher = dispatcher
        self._audit = audit
        self._link = link
        # Pause notices go through the never-silent helper (D236), shared with every other
        # path that stops detection.
        if stops is None and dispatcher is not None:
            stops = DetectionStops(meta, dispatcher, audit, link=link)
        self._stops = stops
        self._last: datetime | None = None
        self._since: datetime | None = None

    def templates(self) -> list[str]:
        return sorted(t.id for t in self._registry.all() if t.emits == "alerts")

    def tick(self, now: datetime | None = None) -> int:
        """Raise items for alerts stored since the last look; returns how many were read."""
        now = (now or clock.now()).astimezone(UTC)
        if self._last is not None and now - self._last < EVERY:
            return 0
        self._last = now
        self._resume(now)
        templates = self.templates()
        if not templates:
            return 0
        since = self._since or now - FIRST_LOOK
        res = self._engine.run(
            ALERTS_SQL,
            QueryScope(None, now - LOOKBACK, None),
            {"templates": templates, "since": since},
            timeout_s=20.0,
            name="detect.external_alerts",
        )
        mapped = {t.id for t in self._registry.all() if "device_hostname" in t.mapping.fields}
        for row in res.rows:
            alert = _row(row, mapped)
            self._raise(alert, now)
            self._since = max(self._since or since, alert.observed)
        if self._since is None:
            self._since = since
        return len(res.rows)

    def _raise(self, a: _Alert, now: datetime) -> None:
        with self._meta.connect() as con:
            seen = con.execute(
                "SELECT k.item_id, k.severity, i.state FROM external_alert_keys k"
                " LEFT JOIN alert_items i ON i.item_id = k.item_id"
                " WHERE k.product = ? AND k.alert_id = ?",
                (a.product, a.alert_id),
            ).fetchone()
            if seen is not None:
                con.execute(
                    "UPDATE external_alert_keys SET last_seen = ?"
                    " WHERE product = ? AND alert_id = ?",
                    (a.observed.isoformat(), a.product, a.alert_id),
                )
            held = con.execute(
                "SELECT 1 FROM external_alert_held WHERE product = ? AND alert_id = ?",
                (a.product, a.alert_id),
            ).fetchone()
            paused = con.execute(
                "SELECT 1 FROM external_alert_pauses WHERE source_id = ?", (a.source_id,)
            ).fetchone()
        rose = seen is not None and RANK.get(a.severity, 0) > RANK.get(seen["severity"], 0)
        if seen is not None and not rose:
            return  # a resend: nothing new
        # A rise on a closed item opens a new item linked to it (0c); the close stays.
        follows = seen["item_id"] if rose and seen["state"] == "closed" else None
        urgent = a.level >= LEVELS["high"]  # High and Critical skip the cap (D231)
        if seen is None and not urgent and (held or paused):
            # Held while the source is over its cap: stored and searchable, not raised. A
            # resend of a held alert stays held unless it comes back High or Critical.
            if not held:
                self._hold(a, now)
            return
        entity = a.user or a.host or a.ip or a.product
        item = self._items.raise_item(
            "rule",
            f"ext:{a.product}:{a.title}"[:300],
            a.title,
            why=f"Alert from {a.product}"
            + ("" if a.severity in ("high", "medium") else f", {a.severity} severity"),
            detail=f"{a.product} alert {a.alert_id}",
            count=1,
            sources=[a.source_id],
            range_start=a.at.isoformat(),
            range_end=a.at.isoformat(),
            severity=a.severity if a.severity in ("high", "medium") else None,
            people=[a.user] if a.user else None,
            devices=[a.host] if a.host else None,
            group=(entity[:200], f"ext:{a.product}:{a.title}"[:200]),
            change=f"{a.title} ({a.alert_id})"
            + (f", rose to {a.severity} after an earlier alert was closed" if follows else ""),
            follows=follows,
        )
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO external_alert_keys"
                " (product, alert_id, item_id, severity, first_seen, last_seen)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (product, alert_id) DO UPDATE SET"
                " item_id = excluded.item_id, severity = excluded.severity,"
                " last_seen = excluded.last_seen",
                (a.product, a.alert_id, item.item_id, a.severity,
                 a.observed.isoformat(), a.observed.isoformat()),
            )  # fmt: skip
            if held:
                con.execute(
                    "DELETE FROM external_alert_held WHERE product = ? AND alert_id = ?",
                    (a.product, a.alert_id),
                )
        if item.fresh:
            self._created(a.source_id, now)
        if item.state != "closed" and (item.fresh or item.rose):
            self._notify(a, item.item_id, item.severity)

    # --- cap (D231) ------------------------------------------------------------------------

    def _hold(self, a: _Alert, now: datetime) -> None:
        with self._meta.connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO external_alert_held"
                " (product, alert_id, source_id, severity, held_at) VALUES (?, ?, ?, ?, ?)",
                (a.product, a.alert_id, a.source_id, level_name(a.level), now.isoformat()),
            )

    def _created(self, source_id: str, now: datetime) -> None:
        """Count an item this source created; pause the source once the hour reaches CAP."""
        cut = (now - WINDOW).isoformat()
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO external_alert_created (source_id, at) VALUES (?, ?)",
                (source_id, now.isoformat()),
            )
            (n,) = con.execute(
                "SELECT count(*) FROM external_alert_created WHERE source_id = ? AND at > ?",
                (source_id, cut),
            ).fetchone()
            if n < CAP:
                return
            cur = con.execute(
                "INSERT OR IGNORE INTO external_alert_pauses (source_id, paused_since)"
                " VALUES (?, ?)",
                (source_id, now.isoformat()),
            )
        if cur.rowcount != 1:
            return
        if self._audit is not None:
            self._audit.write(
                "source.vendor_alerts_paused", "success", None, None,
                {"source_id": source_id, "cap": CAP},
            )  # fmt: skip
        detail = (
            f"Alert creation paused for {source_id}: over {CAP} new alert items in an hour."
            " High and Critical still raise; lower ones are stored, not raised."
        )
        self._send_pause(source_id, "vendor_paused", detail, None, now.isoformat(), None)

    def _resume(self, now: datetime) -> None:
        """End each pause whose last hour is back under the cap, with one notice."""
        cut = (now - WINDOW).isoformat()
        with self._meta.connect() as con:
            con.execute("DELETE FROM external_alert_created WHERE at <= ?", (cut,))
            done = con.execute(
                "SELECT p.source_id, p.paused_since FROM external_alert_pauses p"
                " WHERE (SELECT count(*) FROM external_alert_created c"
                " WHERE c.source_id = p.source_id AND c.at > ?) < ?",
                (cut, CAP),
            ).fetchall()
        for source_id, since in done:
            with self._meta.connect() as con:
                held = dict(
                    con.execute(
                        "SELECT severity, count(*) FROM external_alert_held"
                        " WHERE source_id = ? AND held_at >= ? GROUP BY severity",
                        (source_id, since),
                    ).fetchall()
                )
                cur = con.execute(
                    "DELETE FROM external_alert_pauses WHERE source_id = ? AND paused_since = ?",
                    (source_id, since),
                )
            if cur.rowcount != 1:
                continue
            counts = {k: int(held[k]) for k in LEVELS if k in held}
            if self._audit is not None:
                self._audit.write(
                    "source.vendor_alerts_resumed", "success", None, None,
                    {"source_id": source_id, "paused_since": since, "held": counts},
                )  # fmt: skip
            self._pause_notice(source_id, since, now, counts)

    def _pause_notice(
        self, source_id: str, since: str, now: datetime, held: dict[str, int]
    ) -> None:
        total = sum(held.values())
        lasted = int((now - _ts(since)).total_seconds() // 60)
        parts = ", ".join(f"{n} {k}" for k, n in held.items())
        detail = f"Over {CAP} new alert items in an hour; paused for {max(1, lasted)} min. " + (
            f"Held, stored but not raised: {parts}." if total else "No alerts were held."
        )
        self._send_pause(source_id, "vendor_resumed", detail, total, since, now.isoformat())

    def _send_pause(
        self,
        source_id: str,
        kind: AlertKind,
        detail: str,
        count: int | None,
        start: str,
        end: str | None,
    ) -> None:
        """At most two messages a pause, one as it starts and one as it ends (D235). They go
        to the source's chosen targets even when its notify switch is off, or to every alert
        target when it has none, so a pause is never silent (the D236 helper)."""
        if self._settings is None or self._stops is None:
            return
        alert = Alert(
            kind=kind,
            title=source_id,
            detail=detail,
            count=count,
            reason=None,
            range_start=start,
            range_end=end,
            link=f"{self._link}/health#source={source_id}" if self._link else None,
            product=PRODUCT_NAME,
        )
        self._stops.notify(alert, self._settings.get(source_id).target_ids, source_id=source_id)

    def _notify(self, a: _Alert, item_id: str, severity: str | None) -> None:
        """A new vendor alert item or a rise, to the source's targets when it is turned on
        and the alert is at or above the source's minimum severity (D231)."""
        if self._settings is None or self._dispatcher is None:
            return
        n = self._settings.get(a.source_id)
        if not n.notify or not n.target_ids or a.level < LEVELS[n.min_severity]:
            return
        alert = Alert(
            kind="vendor_alert",
            title=a.title,
            detail=f"{a.product} alert {a.alert_id}, {level_name(a.level)} severity",
            count=None,
            reason=None,
            range_start=a.at.isoformat(),
            range_end=None,
            link=f"{self._link}/alerts#item={item_id}" if self._link else None,
            product=PRODUCT_NAME,
            severity=severity,
        )
        self._dispatcher.enqueue(alert, n.target_ids, None, None, source_id=a.source_id)


def _ts(value: Any) -> datetime:
    when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _row(r: list[Any], maps_device: set[str]) -> _Alert:
    """One alert row. The reporting device's name is the subject only when the template maps
    it: a syslog header's host is the sensor that sent the alert."""
    event_id, source, at, observed, product, alert_id, title, sev, ip, src_host, user = r[:11]
    host = src_host or (r[11] if r[12] in maps_device else None)
    return _Alert(
        event_id=str(event_id),
        source_id=str(source),
        at=_ts(at),
        observed=_ts(observed),
        product=str(product),
        alert_id=str(alert_id),
        title=str(title or "")[:300],
        severity=item_severity(sev),
        level=level(sev),
        ip=str(ip) if ip else None,
        host=str(host) if host else None,
        user=str(user) if user else None,
    )


def item_events(
    engine: QueryEngine,
    meta: MetaDB,
    item_id: str,
    sources: list[str],
    start: str | None,
    end: str | None,
    offset: int = 0,
    limit: int = 100,
) -> QueryResult:
    """A page of an item's own alert events, newest first, read only from the item's
    sources and its time range. The caller checks the viewer may read those sources."""
    keys = item_keys(meta, item_id)
    scope = QueryScope(sorted(sources), _ts(start) if start else None, _ts(end) if end else None)
    return engine.run(
        EVENTS_SQL,
        scope,
        {"keys": keys, "limit": max(1, min(limit, MAX_PAGE)), "offset": max(0, offset)},
        timeout_s=20.0,
        name="alert.events",
    )


def is_external(item: Any) -> bool:
    """An item raised from a vendor's alert (D228)."""
    return bool(item.kind == "rule" and str(item.subject).startswith("ext:"))
