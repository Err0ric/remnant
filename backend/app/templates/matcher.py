"""Deterministic sniff and template matching for sample lines (SPEC 3.6 Match, 4.5 steps 2-4).

No LLM. The envelope is detected first (RFC 5424, RFC 3164, or none), then the payload
format of each line is guessed, then every template whose `match` block accepts enough of
the sample is run over it for real. Ranking prefers templates that pass their own
`min_confidence`, then parse rate, then how many OCSF columns they fill (a vendor template
beats a generic one that also parses the line).
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import regex

from app.ingest.envelope import Envelope, EnvelopeParser, SyslogEnvelopeConfig
from app.ingest.payload.regexpayload import MATCH_TIMEOUT_S
from app.ingest.records import DecodedLine
from app.templates.runtime import TemplateNormalizer
from app.templates.tables import LookupTable
from app.templates.validator import Template

FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)
# Columns every row has regardless of what the template understood.
_ALWAYS = frozenset(
    {
        "event_id", "source_id", "template_id", "template_version", "time_observed", "raw",
        "raw_bytes_invalid", "parse_status", "parse_errors", "classification", "owner_id",
        "envelope", "unmapped", "category_uid",
    }
)  # fmt: skip
_CEF = re.compile(r"(?:^|\s)CEF:\d+\|")
_LEEF = re.compile(r"(?:^|\s)LEEF:\d(?:\.\d)?\|")
_KV = re.compile(r"(?:^|\s)[A-Za-z_][\w.\-]{0,63}=")
_REBUILD = {"CEF": "CEF:", "LEEF": "LEEF:"}
TRY_BELOW = 0.2  # templates whose match block accepts less than this are not run


@dataclass(frozen=True, slots=True)
class Sniff:
    lines: int
    envelope: dict[str, int]  # "5424", "3164", "none" -> line count
    app_names: list[tuple[str, int]]  # most common syslog tags
    formats: dict[str, int]  # json, cef, leef, xml, kv, csv, plain -> line count
    format: str  # the most common format


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    template_id: str
    name: str
    confidence: float  # share of lines the template's match block accepts
    min_confidence: float
    parse_rate: float  # share of lines parsed ok or partial
    coverage: float  # OCSF columns filled per line, on average
    passes: bool  # confidence reaches the template's own min_confidence


def payload_text(env: Envelope | None, line: str) -> str:
    if env is None:
        return line
    if env.app_name in _REBUILD:  # "host CEF:0|..." reads as a tag named CEF
        return f"{_REBUILD[env.app_name]}{env.msg}"
    if env.app_name and (env.app_name.startswith("%") or env.app_name.isdigit()):
        return f"{env.app_name}: {env.msg}"  # Cisco message ids and sequence numbers
    return env.msg


def detect_format(payload: str) -> str:
    text = payload.strip()
    body = text.removeprefix("@cee:").strip()
    if body.startswith("{") and len(body) <= 65_536:
        try:
            if isinstance(json.loads(body), dict):
                return "json"
        except ValueError:
            pass
    if _CEF.search(text[:200]):
        return "cef"
    if _LEEF.search(text[:200]):
        return "leef"
    if text.startswith("<") and text.endswith(">"):
        return "xml"
    if len(_KV.findall(text[:4096])) >= 3:
        return "kv"
    if text.count(",") >= 4 or text.count("\t") >= 4:
        return "csv"
    return "plain"


def _envelopes(lines: list[str]) -> list[Envelope | None]:
    parser = EnvelopeParser(SyslogEnvelopeConfig())
    out: list[Envelope | None] = []
    for line in lines:
        env = parser.parse(line)
        out.append(None if env.rfc == "none" else env)
    return out


def sniff(lines: list[str]) -> Sniff:
    envs = _envelopes(lines)
    rfc = Counter("none" if e is None else str(e.rfc) for e in envs)
    apps = Counter(e.app_name for e in envs if e is not None and e.app_name)
    formats = Counter(
        detect_format(payload_text(e, line)) for e, line in zip(envs, lines, strict=True)
    )
    return Sniff(
        lines=len(lines),
        envelope=dict(rfc),
        app_names=[(name[:100], n) for name, n in apps.most_common(10)],
        formats=dict(formats),
        format=formats.most_common(1)[0][0] if formats else "plain",
    )


def _accepts(template: Template, envs: list[Envelope | None], lines: list[str]) -> float:
    m = template.match
    if not m.app_name and not m.regex:
        return 0.0  # a template that names no criteria is never suggested
    pattern = regex.compile(m.regex) if m.regex else None
    apps = set(m.app_name)
    hits = 0
    for env, line in zip(envs, lines, strict=True):
        if env is not None and env.app_name in apps:
            hits += 1
            continue
        if pattern is None:
            continue
        text = line if template.envelope.type == "none" else payload_text(env, line)
        try:
            if pattern.search(text, timeout=MATCH_TIMEOUT_S):
                hits += 1
        except TimeoutError:
            continue
    return hits / len(lines) if lines else 0.0


def match_templates(
    lines: list[str],
    templates: Iterable[Template],
    tables: Mapping[str, LookupTable] | None = None,
    framing: str = "lines",
    limit: int = 5,
) -> list[TemplateMatch]:
    """Templates ranked for this sample, best first. Only templates of the same framing."""
    lines = [line for line in lines if line.strip()]
    if not lines:
        return []
    envs = _envelopes(lines)
    found: list[TemplateMatch] = []
    for template in templates:
        if template.framing.mode != framing:
            continue
        confidence = _accepts(template, envs, lines)
        if confidence < TRY_BELOW:
            continue
        norm = TemplateNormalizer(template, "discovery", clock=lambda: FIXED_NOW, tables=tables)
        parsed = filled = 0
        for line in lines:
            row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
            if row["parse_status"] in ("ok", "partial"):
                parsed += 1
            filled += sum(
                1
                for k, v in row.items()
                if k not in _ALWAYS and v is not None and not (k == "class_uid" and v == 0)
            )
        found.append(
            TemplateMatch(
                template_id=template.id,
                name=template.name,
                confidence=round(confidence, 3),
                min_confidence=template.match.min_confidence,
                parse_rate=round(parsed / len(lines), 3),
                coverage=round(filled / len(lines), 2),
                passes=confidence >= template.match.min_confidence,
            )
        )
    found.sort(
        key=lambda m: (m.passes, m.parse_rate >= 0.8, m.coverage, m.parse_rate), reverse=True
    )
    return found[:limit]


def match_block(lines: list[str]) -> dict[str, object]:
    """A `match` block for a new draft, decided without a model: the sample's syslog tag
    when at least 80% of lines share it, so the Automatic parser (ADR-0012) routes those
    lines to the template once it is approved. No tag, no routing: the admin can add one."""
    block: dict[str, object] = {"min_confidence": 0.8}
    lines = [line for line in lines if line.strip()]
    if not lines:
        return block
    apps = sniff(lines).app_names
    if apps and apps[0][1] >= 0.8 * len(lines) and len(apps[0][0]) <= 100:
        block = {"app_name": [apps[0][0]], **block}
    return block
