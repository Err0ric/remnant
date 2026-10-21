"""Automatic parser: one approved template per line, or the generic parser (ADR-0012, D38).

Deterministic and model-free. The order is fixed so a line's parser can be reproduced:
1. templates whose `match.app_name` lists the line's syslog tag (if several, the first by
   id whose `match.regex` also matches the payload, else the first by id);
2. templates with a `match.regex`: user templates, then starter templates with a vendor,
   then catch-alls without one (CEF, LEEF, JSON over syslog), each group by id;
3. the generic parser for the source's format.
A routed template that understands nothing of the payload (failed, or header only) is
replaced by the generic parser for that line.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

import regex

from app.ingest.envelope import Envelope, EnvelopeParser
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.payload.regexpayload import MATCH_TIMEOUT_S
from app.ingest.records import DecodedLine
from app.templates.matcher import payload_text
from app.templates.runtime import TemplateNormalizer
from app.templates.tables import LookupTable
from app.templates.validator import Template


def routable(template: Template) -> bool:
    """Per-line routing cannot join lines, so multiline templates are never chosen."""
    m = template.match
    return template.framing.multiline.start is None and bool(m.app_name or m.regex)


class AutoNormalizer:
    """Same interface as Normalizer and TemplateNormalizer. One instance per pass."""

    def __init__(
        self,
        spec: SourceSpec,
        templates: Iterable[Template],
        starter_ids: frozenset[str] = frozenset(),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        tables: Mapping[str, LookupTable] | None = None,
    ) -> None:
        self._spec = spec
        self._clock = clock
        self._tables = tables
        self._generic = Normalizer(spec, clock=clock)
        self._envelope = EnvelopeParser(spec.envelope, clock=clock)
        usable = sorted((t for t in templates if routable(t)), key=lambda t: t.id)
        self._by_app: dict[str, list[Template]] = {}
        for t in usable:
            for name in t.match.app_name:
                self._by_app.setdefault(name, []).append(t)
        with_regex = [t for t in usable if t.match.regex]
        self._by_regex = sorted(
            with_regex,
            key=lambda t: (t.id in starter_ids, t.vendor == "", t.id),
        )
        self._patterns = {t.id: regex.compile(t.match.regex or "") for t in with_regex}
        self._normalizers: dict[str, TemplateNormalizer] = {}

    def route(self, text: str) -> Template | None:
        """The template this line goes to, or None for the generic parser."""
        env: Envelope | None = self._envelope.parse(text)
        if env is not None and env.rfc == "none":
            env = None
        if env is not None and env.app_name:
            candidates = self._by_app.get(env.app_name, [])
            for t in candidates:
                if t.match.regex and self._search(t, env, text):
                    return t
            if candidates:
                return candidates[0]
        for t in self._by_regex:
            # A template that reads a syslog header cannot parse a line without one (a JSON
            # lines file, a headerless line): those go to the generic parser for the format.
            if env is None and t.envelope.type == "syslog":
                continue
            if self._search(t, env, text):
                return t
        return None

    def _search(self, template: Template, env: Envelope | None, text: str) -> bool:
        subject = text if template.envelope.type == "none" else payload_text(env, text)
        try:
            return self._patterns[template.id].search(subject, timeout=MATCH_TIMEOUT_S) is not None
        except TimeoutError:
            return False  # a hostile line is not routed by this template

    def normalize(self, line: DecodedLine) -> dict[str, Any] | None:
        template = self.route(line.text)
        if template is None:
            return self._generic.normalize(line)
        row = self._template(template).normalize(line)
        # "failed" or header only: the template understood nothing of the payload.
        if row.get("parse_status") not in ("failed", "envelope_only"):
            return row
        fallback = self._generic.normalize(line)
        if fallback is not None:
            errors = [f"auto_fallback:{template.id}", fallback.get("parse_errors")]
            fallback["parse_errors"] = ",".join(e for e in errors if e)[:500]
        return fallback

    def _template(self, template: Template) -> TemplateNormalizer:
        norm = self._normalizers.get(template.id)
        if norm is None:
            envelope = template.envelope.syslog.model_copy(
                update={"timezone": self._spec.envelope.timezone}
            )
            norm = TemplateNormalizer(
                template,
                self._spec.source_id,
                self._spec.classification,
                owner_id=self._spec.owner_id,
                envelope=envelope,
                clock=self._clock,
                tables=self._tables,
            )
            self._normalizers[template.id] = norm
        return norm
