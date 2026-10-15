"""AI watch (ADR-0015 rows 9 and 13): one alert for first sightings of AI use that is not
approved, and one for records with sensitive-data signals, per check.

Runs as the system over every source, like the quiet-source watch (ADR-0014): it reads
only what it needs (service host, person, machine, MCP server name, sensitive counts)
from events received since the last check, and alerts carry a summary, never content.
A first sighting is a (kind, name, person or machine) the watch has not seen before;
sightings are kept, so restarts do not repeat alerts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.catalog import Catalog
from app.ai.usage import HOST_EXPR, MACHINE_EXPR, MCP_EXPR, NO_MCP_NAMES, WHO_EXPR, _values
from app.alerts.dispatch import AlertDispatcher
from app.alerts.render import Alert
from app.core.branding import PRODUCT_NAME
from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

MAX_TARGETS = 10
BATCH = 20_000  # rows read per check; the cursor moves past what was read
LOOKBACK_FIRST_RUN = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class WatchSettings:
    enabled: bool
    include_unreviewed: bool
    sensitive: bool
    target_ids: list[str]
    updated_at: str | None
    updated_by: str | None


def _ts(value: datetime) -> str:
    return f"TIMESTAMPTZ '{value.astimezone(UTC).isoformat()}'"


class AiWatch:
    def __init__(
        self,
        meta: MetaDB,
        engine: QueryEngine,
        catalog: Catalog,
        dispatcher: AlertDispatcher,
        audit: AuditLog,
        link: str | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._engine = engine
        self._catalog = catalog
        self._dispatcher = dispatcher
        self._audit = audit
        self._link = link
        self._clock = clock

    def settings(self) -> WatchSettings:
        with self._meta.connect() as con:
            r = con.execute("SELECT * FROM ai_watch WHERE id = 1").fetchone()
        if r is None:
            return WatchSettings(False, False, True, [], None, None)
        return WatchSettings(
            bool(r["enabled"]),
            bool(r["include_unreviewed"]),
            bool(r["sensitive"]),
            list(json.loads(r["target_ids"])),
            r["updated_at"],
            r["updated_by"],
        )

    def configure(
        self,
        enabled: bool,
        include_unreviewed: bool,
        sensitive: bool,
        target_ids: list[str],
        actor: str,
        ip: str | None,
    ) -> WatchSettings:
        wanted = sorted(set(target_ids))
        if len(wanted) > MAX_TARGETS:
            raise ParamInvalidError(f"At most {MAX_TARGETS} alert targets")
        before = self.settings()
        now = self._clock().astimezone(UTC).isoformat()
        with self._meta.connect() as con:
            known = {r[0] for r in con.execute("SELECT target_id FROM alert_targets")}
            if set(wanted) - known:
                raise ParamInvalidError("Unknown alert target")
            con.execute(
                "INSERT INTO ai_watch (id, enabled, include_unreviewed, sensitive, target_ids,"
                " cursor, updated_at, updated_by) VALUES (1, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET enabled = excluded.enabled,"
                " include_unreviewed = excluded.include_unreviewed,"
                " sensitive = excluded.sensitive, target_ids = excluded.target_ids,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (
                    int(enabled),
                    int(include_unreviewed),
                    int(sensitive),
                    json.dumps(wanted),
                    now,  # first run starts from now: no flood of old sightings
                    now,
                    actor,
                ),
            )
        after = self.settings()
        self._audit.write(
            "ai.watch_change",
            "success",
            actor,
            ip,
            {"from": _plain(before), "to": _plain(after)},
        )
        return after

    # --- checking ------------------------------------------------------------------------

    def tick(self) -> int:
        """Check events received since the last check; returns alerts queued."""
        s = self.settings()
        if not s.enabled:
            return 0
        with self._meta.connect() as con:
            row = con.execute("SELECT cursor FROM ai_watch WHERE id = 1").fetchone()
        now = self._clock().astimezone(UTC)
        since = _parse(row["cursor"] if row else None) or now - LOOKBACK_FIRST_RUN
        scope = QueryScope(sources=None)
        rows = self._engine.run(self._sql(since), scope, timeout_s=30.0).rows
        newest = since
        services = {sv.id: sv for sv in self._catalog.services()}
        rules = self._catalog.mcp_rules()
        fresh_ai: list[str] = []
        sensitive: dict[str, dict[str, int]] = {}
        for kind, name, who, machine, observed, sens in rows:
            seen = _parse(str(observed)) if observed is not None else None
            if seen and seen > newest:
                newest = seen
            subject = str(who or machine or "unknown")
            if kind == "sensitive":
                counts = sensitive.setdefault(subject, {})
                for cat, n in (json.loads(sens) if isinstance(sens, str) else (sens or {})).items():
                    counts[str(cat)] = counts.get(str(cat), 0) + int(n)
                continue
            if kind == "service":
                svc = services.get(str(name))
                status = svc.status if svc else "unreviewed"
                label = svc.name if svc else str(name)
            else:
                status = self._catalog.mcp_status(str(name), rules)
                label = f"MCP {name}"
            if status == "approved" or (status == "unreviewed" and not s.include_unreviewed):
                continue
            if self._first(kind, str(name), subject, now):
                fresh_ai.append(
                    f"{label} by {subject}"
                    + (" (not approved)" if status == "not_approved" else "")
                )
        sent = 0
        if fresh_ai:
            self._alert("ai_new", fresh_ai, s.target_ids, since, now)
            sent += 1
        if sensitive and s.sensitive:
            lines = [
                f"{who}: " + ", ".join(f"{c} x{n}" for c, n in sorted(cats.items()))
                for who, cats in sorted(sensitive.items())
            ]
            self._alert("ai_sensitive", lines, s.target_ids, since, now)
            sent += 1
        with self._meta.connect() as con:
            con.execute("UPDATE ai_watch SET cursor = ? WHERE id = 1", (newest.isoformat(),))
        return sent

    def _first(self, kind: str, name: str, subject: str, now: datetime) -> bool:
        with self._meta.connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO ai_sightings (kind, name, subject, first_seen)"
                " VALUES (?, ?, ?, ?)",
                (kind, name[:200], subject[:200], now.isoformat()),
            )
            return cur.rowcount == 1

    def _alert(
        self, kind: str, lines: list[str], targets: list[str], since: datetime, now: datetime
    ) -> None:
        detail = "; ".join(lines[:5]) + (f"; and {len(lines) - 5} more" if len(lines) > 5 else "")
        self._audit.write(
            "ai.sighting" if kind == "ai_new" else "ai.sensitive",
            "success",
            None,
            None,
            {"count": len(lines), "items": lines[:50]},
        )
        if not targets:
            return
        alert = Alert(
            kind="ai_new" if kind == "ai_new" else "ai_sensitive",
            title="AI watch",
            detail=detail,
            count=len(lines),
            reason=None,
            range_start=since.isoformat(),
            range_end=now.isoformat(),
            link=f"{self._link}/ai" if self._link else None,
            product=PRODUCT_NAME,
        )
        self._dispatcher.enqueue(alert, targets, None, None)

    def _sql(self, since: datetime) -> str:
        pairs = self._catalog.domain_table()
        after = f"time_observed > {_ts(since)}"
        return f"""
