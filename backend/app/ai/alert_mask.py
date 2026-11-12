"""AI Watch alert items for a viewer without View people in AI usage (D242, ADR-0029 G2).

Items store references in place of names (app.ai.alert_codes) and are read with the
names filled in from their people; any an older version stored with names keep them.
Either way, each name an item is about is replaced by "a person" when it is read: the
item's people, the person in its subject, the owners AI Watch writes into agent lines,
and the people it lists as using a service or MCP server.
Counts stay, and so do machines the item proves are machines; a value in a person's place
that may be a person is masked. Other kinds are not AI surfaces and are never changed here.
"""

import re
from collections.abc import Iterable
from dataclasses import replace

from app.alerts.items import AlertItem, ItemEvent, Mute

A_PERSON = "a person"
_NOT_NAMES = {"", "?", "unknown", "no person matched", A_PERSON}
# People in the lines AI Watch writes (app.ai.watch, app.ai.agents._label), items stored
# before people were kept apart (migration 57) included: owners of an agent, and who used a
# service or MCP server ("2 people: x, y and more"; before 2026-10-22 "Used by 2: x, y",
# people and machines in one list, so all of it).
_OWNER_PATTERNS = (
    re.compile(r"Claude Code, (.+?): "),
    re.compile(r"In use; owner (.+?)(?:; devices? |$)"),
    re.compile(r" \(([^()]+)\): (?:new |\d+ events in an hour)"),
    re.compile(r"\b\d+ (?:person|people): (.+?)(?=\. \d+ devices? not matched to a person: |$)"),
    re.compile(r"\bUsed by \d+: (.+)$"),
)


def names_in(
    subject: str,
    people: Iterable[str],
    texts: Iterable[str | None],
    devices: Iterable[str] = (),
) -> set[str]:
    """Every name an AI Watch item is about, as stored. The key in its subject is a name
    unless the item proves it is a machine: listed in its devices (a sensitive-data or
    blocked-calls item keyed by its machine) or a "Claude Code on <machine>" label."""
    found = set(people)
    texts = list(texts)
    prefix, _, rest = subject.partition(":")
    cc = prefix == "agent" and rest.startswith("cc|")
    key = rest[3:] if cc else rest
    if cc or prefix in ("sensitive", "account"):
        on = re.compile(rf"claude code on {re.escape(key)}(?=$|[,;:\s])", re.IGNORECASE)
        machine = key not in found and "@" not in key and (
            key in set(devices) or any(on.search(t or "") for t in texts)
        )  # fmt: skip
        if prefix == "account" or not machine:
            found.add(key)
    for text in texts:
        for pattern in _OWNER_PATTERNS:
            for m in pattern.finditer(text or ""):
                found.update(n.strip().removesuffix(" and more") for n in m.group(1).split(", "))
    return {n for n in found if n.strip().lower() not in _NOT_NAMES}


def name_pattern(names: set[str]) -> re.Pattern[str] | None:
    """Each name, and the part of an email before the @ when it is 3 or more characters,
    as a word, longest first, ignoring case."""
    forms = set(names)
    forms.update(n.split("@", 1)[0] for n in names if "@" in n and len(n.split("@", 1)[0]) >= 3)
    forms = {f for f in forms if f}
    if not forms:
        return None
    alts = "|".join(re.escape(f) for f in sorted(forms, key=lambda f: (-len(f), f)))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


def _scrub(text: str | None, pattern: re.Pattern[str] | None) -> str | None:
    if text is None or pattern is None:
        return text
    return pattern.sub(A_PERSON, text)


def _sub(text: str, pattern: re.Pattern[str] | None) -> str:
    return pattern.sub(A_PERSON, text) if pattern is not None else text


def has_names(item: AlertItem) -> bool:
    """Does this AI Watch item name anyone (what an unmasked answer shows)?"""
    return item.kind == "ai_watch" and bool(_names(item))


def _names(i: AlertItem) -> set[str]:
    return names_in(i.subject, i.people, _texts(i), i.devices)


def _texts(i: AlertItem) -> list[str | None]:
    return [i.title, i.detail, i.why, i.ref_id, i.entity, *i.changes]


def mask_item(item: AlertItem) -> AlertItem:
    """The item as a viewer without the permission sees it: no person's name anywhere and
    no people listed. Not an AI Watch item: unchanged."""
    if item.kind != "ai_watch":
        return item
    p = name_pattern(_names(item))
    return replace(
        item,
        subject=_sub(item.subject, p),
        ref_id=_scrub(item.ref_id, p),
        title=_sub(item.title, p),
        detail=_sub(item.detail, p),
        why=_scrub(item.why, p),
        note=_scrub(item.note, p),
        resolved=_scrub(item.resolved, p),
        entity=_scrub(item.entity, p),
        changes=[_sub(c, p) for c in item.changes],
        people=[],
        history=[
            ItemEvent(h.at, h.user_id, h.action, h.reason, _scrub(h.note, p)) for h in item.history
        ],
    )


def mask_mute(mute: Mute) -> Mute:
    """A mute of AI Watch items keeps its kind and subject's shape, without the name."""
    if mute.kind != "ai_watch":
        return mute
    p = name_pattern(names_in(mute.subject, [], [mute.title]))
    return replace(mute, subject=_sub(mute.subject, p), title=_sub(mute.title, p))
