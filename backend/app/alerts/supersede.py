"""Alerts a rule change retired (D213, proposed): on upgrade, each open alert is checked
against the current rules, and one they would not raise now is closed by the server with
the reason Superseded by rule change, one audit row each.

Conservative on purpose: only rules this module knows were changed are re-checked, an
alert someone already acted on (a reopen or any other decision in its history, or a note)
is left open, and anything it cannot read for certain stays open.

Rules re-checked today:
- AI agent changed (ADR-0043 row 8): a built-in Claude Code tool (any tool name without the
  `mcp__` prefix) never raises "changed". An agent-change alert whose every change is a
  built-in tool is superseded; one with an MCP server or tool, or any other kind of change,
  stays open.
- Source gap (ADR-0037 owner answer 3, D168): a gap alert is raised only for a source that
  exists and has Alert if quiet on. A gap alert for a source that was removed, or whose
  quiet alert is off (for example the D168 change on push sources), is superseded.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.alerts.items import SUPERSEDED_NOTE, AlertItem
from app.meta.db import MetaDB

# Bump when a rule change retires alerts, so the check runs again on that upgrade.
RULES_REVISION = "2026-11-06"
NOTE = SUPERSEDED_NOTE


@dataclass(frozen=True, slots=True)
class Rules:
    sources: frozenset[str]  # sources that exist
    watched: frozenset[str]  # sources with Alert if quiet on


def current_rules(meta: MetaDB) -> Rules:
    with meta.connect() as con:
        sources = {r[0] for r in con.execute("SELECT source_id FROM sources")}
        watched = {r[0] for r in con.execute("SELECT source_id FROM source_watches")}
    return Rules(frozenset(sources), frozenset(watched))


def _built_in_change(line: str) -> bool | None:
    """True for "<agent>: new Tool <name>" (or "new Tool <name>", as alerts from before
    ADR-0043 wrote it) with a built-in name, False for any other change line, None when
    the line is not one the agent check writes."""
    head, sep, what = line.rpartition(": new ")
    if not sep or not head:
        if not line.startswith("new "):
            return None
        what = line.removeprefix("new ")
    if what.startswith("Tool "):
        return not what.removeprefix("Tool ").startswith("mcp__")
    return False


def _agent_change(item: AlertItem) -> bool:
    if item.kind != "ai_watch" or not item.subject.startswith("agent:"):
        return False
    if item.rule == "agent_change":
        return True
    ref = item.ref_id or ""
    what = ref[len(item.subject) + 1 :] if ref.startswith(item.subject + ":") else ""
    return bool(what) and what != "agent" and not what.startswith("busy:")


def still_raised(item: AlertItem, rules: Rules) -> bool:
    """Would the current rules raise this alert now? True whenever unsure."""
    if _agent_change(item):
        lines = item.changes or [item.why or ""]
        kinds = [_built_in_change(line) for line in lines]
        if not kinds or any(k is None for k in kinds):
            return True  # a line this check cannot read: keep it
        return not all(kinds)
    if item.kind == "gap" and "/" not in item.subject:
        return item.subject in rules.sources and item.subject in rules.watched
    return True