SELECT * FROM (
WITH cat(service_id, domain) AS (VALUES {_values(pairs)}),
h AS (
  SELECT {HOST_EXPR} AS host, {WHO_EXPR} AS who, {MACHINE_EXPR} AS machine,
         time_observed AS obs, row_number() OVER () AS rid
  FROM events WHERE {after}
),
svc AS (
  SELECT 'service' AS kind, cat.service_id AS name, who, machine, obs,
         row_number() OVER (PARTITION BY rid ORDER BY length(cat.domain) DESC) AS rn
  FROM h JOIN cat ON h.host = cat.domain OR ends_with(h.host, '.' || cat.domain)
)
SELECT kind, name, who, machine, obs, CAST(NULL AS VARCHAR) AS sens FROM svc WHERE rn = 1
UNION ALL
SELECT 'mcp', name, who, machine, obs, NULL FROM (
  SELECT {MCP_EXPR} AS name, {WHO_EXPR} AS who, device_hostname AS machine, time_observed AS obs
  FROM events WHERE {after} AND template_id = 'claude_code_otel'
  UNION ALL
  SELECT message, {WHO_EXPR}, device_hostname, time_observed
  FROM events WHERE {after} AND template_id = 'mcp_inventory'
) WHERE name IS NOT NULL AND lower(name) NOT IN {NO_MCP_NAMES}
UNION ALL
SELECT 'sensitive', NULL, {WHO_EXPR}, device_hostname, time_observed,
       json_extract(unmapped, '$.attr.sensitive')::VARCHAR
FROM events WHERE {after} AND template_id = 'claude_code_otel'
  AND TRY_CAST(json_extract_string(unmapped, '$.attr.sensitive_total') AS BIGINT) > 0
) ORDER BY obs
LIMIT {BATCH}"""  # noqa: S608  # fixed SQL text; domains checked against DOMAIN in _values


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        v = datetime.fromisoformat(value.replace(" ", "T", 1) if "T" not in value else value)
    except ValueError:
        return None
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def _plain(s: WatchSettings) -> dict[str, Any]:
    return {
        "enabled": s.enabled,
        "include_unreviewed": s.include_unreviewed,
        "sensitive": s.sensitive,
        "targets": s.target_ids,
    }
