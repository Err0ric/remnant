"""One Sigma rule file to a checked, runnable condition (ADR-0006 rows 3, 4, 7).

Rule files are untrusted input. A rule is refused, with a reason a person can act on, when:
- the file is over `MAX_RULE_BYTES`, is not one YAML mapping, or uses aliases or deep
  nesting (`core/safeyaml.py`);
- it is a correlation rule or a multi-document collection (out of scope for Slice 4);
- its logsource names no product, service, or category;
- it is a Windows rule whose service or category cannot be narrowed to a channel (below);
- conversion fails (unsupported field, value, or regex; see `sigma_backend.py`);
- the resulting query does not pass the query guard.

Windows narrowing. Sigma leaves the log out of a rule's detection and relies on the
backend's pipeline to add it, so a `category: process_creation` rule says nothing about
Sysmon event 1. Without that, `Image|endswith: \\cmd.exe` would also match Sysmon network
and image load events, which carry `Image` too. As pySigma's reference Windows and Sysmon
pipelines do, a Windows rule gets:
- `service: X`: the event's channel must be one of X's channels;
- a Sysmon category: the Sysmon channel and the category's Sysmon event ids;
- a PowerShell category: the PowerShell channel and its event id.

Process creation also through Security event 4688: a `process_creation` rule whose fields
all exist in 4688 (`AUDIT_4688_FIELDS`) also matches Security 4688 events, with `Image`,
`ParentImage`, and `LogonId` read from their 4688 names. A rule that uses any other field
(for example `OriginalFileName`, `Hashes`, `User`, or `ParentCommandLine`, which 4688 does
not record or records differently) runs on Sysmon only, so a filter on a field 4688 lacks
can never silently stop filtering.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

import yaml
from sigma.collection import SigmaCollection
from sigma.exceptions import SigmaError
from sigma.pipelines.common import windows_logsource_mapping
from sigma.rule import SigmaDetection, SigmaDetectionItem, SigmaRule
from sigma.types import SigmaFieldReference

from app.core import safeyaml
from app.core.errors import QueryRejectedError, RuleRejectedError
from app.detect.logsource import LogSource
from app.detect.pipelines.compat import compat_pipeline, field_expression
from app.detect.sigma_backend import DuckDBBackend, SecurityAuditBackend, sql_literal
from app.engine.guard import guard

MAX_RULE_BYTES = 512 * 1024  # SigmaHQ's largest (vulnerable drivers) is about 290 KB
_TEXT_MAX = 300  # title, author, id, level, status as stored and shown

SYSMON_CHANNEL = "Microsoft-Windows-Sysmon/Operational"
# Generic Sigma categories to Sysmon event ids (same table as pySigma's Sysmon pipeline).
SYSMON_CATEGORY_EVENTS: dict[str, tuple[int, ...]] = {
    "process_creation": (1,),
    "file_change": (2,),
    "network_connection": (3,),
    "sysmon_status": (4, 16),
    "process_termination": (5,),
    "driver_load": (6,),
    "image_load": (7,),
    "create_remote_thread": (8,),
    "raw_access_thread": (9,),
    "process_access": (10,),
    "file_event": (11,),
    "registry_add": (12,),
    "registry_delete": (12,),
    "registry_set": (13,),
    "registry_rename": (14,),
    "registry_event": (12, 13, 14),
    "create_stream_hash": (15,),
    "pipe_created": (17, 18),
    "wmi_event": (19, 20, 21),
    "dns_query": (22,),
    "file_delete": (23,),
    "clipboard_capture": (24,),
    "process_tampering": (25,),
    "file_delete_detected": (26,),
    "file_block_executable": (27,),
    "file_block_shredding": (28,),
    "file_executable_detected": (29,),
    "sysmon_error": (255,),
}
# PowerShell categories to (service, event id), as pySigma's Windows pipeline maps them.
POWERSHELL_CATEGORY_EVENTS: dict[str, tuple[str, int]] = {
    "ps_module": ("powershell", 4103),
    "ps_script": ("powershell", 4104),
    "ps_classic_start": ("powershell-classic", 400),
    "ps_classic_provider_start": ("powershell-classic", 600),
    "ps_classic_script": ("powershell-classic", 800),
}


# Sigma fields a process_creation rule may use and still run on Security 4688 events.
AUDIT_4688_FIELDS = frozenset({"Image", "ParentImage", "CommandLine", "LogonId", "Computer"})
AUDIT_4688 = "lower({channel}) IN ('security') AND {event_id} IN ('4688')"


def _fields(rule: SigmaRule) -> set[str | None]:
    """Every field name the detection uses (None for keywords), including fields that a
    `|fieldref` value compares against."""
    out: set[str | None] = set()

    def walk(item: SigmaDetection | SigmaDetectionItem) -> None:
        if isinstance(item, SigmaDetectionItem):
            out.add(item.field)
            out.update(v.field for v in item.value if isinstance(v, SigmaFieldReference))
        else:
            for child in item.detection_items:
                walk(child)

    for detection in rule.detection.detections.values():
        walk(detection)
    return out


@dataclass(frozen=True, slots=True)
class CompiledRule:
    rule_id: str  # the rule's own `id`, or the file's sha256 when it has none
    title: str
    author: str  # "" when the rule names none; shown as "author not stated"
    level: str
    status: str
    logsource: LogSource
    condition: str  # WHERE condition on the events view, narrowing included
    sha256: str  # of the exact file bytes
    tags: tuple[str, ...] = field(default_factory=tuple)
    security_4688: bool = False  # process creation also matched on Security 4688


def _channels(service: str) -> list[str]:
    channels = windows_logsource_mapping.get(service)
    if channels is None:
        raise RuleRejectedError(f"Windows service {service!r} is not supported yet")
    return [channels] if isinstance(channels, str) else list(channels)


def _in(expr: str, values: list[str], lower: bool = False) -> str:
    if lower:
        expr = f"lower({expr})"
        values = [v.lower() for v in values]
    return f"{expr} IN ({', '.join(sql_literal(v) for v in values)})"


def windows_narrowing(ls: LogSource) -> str | None:
    """The channel and event id condition a Windows rule needs, or None for other rules."""
    if ls.product != "windows":
        return None
    parts: list[str] = []
    channel = field_expression("Channel")
    event_id = field_expression("EventID")
    if ls.service is not None:
        parts.append(_in(channel, _channels(ls.service), lower=True))
    if ls.category is not None:
        if ls.category in SYSMON_CATEGORY_EVENTS:
            parts.append(_in(channel, [SYSMON_CHANNEL], lower=True))
            parts.append(_in(event_id, [str(i) for i in SYSMON_CATEGORY_EVENTS[ls.category]]))
        elif ls.category in POWERSHELL_CATEGORY_EVENTS:
            service, eid = POWERSHELL_CATEGORY_EVENTS[ls.category]
            parts.append(_in(channel, _channels(service), lower=True))
            parts.append(_in(event_id, [str(eid)]))
        else:
            raise RuleRejectedError(f"Windows category {ls.category!r} is not supported yet")
    if not parts:  # product: windows alone: any Windows event
        return None
    return " AND ".join(parts)


def _text(doc: dict[str, Any], key: str) -> str:
    value = doc.get(key)
    if isinstance(value, list):  # some rules list authors
        value = ", ".join(str(v) for v in value)
    return str(value).strip()[:_TEXT_MAX] if value is not None else ""


def compile_rule(data: bytes) -> CompiledRule:
    """Parse, convert, narrow, and guard-check one rule file."""
    if len(data) > MAX_RULE_BYTES:
        raise RuleRejectedError(f"Rule file is larger than {MAX_RULE_BYTES // 1024} KB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuleRejectedError("Rule file is not UTF-8 text") from exc
    try:
        doc = safeyaml.load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise RuleRejectedError(f"Rule file is not valid YAML{where}") from exc
    if not isinstance(doc, dict):
        raise RuleRejectedError("Rule file must be one YAML mapping")
    if "correlation" in doc or "action" in doc:
        raise RuleRejectedError("Correlation rules and rule collections are not supported yet")
    if not isinstance(doc.get("detection"), dict):
        raise RuleRejectedError("Rule has no detection block")
    logsource = doc.get("logsource")
    ls = LogSource.from_mapping(logsource if isinstance(logsource, dict) else None)
    if ls.is_empty():
        raise RuleRejectedError("Rule logsource names no product, service, or category")
    narrowing = windows_narrowing(ls)
    try:
        collection = SigmaCollection.from_dicts([doc])
        detection = _convert(collection, DuckDBBackend())
        audit: str | None = None
        if (
            ls.product == "windows"
            and ls.category == "process_creation"
            and ls.service is None
            and isinstance(collection.rules[0], SigmaRule)
            and _fields(collection.rules[0]) - {None} <= AUDIT_4688_FIELDS
        ):
            audit = _convert(SigmaCollection.from_dicts([doc]), SecurityAuditBackend())
    except SigmaError as exc:
        raise RuleRejectedError(
            f"Rule cannot be converted: {str(exc).splitlines()[0][:200]}"
        ) from exc
    condition = f"({narrowing}) AND ({detection})" if narrowing else detection
    if audit is not None:
        audit_narrowing = AUDIT_4688.format(
            channel=field_expression("Channel"), event_id=field_expression("EventID")
        )
        condition = f"({condition}) OR (({audit_narrowing}) AND ({audit}))"
    try:
        guard(f"SELECT event_id FROM events WHERE {condition}", frozenset({"events"}))  # noqa: S608  # the compiled condition is what is checked
    except QueryRejectedError as exc:
        raise RuleRejectedError(f"Rule query refused by the guard: {exc}") from exc
    sha = hashlib.sha256(data).hexdigest()
    tags = doc.get("tags")
    return CompiledRule(
        rule_id=_text(doc, "id") or sha,
        title=_text(doc, "title") or "(untitled rule)",
        author=_text(doc, "author"),
        level=_text(doc, "level"),
        status=_text(doc, "status"),
        logsource=ls,
        condition=condition,
        sha256=sha,
        tags=tuple(str(t)[:100] for t in tags[:50]) if isinstance(tags, list) else (),
        security_4688=audit is not None,
    )


def _convert(collection: SigmaCollection, backend: DuckDBBackend) -> str:
    backend.processing_pipeline = compat_pipeline()
    queries = backend.convert(collection)
    conditions = [q for q in queries if isinstance(q, str)]
    if not conditions or len(conditions) != len(queries):
        raise RuleRejectedError("Rule produced no condition")
    return " OR ".join(f"({c})" for c in conditions)
