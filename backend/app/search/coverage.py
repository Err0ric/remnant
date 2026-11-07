"""Why an address has no events (ADR-0045 Part B).

When the caller's sources hold no event naming an address in the range, this says, one
category at a time, what was searched and what each source could record. Every line comes
from facts the server holds (B3): the search itself, each source's template category and
mapped fields, and whether the source was receiving (its last event, its kind's quiet
threshold, and whether it is turned off). Nothing is inferred about network paths, and no
model writes any of it (B5). Only sources the caller may read are named or counted (B4).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.quiet import default_quiet_s
from app.ingest.sources import SourceConfig
from app.ingest.watcher import SourceStatus
from app.templates.validator import Template

# The categories whose absence is worth saying (B2), in the order they are shown.
HEADLINE = ("dns", "network", "system", "identity")
ORDER = (*HEADLINE, "application", "findings", "other")
ADDRESS_COLUMNS = frozenset({"src_endpoint_ip", "dst_endpoint_ip", "device_ip"})

COUNT_SQL = """SELECT source_id, count(*)
FROM events
WHERE (src_endpoint_ip = $v OR dst_endpoint_ip = $v OR device_ip = $v OR device_hostname = $v)
  AND coalesce(template_id, '') <> 'proxmox_inventory'
GROUP BY 1"""


@dataclass(slots=True)
class SourceNote:
    source_id: str
    # receiving | not_receiving (with `since`, its last event) | never | off
    state: str
    since: str | None = None
    records_address: bool = True  # its template maps an address field (or the syslog host)


@dataclass(slots=True)
class CategoryLine:
    category: str
    sources: list[SourceNote] = field(default_factory=list)


@dataclass(slots=True)
class Coverage:
    value: str
    events: int  # events naming the value in the range; the block shows only at 0
    categories: list[CategoryLine]
    missing: list[str]  # headline categories the caller has no source for
    inventory_source: bool  # the caller can read a Proxmox inventory source
    restricted: bool  # the caller cannot read every source: "were not searched"
    read: list[str]  # sources searched, for the audit row


def _category(source: SourceConfig, template: Template | None) -> str:
    if source.kind == "proxmox":
        return "inventory"
    category = template.category if template else ""
    return category if category in ORDER else "other"


def _records(source: SourceConfig, template: Template | None) -> bool:
    if source.format == "syslog":
        return True  # the envelope names the sending host
    if template is None:
        return True  # a generic parser keeps every field it finds; not known to lack one
    return bool(ADDRESS_COLUMNS & set(template.mapping.fields))


def _state(source: SourceConfig, st: SourceStatus | None, end: datetime) -> tuple[str, str | None]:
    if not source.enabled:
        return "off", None
    last = st.last_event_at if st else None
    if last is None:
        return "never", None
    if end - last > timedelta(seconds=default_quiet_s(source.kind)):
        return "not_receiving", last.isoformat()
    return "receiving", None


def coverage(
    engine: QueryEngine,
    scope: QueryScope,
    value: str,
    sources: list[SourceConfig],
    template_of: Callable[[str], Template | None],
    statuses: Mapping[str, SourceStatus],
    now: datetime,
    restricted: bool,
) -> Coverage:
    """`sources` are the caller's own; `scope` is built from the same list."""
    counts = {
        str(s): int(n)
        for s, n in engine.run(COUNT_SQL, scope, {"v": value.strip()}, timeout_s=20).rows
    }
    end = min(scope.end or now, now)
    lines: dict[str, CategoryLine] = {}
    inventory = False
    for source in sources:
        tid = source.template_id
        template = template_of(tid) if tid and tid != "auto" else None
        category = _category(source, template)
        if category == "inventory":
            inventory = True
            continue
        state, since = _state(source, statuses.get(source.source_id), end)
        note = SourceNote(source.source_id, state, since, _records(source, template))
        lines.setdefault(category, CategoryLine(category)).sources.append(note)
    return Coverage(
        value=value,
        events=sum(counts.values()),
        categories=[lines[c] for c in ORDER if c in lines],
        missing=[c for c in HEADLINE if c not in lines],
        inventory_source=inventory,
        restricted=restricted,
        read=sorted(s.source_id for s in sources),
    )
