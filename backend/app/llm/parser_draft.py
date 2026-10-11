"""LLM-drafted parser templates (SPEC 4.5 step 5, ADR-0005). Optional: everything else in
the draft flow works without it.

The model sees the deterministic envelope result, a format guess, up to 20 payloads with
the syslog header removed, and up to 5 full lines, all under "data" with declared sources,
plus the column list. It returns only payload, transforms, mapping, and tests (schema
checked by the gate). The envelope, id, name, and version come from this module, so a model
cannot change identity, header handling, or the classification default. The merged YAML is
written to the draft; it is inert until an admin previews and approves it.

Classification: a pasted sample is local_only (ADR-0005), so it is declared under a reserved
source id that can never be configured and that the gate always treats as local_only. A
file sample is declared under every source that would read each sampled file, and under the
reserved id for any file no source reads. The gate blocks a cloud provider unless every
declared source is cloud_allowed.
"""

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core import safeyaml
from app.core.errors import RateLimitedError, SourceRejectedError, TemplateInvalidError
from app.core.ids import LOCAL_ONLY_SAMPLE_SOURCE
from app.core.schema import COLUMNS
from app.engine.duckdb import QueryScope
from app.ingest.envelope import EnvelopeParser, SyslogEnvelopeConfig
from app.ingest.sources import resolve_source_path
from app.llm.gate import GateRequest, LLMGate, data_message
from app.llm.provider import ChatMessage
from app.templates.drafts import Draft, DraftStore, SampleSnapshot
from app.templates.matcher import match_block, payload_text, sniff

PROMPT = "parser_draft.v1"
MAX_PAYLOADS = 20
MAX_LINES = 5
MAX_SAMPLE_CHARS = 2_000
_SERVER_COLUMNS = frozenset(
    {
        "event_id", "source_id", "template_id", "template_version", "time_observed", "raw",
        "raw_bytes_invalid", "parse_status", "parse_errors", "classification", "owner_id",
        "envelope", "unmapped", "class_uid", "category_uid",
    }
)  # fmt: skip


class DraftReply(BaseModel):
    """What the model may return. Anything else is refused by the gate."""

    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]
    transforms: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    mapping: dict[str, Any]
    tests: list[dict[str, Any]] = Field(min_length=1, max_length=50)


def envelope_block(lines: list[str]) -> dict[str, Any]:
    """Deterministic header handling (4.5 step 2): syslog when every line has a header,
    none when no line does, an optional header when they are mixed."""
    parser = EnvelopeParser(SyslogEnvelopeConfig())
    with_header = sum(1 for line in lines if parser.parse(line).rfc != "none")
    if with_header == 0:
        return {"type": "none"}
    syslog = {"rfc": "auto", "assume_year": "rollover_safe", "timezone": "UTC"}
    block: dict[str, Any] = {"type": "syslog", "syslog": syslog}
    if with_header < len(lines):
        block["optional"] = True
    return block


def _has_criteria(match: object) -> bool:
    return isinstance(match, dict) and bool(match.get("app_name") or match.get("regex"))


def _columns_message() -> ChatMessage:
    columns = [
        f"{c.name} ({c.type}): {c.description}" for c in COLUMNS if c.name not in _SERVER_COLUMNS
    ]
    return ChatMessage("user", "Columns you may map:\n" + "\n".join(columns))


