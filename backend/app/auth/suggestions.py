"""Suggested source groups (SPEC 3.6, D22). Suggestions only.

One suggestion per template category, and per vendor, that has at least one configured
source. Accepting one creates the group if it does not exist and adds the sources the admin
ticked, all of which must belong to that suggestion. It never removes a source from a group,
never adds a person to one, and so never grants access by itself. Every accept is audited.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.auth.groups import Group, GroupStore
from app.auth.users import User
from app.core.errors import ConflictError
from app.ingest.sources import SourceConfig
from app.meta.audit import AuditLog
from app.templates.validator import Template

Kind = Literal["category", "vendor"]

CATEGORY_NAMES = {
    "identity": "Identity",
    "network": "Network",
    "dns": "DNS",
    "system": "System",
    "application": "Application",
    "findings": "Findings",
}
VENDOR_NAMES = {
    "paloalto": "Palo Alto Networks",
    "windows": "Windows",
    "linux": "Linux",
    "cisco": "Cisco",
    "fortinet": "Fortinet",
    "ubiquiti": "Ubiquiti",
    "isc": "ISC BIND",
    "nlnetlabs": "Unbound",
}


@dataclass(frozen=True, slots=True)
class Suggestion:
    kind: Kind
    key: str
    name: str  # the group name it creates or extends
    group_id: str | None  # an existing group with that name, if any
    source_ids: list[str]  # every source of this category or vendor
    missing: list[str]  # those not yet in the group


def suggest(
    sources: list[SourceConfig],
    template_of: Callable[[str], Template | None],
    groups: list[Group],
) -> list[Suggestion]:
    by: dict[tuple[Kind, str], list[str]] = {}
    for source in sources:
        template = template_of(source.template_id) if source.template_id else None
        if template is None:
            continue  # generic parsers carry no category
        if template.category:
            by.setdefault(("category", template.category), []).append(source.source_id)
        if template.vendor:
            by.setdefault(("vendor", template.vendor), []).append(source.source_id)
    named = {g.name.casefold(): g for g in groups}
    out: list[Suggestion] = []
    for (kind, key), ids in sorted(by.items()):
        name = (CATEGORY_NAMES if kind == "category" else VENDOR_NAMES).get(key, key)
        group = named.get(name.casefold())
        have = set(group.source_ids) if group else set()
        ids = sorted(ids)
        missing = [s for s in ids if s not in have]
        out.append(Suggestion(kind, key, name, group.group_id if group else None, ids, missing))
    return out


def accept(
    suggestions: list[Suggestion],
    kind: Kind,
    key: str,
    source_ids: list[str],
    groups: GroupStore,
    audit: AuditLog,
    actor: User,
    ip: str | None,
) -> Group:
    """Create or extend the suggested group with `source_ids`, re-checked against the
    suggestion computed now (never trusting the client's list)."""
    found = next((s for s in suggestions if s.kind == kind and s.key == key), None)
    if found is None:
        raise ConflictError(f"No suggested {kind} group {key}")
    wanted = sorted(set(source_ids))
    outside = [s for s in wanted if s not in found.source_ids]
    if not wanted or outside:
        raise ConflictError(f"Only sources of the {found.name} suggestion can be added")
    group = (
        groups.get(found.group_id)
        if found.group_id
        else groups.create(found.name, f"Suggested from template {kind}: {key}", actor, ip)
    )
    merged = sorted(set(group.source_ids) | set(wanted))
    result = groups.set_sources(group.group_id, merged, actor, ip)
    audit.write(
        "group.suggestion_accept",
        "success",
        actor.user_id,
        ip,
        {"kind": kind, "key": key, "group_id": group.group_id, "added": wanted},
    )
    return result
