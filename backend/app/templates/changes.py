"""What a template update changes for events already stored (F66 release safety).

Events keep the mapping they were parsed with: there is no re-parse. So when a template
version changes a mapping, people need to know the day the new mapping starts (the day
this server first loaded that version) and which saved searches and scheduled searches
(dashboard panels are schedules) filter on a column whose meaning changed. A template
declares its changes in `changes:`; this module records first loads and builds the list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.meta.db import MetaDB
from app.templates.validator import Template

RECENT = 3  # changes listed per template: the newest few


@dataclass(slots=True)
class Affected:
    kind: str  # "saved search" or "schedule"
    id: str
    name: str
    fields: list[str]


@dataclass(slots=True)
class Change:
    template_id: str
    template_name: str
    version: str
    note: str
    fields: list[str]
    since: str | None  # when this server first loaded the version: new events from then on
    current: bool  # the version now in use
    affected: list[Affected] = field(default_factory=list)


def record(meta: MetaDB, templates: list[Template], now: datetime) -> None:
    """Note the first time this server loads each template version."""
    with meta.connect() as con:
        con.executemany(
            "INSERT OR IGNORE INTO template_versions (template_id, version, first_loaded_at)"
            " VALUES (?, ?, ?)",
            [(t.id, t.version, now.isoformat()) for t in templates],
        )


def report(meta: MetaDB, templates: list[Template]) -> list[Change]:
    """Each template's recent declared changes, with when they started here and the
    searches that filter on a changed column."""
    with meta.connect() as con:
        loaded = {
            (r[0], r[1]): str(r[2])
            for r in con.execute(
                "SELECT template_id, version, first_loaded_at FROM template_versions"
            )
        }
        searches = [
            (str(r[0]), str(r[1]), str(r[2]))
            for r in con.execute("SELECT search_id, name, sql FROM saved_searches")
        ]
        schedules = [
            (str(r[0]), str(r[1]), str(r[2]))
            for r in con.execute(
                "SELECT schedule_id, name, target_id FROM schedules WHERE kind = 'search'"
            )
        ]
    out: list[Change] = []
    for t in templates:
        for c in t.changes[:RECENT]:
            change = Change(
                t.id, t.name, c.version, c.note, list(c.fields),
                loaded.get((t.id, c.version)), c.version == t.version,
            )  # fmt: skip
            if c.fields:
                uses = {
                    sid: [f for f in c.fields if re.search(rf"\b{re.escape(f)}\b", sql)]
                    for sid, _, sql in searches
                }
                for sid, name, _ in searches:
                    if uses[sid]:
                        change.affected.append(Affected("saved search", sid, name, uses[sid]))
                for sched_id, name, target in schedules:
                    if uses.get(target):
                        change.affected.append(Affected("schedule", sched_id, name, uses[target]))
            out.append(change)
    return out
