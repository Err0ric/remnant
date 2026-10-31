"""Built-in detection: refused credentials from one address (ADR-0040, owner 2026-10-30).

Reads the server_events source: when one address has THRESHOLD or more refusals (ingest
tokens, sign-ins, single sign-on, API tokens) in WINDOW, an alert item is raised, one per
address per hour, with what was refused. On by default because it protects this server
and only counts refusals; an admin can turn it off or change the threshold (audited
`detect.refusals`). Sigma correlation rules (counts over time) are not supported yet, so
this runs as a built-in check rather than a rule file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.alerts.items import AlertItems
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.server_events import SOURCE_ID
from app.meta.db import MetaDB

WINDOW = timedelta(minutes=10)
EVERY = timedelta(minutes=1)

COUNT_SQL = """
SELECT src_endpoint_ip AS ip, count(*) AS n,
       list(DISTINCT message ORDER BY message) AS kinds,
       min(coalesce(time, time_observed)) AS first, max(coalesce(time, time_observed)) AS last
FROM events
WHERE template_id = 'server_events' AND nullif(src_endpoint_ip, '') IS NOT NULL
GROUP BY 1
HAVING count(*) >= $threshold
ORDER BY n DESC
LIMIT 50"""

# What an item's "Open in Search" shows: that address's refusals in the window.
ROWS_SQL = (
    "SELECT time, message AS refused, actor_user_name, status_detail AS reason,"
    " src_endpoint_ip, event_id\nFROM events\nWHERE template_id = 'server_events'"
    " AND src_endpoint_ip = {ip}\nORDER BY coalesce(time, time_observed) DESC"
)

LABELS = {
    "server.refused.otlp_token": "ingest token",
    "server.refused.sign_in": "sign-in",
    "server.refused.sso": "single sign-on",
    "server.refused.api_token": "API token",
}


@dataclass(slots=True)
class RefusalSettings:
    enabled: bool
    threshold: int


def load(meta: MetaDB) -> RefusalSettings:
    with meta.connect() as con:
        row = con.execute(
            "SELECT refusal_alert, refusal_threshold FROM install_settings WHERE id = 1"
        ).fetchone()
    return RefusalSettings(bool(row[0]) if row else True, int(row[1]) if row else 10)


def save(meta: MetaDB, enabled: bool, threshold: int, user_id: str) -> RefusalSettings:
    with meta.connect() as con:
        con.execute(
            "INSERT INTO install_settings (id, refusal_alert, refusal_threshold, updated_by)"
            " VALUES (1, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET"
            " refusal_alert = excluded.refusal_alert,"
            " refusal_threshold = excluded.refusal_threshold, updated_by = excluded.updated_by",
            (int(enabled), threshold, user_id),
        )
    return load(meta)


class RefusalWatch:
    def __init__(self, engine: QueryEngine, meta: MetaDB, items: AlertItems) -> None:
        self._engine = engine
        self._meta = meta
        self._items = items
        self._last: datetime | None = None

    def tick(self, now: datetime | None = None) -> int:
        """Raise an item per address over the threshold; returns how many were checked."""
        now = (now or datetime.now(UTC)).astimezone(UTC)
        if self._last is not None and now - self._last < EVERY:
            return 0
        self._last = now
        s = load(self._meta)
        if not s.enabled:
            return 0
        res = self._engine.run(
            COUNT_SQL,
            QueryScope([SOURCE_ID], now - WINDOW, now),
            {"threshold": s.threshold},
            timeout_s=20.0,
            name="detect.refusals",
        )
        for ip, n, kinds, first, last in res.rows:
            self._raise(str(ip), int(n), list(kinds or []), first, last, now)
        return len(res.rows)

    def _raise(
        self, ip: str, n: int, kinds: list[Any], first: Any, last: Any, now: datetime
    ) -> None:
        what = ", ".join(LABELS.get(str(k), str(k)) for k in kinds)
        self._items.raise_item(
            "rule",
            f"refusals:{ip}",
            f"Refused credentials: {n} from {ip} in 10 minutes",
            ref_id=f"refusals:{ip}:{now:%Y%m%d%H}",
            why="Refused credentials from one address",
            detail=f"{n} refusals ({what}) from {ip}, a sign of guessing tokens or passwords."
            " Open in Search: " + ROWS_SQL.replace("{ip}", "'" + ip.replace("'", "''") + "'"),
            count=n,
            sources=[SOURCE_ID],
            range_start=str(first) if first else (now - WINDOW).isoformat(),
            range_end=str(last) if last else now.isoformat(),
            severity="high",
            refresh=True,
        )