class ParserDrafter:
    def __init__(
        self,
        gate: LLMGate,
        drafts: DraftStore,
        owners: Callable[[list[Path]], dict[Path, list[str]] | None],
    ) -> None:
        self._gate = gate
        self._drafts = drafts
        self._owners = owners
        self._running = threading.Lock()  # one model draft at a time per server

    def _declared(self, sample: SampleSnapshot) -> list[str]:
        """Every source that reads any file the lines came from, plus the reserved
        local-only id for pasted lines or any file no source reads. The gate blocks a cloud
        provider unless every one of them is cloud_allowed."""
        if sample.kind != "file" or not sample.files:
            return [LOCAL_ONLY_SAMPLE_SOURCE]
        by_file = self._owners(sample.files)
        if by_file is None:  # could not finish the check: treat the sample as local_only
            return [LOCAL_ONLY_SAMPLE_SOURCE]
        declared: set[str] = set()
        for path in sample.files:
            declared.update(by_file.get(path) or [LOCAL_ONLY_SAMPLE_SOURCE])
        return sorted(declared)

    def draft(self, template_id: str, actor_id: str, provider_id: str) -> Draft:
        if not self._running.acquire(blocking=False):
            raise RateLimitedError("A template draft is already being written", retry_after_s=10)
        try:
            return self._draft(template_id, actor_id, provider_id)
        finally:
            self._running.release()

    def _draft(self, template_id: str, actor_id: str, provider_id: str) -> Draft:
        current = self._drafts.get(template_id)
        sample = self._drafts.sample_snapshot(template_id)
        lines = [ln for ln in sample.lines if ln.strip()]
        if not lines:
            raise TemplateInvalidError(
                "Add sample lines to the draft before asking for a model draft"
            )
        envelope = envelope_block(lines)
        guess = sniff(lines)
        env_parser = EnvelopeParser(SyslogEnvelopeConfig())
        payloads = []
        for line in lines[:MAX_PAYLOADS]:
            env = env_parser.parse(line)
            payloads.append(
                payload_text(None if env.rfc == "none" else env, line)[:MAX_SAMPLE_CHARS]
            )
        data = {
            "envelope": envelope,
            "format_sniff": {"format": guess.format, "formats": guess.formats},
            "payloads": payloads,
            "lines": [line[:MAX_SAMPLE_CHARS] for line in lines[:MAX_LINES]],
        }
        result = self._gate.call(
            GateRequest(
                actor_id=actor_id,
                provider_id=provider_id,
                purpose="parser_draft",
                scope=QueryScope(sources=[]),
                prompt=PROMPT,
                messages=[
                    _columns_message(),
                    data_message(data, self._declared(sample)),
                ],
                response_model=DraftReply,
                max_tokens=4096,
            )
        )
        reply = result.parsed
        if not isinstance(reply, DraftReply):  # pragma: no cover  # the gate validated it
            raise TemplateInvalidError("The model did not return a template draft")
        try:
            old = safeyaml.load(current.yaml) if current.yaml.strip() else None
        except yaml.YAMLError:
            old = None
        version = old.get("version") if isinstance(old, dict) else None
        old_match = old.get("match") if isinstance(old, dict) else None
        doc = {
            "schema_version": 1,
            "id": template_id,
            "name": (old.get("name") if isinstance(old, dict) else None) or template_id,
            "version": version if isinstance(version, str) else "0.1.0",
            "author": "",
            "description": (
                f"Drafted by a model (call {result.call_id}); review the patterns, mappings,"
                " and tests before approving."
            ),
            "category": "",
            "classification_default": "local_only",
            "envelope": envelope,
            # Kept when the admin already set one, else derived from the sample.
            "match": old_match if _has_criteria(old_match) else match_block(lines),
            "payload": reply.payload,
            "transforms": reply.transforms,
            "mapping": reply.mapping,
            "tests": reply.tests,
        }
        text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)
        return self._drafts.record_llm_draft(template_id, text, result.call_id)


OWNER_SCAN_ENTRIES = 50_000  # files listed across all sources per draft call
OWNER_SCAN_SECONDS = 5.0


def file_owners(
    store_list: Callable[[], list[Any]], allowed_roots: list[Path]
) -> Callable[[list[Path]], dict[Path, list[str]] | None]:
    """Which sources would read each sampled file, using each source's own path, glob, and
    symlink resolution under the roots, as ingest does. Bounded: past the entry or time
    budget the answer is None, and the caller declares the reserved local_only id."""

    def owners(paths: list[Path]) -> dict[Path, list[str]] | None:
        wanted = {Path(os.path.realpath(p)): p for p in paths}
        found: dict[Path, list[str]] = {p: [] for p in paths}
        deadline = time.monotonic() + OWNER_SCAN_SECONDS
        seen = 0
        for source in store_list():
            if getattr(source, "kind", "file") != "file":
                continue  # a Loki source reads no files
            try:
                base = resolve_source_path(source.path, allowed_roots)
            except (SourceRejectedError, OSError):
                continue  # nothing there to read
            candidates = [base] if base.is_file() else base.glob(source.glob)
            for candidate in candidates:
                seen += 1
                if seen > OWNER_SCAN_ENTRIES or time.monotonic() > deadline:
                    return None
                try:
                    real = resolve_source_path(candidate, allowed_roots)
                except (SourceRejectedError, OSError):
                    continue
                if real in wanted:
                    found[wanted[real]].append(source.source_id)
        return found

    return owners
