"""AI usage > Inventory (ADR-0038 section 7): one typed list of everything AI seen in the
caller's own view: AI services, agents, MCP servers, and Microsoft 365 apps with a granted
consent. Each row has its type, review status (services and MCP servers only), people,
devices, first and last seen, and where it was seen.

An admin can exclude a row (row 21): it leaves the Active list and stays under Excluded
with who excluded it, when, and why. Exclusion hides nothing from Search, alerts, or AI
Watch; it only sorts this list. Deterministic SQL; no model is called."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.ai.agents import agents
from app.ai.catalog import NON_USAGE, Catalog
from app.ai.consents import CONSENTS_CTE
from app.ai.sessions import _ONE_COPY, _a
from app.ai.usage import Usage
from app.engine.duckdb import QueryEngine, QueryScope
from app.meta.db import MetaDB
from app.search.identity import IdentityMap

ItemType = Literal["service", "agent", "mcp", "m365_app"]
TYPES: tuple[ItemType, ...] = ("service", "agent", "mcp", "m365_app")
TYPE_LABEL = {
    "service": "AI service",
    "agent": "Agent",
    "mcp": "MCP server",
    "m365_app": "Microsoft 365 app",
}
TIMEOUT_S = 30.0
MAX_REASON = 500

# Apps with a granted consent, one row per app (D122: each operation once).
APPS_SQL = f"""
WITH {CONSENTS_CTE}
SELECT coalesce(app, app_id, 'an app with no name') AS name,
       count(DISTINCT lower(who)) AS people, min(ts) AS first_seen, max(ts) AS last_seen
FROM consents
WHERE coalesce(status_id, 1) <> 2
GROUP BY 1
ORDER BY last_seen DESC
LIMIT 2000"""  # noqa: S608  # fixed SQL text

# MCP servers the hooks plugin saw called; telemetry and the MCP inventory are in
# Usage.mcp, and a name seen by both is one row.
HOOK_MCP_SQL = f"""
WITH {_ONE_COPY}
SELECT {_a("mcp_server_name")} AS name,
       count(DISTINCT nullif(actor_user_name, '')) AS people,
       count(DISTINCT device_hostname) AS devices,
       min(coalesce(time, time_observed)), max(coalesce(time, time_observed))
