"""AI watch (ADR-0015 rows 9 and 13): one alert for first sightings of AI use that is not
approved, and one for records with sensitive-data signals, per check.

Every check also raises review items on Alerts (ADR-0035 row 11, ADR-0037 row 13), whether
or not alert messages are on: one per service or MCP server that is not approved or not
reviewed yet, one per person and day with sensitive-data signals, and one per agent change.

Runs as the system over every source, like the quiet-source watch (ADR-0014): it reads
only what it needs (service host, person, machine, MCP server name, sensitive counts)
from events received since the last check, and alerts carry a summary, never content.
A first sighting is a (kind, name, person or machine) the watch has not seen before;
sightings are kept, so restarts do not repeat alerts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai.agents import agents
from app.ai.catalog import NON_USAGE, Catalog
from app.ai.usage import HOST_EXPR, MACHINE_EXPR, MCP_EXPR, NO_MCP_NAMES, WHO_EXPR, _values
from app.alerts.dispatch import AlertDispatcher
from app.alerts.items import AlertItems
from app.alerts.render import Alert
from app.core.branding import PRODUCT_NAME
from app.core.errors import ParamInvalidError
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

MAX_TARGETS = 10
BATCH = 20_000  # rows read per check; the cursor moves past what was read
LOOKBACK_FIRST_RUN = timedelta(hours=1)
AGENT_CHECK_EVERY = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class WatchSettings:
    enabled: bool
    include_unreviewed: bool
    sensitive: bool
    target_ids: list[str]
    updated_at: str | None
    updated_by: str | None
    agents: bool = False  # alert when an AI agent changes (ADR-0020 row 3)


@dataclass(slots=True)
class _Review:
    """One service or MCP server that needs review, across a check's rows."""

    label: str
    status: str
    people: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)


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
        items: AlertItems | None = None,
        agent_sources: Callable[[], list[str]] = list,
    ) -> None:
        self._items = items
        # Agent changes come from telemetry sources: an agent item is restricted for a
        # viewer who cannot read them.
        self._agent_sources = agent_sources
        self._meta = meta
        self._engine = engine
        self._catalog = catalog
        self._dispatcher = dispatcher
        self._audit = audit
        self._link = link
        self._clock = clock

    def now(self) -> datetime:
        """The watch's clock, which AI Watch's summary uses too (settable in tests)."""
        return self._clock()

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
            bool(r["agents"]),
        )

    def configure(
        self,
        enabled: bool,
        include_unreviewed: bool,
        sensitive: bool,
        target_ids: list[str],
        actor: str,
        ip: str | None,
        agents: bool = False,
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
                " cursor, updated_at, updated_by, agents) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (id) DO UPDATE SET enabled = excluded.enabled,"
                " include_unreviewed = excluded.include_unreviewed,"
                " sensitive = excluded.sensitive, target_ids = excluded.target_ids,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by,"
                " agents = excluded.agents",
                (
                    int(enabled),
                    int(include_unreviewed),
                    int(sensitive),
                    json.dumps(wanted),
                    now,  # first run starts from now: no flood of old sightings
                    now,
                    actor,
                    int(agents),
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
        """Check events received since the last check; returns alert messages queued.

        Every check raises AI Watch items for the review queue on Alerts (ADR-0035 row 11,
        ADR-0037 row 13): a service or MCP server that is not approved (or not reviewed
        yet), a sensitive-data signal, an agent change. Messages go out only when the
        watch's alerts are turned on, as before."""
        s = self.settings()
        now = self._clock().astimezone(UTC)
        with self._meta.connect() as con:
            # The cursor lives in the settings row; make it before the first check.
            con.execute(
                "INSERT OR IGNORE INTO ai_watch (id, enabled, include_unreviewed, sensitive,"
                " target_ids, cursor, updated_at) VALUES (1, 0, 0, 1, '[]', ?, ?)",
                ((now - LOOKBACK_FIRST_RUN).isoformat(), now.isoformat()),
            )
            row = con.execute("SELECT cursor FROM ai_watch WHERE id = 1").fetchone()
        since = _parse(row["cursor"] if row else None) or now - LOOKBACK_FIRST_RUN
        scope = QueryScope(sources=None)
        rows = self._engine.run(self._sql(since), scope, timeout_s=30.0).rows
        newest = since
        services = {sv.id: sv for sv in self._catalog.services()}
        rules = self._catalog.mcp_rules()
        fresh_ai: list[str] = []
        sensitive: dict[str, dict[str, int]] = {}
        sensitive_src: dict[str, set[str]] = {}
        review: dict[tuple[str, str], _Review] = {}
        for src, kind, name, who, machine, observed, sens in rows:
            seen = _parse(str(observed)) if observed is not None else None
            if seen and seen > newest:
                newest = seen
            subject = str(who or machine or "unknown")
            if kind == "sensitive":
                counts = sensitive.setdefault(subject, {})
                for cat, n in (json.loads(sens) if isinstance(sens, str) else (sens or {})).items():
                    counts[str(cat)] = counts.get(str(cat), 0) + int(n)
                sensitive_src.setdefault(subject, set()).add(str(src))
                continue
            if kind == "service":
                svc = services.get(str(name))
                if svc is not None and svc.kind == NON_USAGE:
                    continue  # a vendor tag on another site is not AI use
                status = svc.status if svc else "unreviewed"
                label = svc.name if svc else str(name)
            else:
                status = self._catalog.mcp_status(str(name), rules)
                label = f"MCP {name}"
            if status == "approved":
                continue
            r = review.setdefault((str(kind), str(name)), _Review(label, str(status)))
            r.people.add(subject)
            r.sources.add(str(src))
            if status == "unreviewed" and not s.include_unreviewed:
                continue
            if self._first(kind, str(name), subject, now):
                fresh_ai.append(
                    f"{label} by {subject}"
                    + (" (not approved)" if status == "not_approved" else "")
                )
        for (kind, name), r in review.items():
            self._raise_use(kind, name, r, since, now)
        # Claude Code sends to the Anthropic API; a service cleared for Confidential data
        # (ADR-0020 row 4) is where sensitive data may go, so it is not an alert.
        api = services.get("anthropic_api")
        if api is not None and api.data_level == "confidential":
            sensitive = {}
        for who, cats in sorted(sensitive.items()):
            self._raise_sensitive(who, cats, sorted(sensitive_src.get(who, set())), since, now)
        sent = 0
        if s.enabled and fresh_ai:
            self._alert("ai_new", fresh_ai, s.target_ids, since, now)
            sent += 1
        if s.enabled and sensitive and s.sensitive:
            lines = [
                f"{who}: " + ", ".join(f"{c} x{n}" for c, n in sorted(cats.items()))
                for who, cats in sorted(sensitive.items())
            ]
            self._alert("ai_sensitive", lines, s.target_ids, since, now)
            sent += 1
        with self._meta.connect() as con:
            con.execute("UPDATE ai_watch SET cursor = ? WHERE id = 1", (newest.isoformat(),))
        sent += self._agents(s, now)
        return sent

    # --- review items (ADR-0035 row 11) --------------------------------------------------

    def _raise_use(self, kind: str, name: str, r: _Review, since: datetime, now: datetime) -> None:
        if self._items is None:
            return
        not_approved = r.status == "not_approved"
        people = len(r.people)
        self._items.raise_item(
            "ai_watch",
            f"{kind}:{name}",
            f"New AI service: {r.label}" if kind == "service" else f"New MCP server: {name}",
            ref_id=f"{kind}:{name}",
            why="Not approved" if not_approved else "Not reviewed yet",
            # A person where the events name one, else the machine or address.
            detail=f"Used by {people}: "
            + ", ".join(sorted(r.people)[:5])
            + (" and more" if people > 5 else ""),
            count=people,
            sources=sorted(r.sources),
            range_start=since.isoformat(),
            range_end=now.isoformat(),
            severity="high" if not_approved and people > 1 else "medium",
        )

    def _raise_sensitive(
        self, who: str, cats: dict[str, int], sources: list[str], since: datetime, now: datetime
    ) -> None:
        if self._items is None:
            return
        self._items.raise_item(
            "ai_watch",
            f"sensitive:{who}",
            f"Sensitive data to AI: {who}",
            # One item per person per day: later signals that day are the same item.
            ref_id=f"sensitive:{who}:{now.date().isoformat()}",
            why=", ".join(f"{c} x{n}" for c, n in sorted(cats.items())),
            count=sum(cats.values()),
            sources=sources,
            range_start=since.isoformat(),
            range_end=now.isoformat(),
            severity="high",
        )

    def _agents(self, s: WatchSettings, now: datetime) -> int:
        """Hourly: an item per agent change, and one alert listing changes not alerted
        before when agent alerts are on (ADR-0020 row 3)."""
        with self._meta.connect() as con:
            row = con.execute("SELECT agents_checked_at FROM ai_watch WHERE id = 1").fetchone()
        last = _parse(row["agents_checked_at"] if row else None)
        if last is not None and now - last < AGENT_CHECK_EVERY:
            return 0
        lines: list[str] = []
        for a in agents(self._engine, None, now):
            who = f" ({', '.join(a.owners)})" if a.owners else ""
            if a.state == "new":  # a new agent is a change too (QA F12); once per agent
                if self._agent_first(a.agent, "agent", "first seen", now):
                    lines.append(f"{a.label}{who}: new agent")
                    self._raise_agent(a.agent, "agent", a.label, f"{a.label}{who}: new agent", now)
                continue
            if a.state != "changed":
                continue
            for item in a.new_items:
                if self._agent_first(a.agent, item["kind"], item["name"], now):
                    line = f"{a.label}{who}: new {item['kind']} {item['name']}"
                    lines.append(line)
                    self._raise_agent(a.agent, f"{item['kind']}:{item['name']}", a.label, line, now)
            if a.recent_peak is not None and self._agent_first(
                a.agent, "busy hour", now.date().isoformat(), now
            ):
                line = (
                    f"{a.label}{who}: {a.recent_peak} events in an hour"
                    f" (usual busiest {a.usual_peak})"
                )
                lines.append(line)
                self._raise_agent(a.agent, f"busy:{now.date()}", a.label, line, now)
        with self._meta.connect() as con:
            con.execute(
                "UPDATE ai_watch SET agents_checked_at = ? WHERE id = 1", (now.isoformat(),)
            )
        if not lines or not (s.enabled and s.agents):
            return 0
        self._alert("ai_agent", lines, s.target_ids, now - AGENT_CHECK_EVERY, now)
        return 1

    def _raise_agent(self, agent: str, what: str, label: str, line: str, now: datetime) -> None:
        if self._items is None:
            return
        self._items.raise_item(
            "ai_watch",
            f"agent:{agent}",
            f"AI agent changed: {label}" if what != "agent" else f"New AI agent: {label}",
            ref_id=f"agent:{agent}:{what}",
            why=line,
            sources=self._agent_sources(),
            range_end=now.isoformat(),
            severity="medium",
        )

    def _agent_first(self, agent: str, kind: str, item: str, now: datetime) -> bool:
        with self._meta.connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO ai_agent_items (agent, item_kind, item, first_seen)"
                " VALUES (?, ?, ?, ?)",
                (agent[:300], kind[:40], item[:200], now.isoformat()),
            )
            return cur.rowcount == 1

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
            {"ai_new": "ai.sighting", "ai_agent": "ai.agent_change"}.get(kind, "ai.sensitive"),
            "success",
            None,
            None,
            {"count": len(lines), "items": lines[:50]},
        )
        if not targets:
            return
        alert = Alert(
            kind="ai_new"
            if kind == "ai_new"
            else "ai_agent"
            if kind == "ai_agent"
            else "ai_sensitive",
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
  SELECT source_id AS src, {HOST_EXPR} AS host, {WHO_EXPR} AS who,
         {MACHINE_EXPR} AS machine, time_observed AS obs, row_number() OVER () AS rid
  FROM events WHERE {after}
),
svc AS (
  SELECT src, 'service' AS kind, cat.service_id AS name, who, machine, obs,
         row_number() OVER (PARTITION BY rid ORDER BY length(cat.domain) DESC) AS rn
  FROM h JOIN cat ON h.host = cat.domain OR ends_with(h.host, '.' || cat.domain)
)
SELECT src, kind, name, who, machine, obs, CAST(NULL AS VARCHAR) AS sens FROM svc WHERE rn = 1
UNION ALL
SELECT src, 'mcp', name, who, machine, obs, NULL FROM (
  SELECT source_id AS src, {MCP_EXPR} AS name, {WHO_EXPR} AS who, device_hostname AS machine,
         time_observed AS obs
  FROM events WHERE {after} AND template_id = 'claude_code_otel'
  UNION ALL
  SELECT source_id, message, {WHO_EXPR}, device_hostname, time_observed
  FROM events WHERE {after} AND template_id = 'mcp_inventory'
) WHERE name IS NOT NULL AND lower(name) NOT IN {NO_MCP_NAMES}
UNION ALL
SELECT source_id, 'sensitive', NULL, {WHO_EXPR}, device_hostname, time_observed,
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
        "agents": s.agents,
    }
