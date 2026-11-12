"""Audit rows that store a person from an AI surface, for a viewer without View people in
AI usage (D242).

These rows keep their names: the audit log is complete and never edited. What the Audit
page and its export return to a viewer without the permission has each name replaced by
"a person", using the same rules as alert items (app.ai.alert_mask): a value in a person's
place that the row does not prove is a machine is masked. The actions masked:

- `ai.sighting`, `ai.sensitive`, `ai.agent_change`: the lines AI Watch saw;
- `ai.review`: the agent approved from its alert (`cc|<person>`);
- `ai.view`, `ai.view_people`: the `person` asked for (`ai.sessions`,
  `ai.person_activity`, `person.timeline`) and the AI flow's `value` for a person
  (`kind` "user");
- `ai.inventory_exclude`, `ai.inventory_include`: a Claude Code agent's `key`
  (`cc|<person>`) and that name anywhere else in the row; other keys (services, MCP
  servers, apps, `mcp|<machine>|...` and `key|<id>` agents) name no one and stay;
- `investigate.graph`: the AI flow (`mode` "ai") for a person (`kind` "user");
- `alert.close`, `alert.reopen`, `alert.mute`, `alert.unmute` about an AI Watch item
  (`kind` "ai_watch", or a subject with an AI Watch key head): the person in its subject,
  as the item stored it, and that name anywhere else in the row. A code `{p:...}` is not a
  name and stays; rows about other kinds of alert are returned as stored.

A `person.timeline` view row stores no person: the person page's own `search.timeline`
row holds who the page is about, and the person page is not an AI surface, so it keeps
the name. Older `person.timeline` view rows that stored the person are masked.

`ai.export_people`, `ai.inventory_export`, and `audit.export` store filters and counts,
never a person, and are returned as stored, as is every other row.
"""

import re
from collections.abc import Iterator
from typing import Any

from app.ai.alert_codes import KEY_HEADS
from app.ai.alert_mask import A_PERSON, name_pattern, names_in
from app.alerts.person_refs import REF

_WATCH = frozenset({"ai.sighting", "ai.sensitive", "ai.agent_change", "ai.review"})
_VIEWS = frozenset({"ai.view", "ai.view_people"})
_INVENTORY = frozenset({"ai.inventory_exclude", "ai.inventory_include"})
_ALERTS = frozenset({"alert.close", "alert.reopen", "alert.mute", "alert.unmute"})
MASKED_ACTIONS = _WATCH | _VIEWS | _INVENTORY | _ALERTS | {"investigate.graph"}
# The subjects AI Watch raises items under (app.ai.watch), people's keys among them.
_WATCH_HEADS = (*KEY_HEADS, "agent:", "service:", "mcp:")

# Where a person stands in the lines app.ai.watch writes for each action, beyond the owner
# patterns alert_mask already knows ("Claude Code, x: ", "(x): new ", "2 people: x, y").
_LINES: dict[str, tuple[re.Pattern[str], ...]] = {
    # "<service or MCP label> by <person or machine>[ (not approved)]"
    "ai.sighting": (re.compile(r"^.* by (.+?)(?: \(not approved\))?$"),),
    # "<person or machine>: <category> xN, ..."
    "ai.sensitive": (re.compile(r"^(.+): [^:]*$"),),
    # "Personal Claude account <email> on <machine>", "N blocked ... by Claude Code for <x>"
    "ai.agent_change": (
        re.compile(r"^Personal Claude account (\S+) on "),
        re.compile(r" by Claude Code for (.+)$"),
    ),
}


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _str(detail: dict[str, Any], key: str) -> str | None:
    value = detail.get(key)
    return value if isinstance(value, str) else None


def _flow_person(detail: dict[str, Any]) -> list[str]:
    """The AI flow's value when it is a person (`kind` "user")."""
    value = _str(detail, "value")
    return [value] if value and detail.get("kind") == "user" else []


def _names(action: str, detail: dict[str, Any]) -> set[str]:
    """The names a row stores, codes left out: a code names no one."""
    return {n for n in _stored_names(action, detail) if not REF.search(n)}


def _about_ai_watch(detail: dict[str, Any]) -> bool:
    kind = detail.get("kind")
    return kind == "ai_watch" or (
        kind is None and (_str(detail, "subject") or "").startswith(_WATCH_HEADS)
    )


def _stored_names(action: str, detail: dict[str, Any]) -> set[str]:
    if action in _ALERTS:
        if not _about_ai_watch(detail):
            return set()
        # Nothing in the row proves a machine, so the subject's key is a person's place.
        return names_in(_str(detail, "subject") or "", [], list(_strings(detail)))
    if action in _VIEWS:
        person = _str(detail, "person")
        flow = _flow_person(detail) if detail.get("surface") == "ai.flow" else []
        return names_in("", [person, *flow] if person else flow, [])
    if action in _INVENTORY:
        key = _str(detail, "key") or ""
        if detail.get("type") != "agent" or not key.startswith("cc|"):
            return set()
        return names_in(f"agent:{key}", [], [])  # nothing in the row proves a machine
    if action == "investigate.graph":
        return names_in("", _flow_person(detail) if detail.get("mode") == "ai" else [], [])
    texts = list(_strings(detail))
    found = names_in("", [], texts)
    agent = detail.get("agent")
    if action == "ai.review" and isinstance(agent, str):
        found |= names_in(f"agent:{agent}", [], [])
    for pattern in _LINES.get(action, ()):
        for text in texts:
            m = pattern.search(text)
            if m:
                found |= names_in("", [m.group(1)], [])
    return found


def _replace(value: Any, pattern: re.Pattern[str]) -> Any:
    """A copy with each name replaced; the stored value is never changed."""
    if isinstance(value, str):
        return pattern.sub(A_PERSON, value)
    if isinstance(value, dict):
        return {k: _replace(v, pattern) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, pattern) for v in value]
    return value


def mask_detail(action: str, detail: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The detail a viewer without the permission sees, and whether it named anyone."""
    if action not in MASKED_ACTIONS:
        return detail, False
    pattern = name_pattern(_names(action, detail))
    if pattern is None:
        return detail, False
    return _replace(detail, pattern), True


def has_names(action: str, detail: dict[str, Any]) -> bool:
    """Does this row name anyone a viewer without the permission may not see?"""
    return action in MASKED_ACTIONS and bool(_names(action, detail))