FROM hooks
WHERE {_a("mcp_server_name")} IS NOT NULL
GROUP BY 1
LIMIT 2000"""  # noqa: S608  # fixed SQL text


@dataclass(slots=True)
class Exclusion:
    reason: str
    by: str
    at: str


@dataclass(slots=True)
class Item:
    type: str
    key: str  # unique within its type: service id, agent key, MCP name, app name
    name: str
    status: str | None  # approved, not_approved, unreviewed; None where nothing is reviewed
    people: int
    devices: int | None
    first_seen: str | None
    last_seen: str | None
    where: list[str]
    excluded: Exclusion | None = None


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.astimezone(UTC).isoformat() if isinstance(v, datetime) else str(v)


class Exclusions:
    def __init__(self, meta: MetaDB) -> None:
        self._meta = meta

    def all(self) -> dict[tuple[str, str], Exclusion]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT item_type, item_key, reason, excluded_by, excluded_at"
                " FROM ai_inventory_exclusions"
            ).fetchall()
        return {(str(t), str(k)): Exclusion(str(r), str(b), str(a)) for t, k, r, b, a in rows}

    def set(self, item_type: str, key: str, reason: str, by: str) -> Exclusion:
        at = datetime.now(UTC).isoformat()
        reason = reason.strip()[:MAX_REASON]
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO ai_inventory_exclusions"
                " (item_type, item_key, reason, excluded_by, excluded_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (item_type, item_key) DO UPDATE SET reason = excluded.reason,"
                " excluded_by = excluded.excluded_by, excluded_at = excluded.excluded_at",
                (item_type, key, reason, by, at),
            )
        return Exclusion(reason, by, at)

    def clear(self, item_type: str, key: str) -> bool:
        with self._meta.connect() as con:
            cur = con.execute(
                "DELETE FROM ai_inventory_exclusions WHERE item_type = ? AND item_key = ?",
                (item_type, key),
            )
        return cur.rowcount > 0


def inventory(
    engine: QueryEngine,
    usage: Usage,
    catalog: Catalog,
    allowed: list[str] | None,
    ident: IdentityMap | None,
    excluded: dict[tuple[str, str], Exclusion],
    now: datetime,
    days: int,
) -> tuple[list[Item], list[str]]:
    """Every item seen in the last `days`, newest last seen first, and the sources read."""
    now = now.astimezone(UTC)
    # Open-ended and to the minute, as AI usage asks: the two pages share the answer.
    scope = QueryScope(allowed, (now - timedelta(days=days)).replace(second=0, microsecond=0), None)
    found, sources = usage.all_services(scope)
    out: list[Item] = [
        Item("service", u.service.id, u.service.name, u.service.status, u.people, u.machines,
             u.first_seen, u.last_seen, ["Network and proxy logs"])
        for u in found
        if u.service.kind != NON_USAGE
    ]  # fmt: skip
    for m in usage.mcp(scope, ident):
        out.append(
            Item("mcp", m.name, m.name, m.status, m.people, m.machines, m.first_seen,
                 m.last_seen, sorted(m.sources))
        )  # fmt: skip
    hooks = engine.run(HOOK_MCP_SQL, scope, timeout_s=TIMEOUT_S, intel=False, name="inventory.mcp")
    mcp = {i.key: i for i in out if i.type == "mcp"}
    rules = catalog.mcp_rules()
    for name, people, devices, first, last in hooks.rows:
        f, la = _iso(first), _iso(last)
        it = mcp.get(str(name))
        if it is None:
            status = catalog.mcp_status(str(name), rules)
            out.append(Item("mcp", str(name), str(name), status, int(people or 0),
                            int(devices or 0), f, la, ["Claude Code hooks plugin"]))  # fmt: skip
            continue
        it.people, it.devices = (
            max(it.people, int(people or 0)),
            max(it.devices or 0, int(devices or 0)),
        )
        it.first_seen = min(x for x in (it.first_seen, f) if x) if (it.first_seen or f) else None
        it.last_seen = max(x for x in (it.last_seen, la) if x) if (it.last_seen or la) else None
        it.where = sorted(set(it.where) | {"Claude Code hooks plugin"})
    start = now - timedelta(days=days)
    for a in agents(engine, allowed, now):
        if _iso(a.last_seen) and str(_iso(a.last_seen)) < start.isoformat():
            continue
        out.append(
            Item("agent", a.agent, a.label, None, len(a.owners), 1 if a.machine else 0,
                 a.first_seen, a.last_seen, [a.kind])
        )  # fmt: skip
    apps = engine.run(APPS_SQL, scope, timeout_s=TIMEOUT_S, intel=False, name="inventory.apps")
    for name, people, first, last in apps.rows:
        out.append(
            Item("m365_app", str(name), str(name), None, int(people or 0), None, _iso(first),
                 _iso(last), ["Microsoft 365 consents"])
        )  # fmt: skip
    for it in out:
        it.excluded = excluded.get((it.type, it.key))
    out.sort(key=lambda i: i.last_seen or "", reverse=True)
    return out, sorted(set(sources) | set(apps.sources) | set(hooks.sources))


def export(items: list[Item], fmt: Literal["csv", "json"]) -> str:
    if fmt == "json":
        return json.dumps([asdict(i) for i in items], indent=2)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["type", "name", "status", "people", "devices", "first_seen", "last_seen",
                "where", "excluded", "excluded_by", "excluded_reason"])  # fmt: skip
    for i in items:
        w.writerow([
            TYPE_LABEL[i.type], _cell(i.name), i.status or "", i.people,
            "" if i.devices is None else i.devices, i.first_seen or "", i.last_seen or "",
            "; ".join(i.where), "yes" if i.excluded else "no",
            i.excluded.by if i.excluded else "", _cell(i.excluded.reason) if i.excluded else "",
        ])  # fmt: skip
    return buf.getvalue()


def _cell(v: str) -> str:
    """No formula injection when the file opens in a spreadsheet (names come from logs)."""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
