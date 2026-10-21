"""Template drafts: create, edit, preview, and approve user templates (SPEC 4.5, ADR-0005).

A draft is inert. Its YAML lives in data/templates/drafts/<id>.yaml, which the loader never
reads, and its metadata and sample live in the `template_drafts` table. Approval runs the
same checks a starter template must pass (schema, inline tests, a pathological line), then
writes data/templates/<id>.yaml atomically, records who approved exactly which bytes in the
append-only `template_approvals` table, and reloads the registry. Everything here works
with no LLM provider configured.
"""

import hashlib
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml

from app.core import safeyaml
from app.core.errors import (
    ConflictError,
    NotFoundError,
    SourceRejectedError,
    TemplateInvalidError,
)
from app.core.ids import new_id
from app.core.schema import COLUMN_NAMES
from app.ingest.discovery import is_evtx, sample_evtx_files, sample_text_files
from app.ingest.records import DecodedLine
from app.ingest.sources import SourceConfig, path_key, resolve_source_path
from app.meta.db import MetaDB
from app.templates.loader import MAX_TEMPLATE_BYTES, parse_template
from app.templates.matcher import match_block
from app.templates.registry import TemplateRegistry
from app.templates.runtime import TemplateNormalizer
from app.templates.tester import FIXED_NOW, run_tests
from app.templates.validator import TEMPLATE_ID, Template

T = TypeVar("T")

MAX_PASTED_LINES = 200
MAX_PASTED_BYTES = 256 * 1024
PREVIEW_ROWS = 50
RAW_PREVIEW_CHARS = 500
SAMPLE_FILES = 3
MAX_GLOB_ENTRIES = 2_000  # directory entries looked at when picking sample files
# The pathological check every approved template must survive (CLAUDE.md security rule 5).
PATHOLOGICAL = [
    "x" * 10_240,
    "<13>Oct  9 20:41:12 host app[1]: " + "a=" * 4_000,
    "{" * 5_000,
    "\x00\x01\x1b[31m" + "|" * 3_000,
    "",
]
_HIDDEN_COLUMNS = frozenset(
    {
        "event_id", "source_id", "template_id", "template_version", "time_observed", "raw",
        "raw_bytes_invalid", "parse_status", "parse_errors", "classification", "owner_id",
        "envelope",
    }
)  # fmt: skip
_SEMVER_CORE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
SampleKind = Literal["file", "pasted", "none"]
_UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class DraftSample:
    kind: SampleKind
    path: str | None = None
    glob: str | None = None
    lines: int = 0  # pasted lines kept with the draft


@dataclass(frozen=True, slots=True)
class SampleSnapshot:
    kind: SampleKind
    lines: list[str]
    files: list[Path]  # resolved paths the lines came from (file samples only)


@dataclass(frozen=True, slots=True)
class DraftInfo:
    template_id: str
    created_by: str
    created_at: str
    updated_at: str
    sample: DraftSample
    llm_call_id: str | None
    replaces_version: str | None  # the approved user template this draft would replace


@dataclass(frozen=True, slots=True)
class Draft(DraftInfo):
    yaml: str


@dataclass(frozen=True, slots=True)
class PreviewTest:
    name: str
    passed: bool
    problems: list[str]


@dataclass(frozen=True, slots=True)
class PreviewRow:
    line: int
    raw: str
    parse_status: str
    parse_errors: str | None
    class_uid: int | None
    fields: dict[str, str | int | float | bool | None]


@dataclass(frozen=True, slots=True)
class Preview:
    valid: bool
    errors: list[str]  # why the YAML is not a valid template, or why it cannot be approved
    tests: list[PreviewTest] = field(default_factory=list)
    lines: int = 0
    ok: int = 0
    partial: int = 0
    failed: int = 0
    rows: list[PreviewRow] = field(default_factory=list)
    approvable: bool = False
    # sha256 of exactly the YAML these results describe; approval must name it, so what
    # gets approved is what the admin looked at.
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class Approval:
    approval_id: str
    template_id: str
    version: str
    sha256: str
    approved_by: str
    approved_at: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _version_core(version: str) -> tuple[int, int, int]:
    m = _SEMVER_CORE.match(version)
    if m is None:  # pragma: no cover  # the schema only admits semver
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _check_id(template_id: str) -> str:
    if not TEMPLATE_ID.fullmatch(template_id):
        raise TemplateInvalidError("Template id must be snake_case: [a-z][a-z0-9_]{1,63}")
    return template_id


def _json_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def pasted_lines(text: str) -> list[str]:
    """Validate pasted sample text and split it into lines (blank lines dropped)."""
    if len(text.encode("utf-8", errors="replace")) > MAX_PASTED_BYTES:
        raise TemplateInvalidError(f"A pasted sample is limited to {MAX_PASTED_BYTES // 1024} KB")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > MAX_PASTED_LINES:
        raise TemplateInvalidError(f"A pasted sample is limited to {MAX_PASTED_LINES} lines")
    return lines


def skeleton(template_id: str, lines: list[str]) -> str:
    """A minimal template that loads and passes its own tests: every line becomes a
    message. The starting point when no existing template is close. Sample lines that
    would not parse `ok` under it (a bare syslog header, say) are not used as tests."""
    fallback = ["example line one", "example line two", "example line three"]
    text = _skeleton_doc(template_id, fallback, match_block(lines[:200]))
    norm = TemplateNormalizer(parse_template(text), "draft_skeleton", clock=lambda: FIXED_NOW)
    usable = [
        line[:4_000]
        for line in lines[:50]
        if norm.normalize(DecodedLine(text=line[:4_000], bytes_invalid=False, truncated=False))[
            "parse_status"
        ]
        == "ok"
    ]
    return _skeleton_doc(template_id, [*usable, *fallback][:3], match_block(lines[:200]))


def _skeleton_doc(template_id: str, inputs: list[str], match: dict[str, object]) -> str:
    doc = {
        "schema_version": 1,
        "id": template_id,
        "name": template_id.replace("_", " ").capitalize(),
        "version": "0.1.0",
        "author": "",
        "description": "Draft. Replace the payload pattern and mappings for this log.",
        "category": "",
        "classification_default": "local_only",
        "envelope": {"type": "syslog", "optional": True},
        "match": match,
        "payload": {"format": "regex", "regex": {"patterns": [r"^(?P<text>.+)$"]}},
        "transforms": [],
        "mapping": {"class_uid": 0, "fields": {"message": {"from": "text"}}},
        "tests": [
            {
                "name": f"sample line {i + 1}",
                "input": line,
                "expect": {"parse_status": "ok"},
            }
            for i, line in enumerate(inputs)
        ],
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


class DraftStore:
    def __init__(
        self,
        meta: MetaDB,
        registry: TemplateRegistry,
        allowed_roots: list[Path],
        sources_using: Callable[[str], list[str]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._registry = registry
        self._roots = allowed_roots
        self._sources_using = sources_using
        self._clock = clock
        self._lock = threading.Lock()  # one writer at a time for drafts and approvals

    # --- paths ------------------------------------------------------------------------

    @property
    def _user_dir(self) -> Path:
        return self._registry.user_dir

    def _draft_path(self, template_id: str) -> Path:
        return self._user_dir / "drafts" / f"{_check_id(template_id)}.yaml"

    def _user_path(self, template_id: str) -> Path:
        return self._user_dir / f"{_check_id(template_id)}.yaml"

    def _is_starter(self, template_id: str) -> bool:
        return (self._registry.starter_dir / f"{template_id}.yaml").is_file()

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(text, "utf-8")
        os.replace(tmp, path)

    # --- drafts -----------------------------------------------------------------------

    def list_drafts(self) -> list[DraftInfo]:
        with self._meta.connect() as con:
            rows = con.execute("SELECT * FROM template_drafts ORDER BY updated_at DESC").fetchall()
        return [self._info(r) for r in rows]

    def get(self, template_id: str) -> Draft:
        _check_id(template_id)
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT * FROM template_drafts WHERE template_id = ?", (template_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"No draft named {template_id}")
        try:
            text = self._draft_path(template_id).read_text("utf-8")
        except OSError:
            text = ""
        info = self._info(row)
        return Draft(**{f: getattr(info, f) for f in DraftInfo.__dataclass_fields__}, yaml=text)

    def _info(self, row: Any) -> DraftInfo:
        current = self._registry.get(row["template_id"])
        pasted = (
            len((row["sample_text"] or "").splitlines()) if row["sample_kind"] == "pasted" else 0
        )
        return DraftInfo(
            template_id=row["template_id"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sample=DraftSample(row["sample_kind"], row["sample_path"], row["sample_glob"], pasted),
            llm_call_id=row["llm_call_id"],
            replaces_version=current.version if current is not None else None,
        )

    def _sample_row(
        self, kind: SampleKind, path: str | None, glob: str | None, text: str | None
    ) -> tuple[str, str | None, str | None, str | None]:
        if kind == "file":
            if not path:
                raise TemplateInvalidError("A file sample needs a path")
            real = resolve_source_path(path, self._roots)  # raises SourceRejectedError
            glob = glob or "*"
            if "**" in glob:
                raise TemplateInvalidError(
                    "A sample pattern cannot use **; point at the folder that holds the files"
                )
            SourceConfig(source_id="sample_check", format="syslog", path=str(real), glob=glob)
            return "file", str(real), glob, None
        if kind == "pasted":
            lines = pasted_lines(text or "")
            if not lines:
                raise TemplateInvalidError("The pasted sample is empty")
            return "pasted", None, None, "\n".join(lines)
        return "none", None, None, None

    def create(
        self,
        template_id: str,
        created_by: str,
        sample: tuple[SampleKind, str | None, str | None, str | None],
        from_template: str | None = None,
    ) -> Draft:
        _check_id(template_id)
        if self._is_starter(template_id):
            raise ConflictError(
                f"{template_id} is a starter template. Give a customized copy a new id, "
                f"for example {template_id}_custom"
            )
        kind, path, glob, text = self._sample_row(*sample)
        if from_template is not None:
            yaml_text = self._from_template(from_template, template_id)
        else:
            yaml_text = skeleton(template_id, self._lines(kind, path, glob, text, "lines"))
        with self._lock:
            # The row is the source of truth; a stray file without one is overwritten.
            if self._exists(template_id):
                raise ConflictError(f"A draft named {template_id} already exists")
            self._write(self._draft_path(template_id), yaml_text)
            now = self._clock().isoformat()
            with self._meta.connect() as con:
                con.execute(
                    "INSERT INTO template_drafts (template_id, created_by, created_at, updated_at,"
                    " sample_kind, sample_path, sample_glob, sample_text) VALUES (?,?,?,?,?,?,?,?)",
                    (template_id, created_by, now, now, kind, path, glob, text),
                )
        return self.get(template_id)

    def _exists(self, template_id: str) -> bool:
        with self._meta.connect() as con:
            return (
                con.execute(
                    "SELECT 1 FROM template_drafts WHERE template_id = ?", (template_id,)
                ).fetchone()
                is not None
            )

    def update(
        self,
        template_id: str,
        yaml_text: str | None = None,
        sample: tuple[SampleKind, str | None, str | None, str | None] | None = None,
    ) -> Draft:
        _check_id(template_id)
        if yaml_text is not None and len(yaml_text.encode("utf-8")) > MAX_TEMPLATE_BYTES:
            raise TemplateInvalidError(f"A template is limited to {MAX_TEMPLATE_BYTES // 1024} KB")
        row = self._sample_row(*sample) if sample is not None else None
        with self._lock:
            if not self._exists(template_id):
                raise NotFoundError(f"No draft named {template_id}")
            if yaml_text is not None:
                self._write(self._draft_path(template_id), yaml_text)
            with self._meta.connect() as con:
                con.execute(
                    "UPDATE template_drafts SET updated_at = ? WHERE template_id = ?",
                    (self._clock().isoformat(), template_id),
                )
                if row is not None:
                    con.execute(
                        "UPDATE template_drafts SET sample_kind = ?, sample_path = ?,"
                        " sample_glob = ?, sample_text = ? WHERE template_id = ?",
                        (*row, template_id),
                    )
        return self.get(template_id)

    def record_llm_draft(self, template_id: str, yaml_text: str, call_id: str) -> Draft:
        """Replace a draft's YAML with a model's draft and keep the call id, which the
        approval record carries (SPEC 4.5 step 7)."""
        _check_id(template_id)
        with self._lock:
            if not self._exists(template_id):
                raise NotFoundError(f"No draft named {template_id}")
            self._write(self._draft_path(template_id), yaml_text)
            with self._meta.connect() as con:
                con.execute(
                    "UPDATE template_drafts SET llm_call_id = ?, llm_yaml_sha256 = ?,"
                    " updated_at = ? WHERE template_id = ?",
                    (call_id, _sha256(yaml_text), self._clock().isoformat(), template_id),
                )
        return self.get(template_id)

    def delete(self, template_id: str) -> None:
        _check_id(template_id)
        with self._lock:
            if not self._exists(template_id):
                raise NotFoundError(f"No draft named {template_id}")
            with self._meta.connect() as con:
                con.execute("DELETE FROM template_drafts WHERE template_id = ?", (template_id,))
            self._draft_path(template_id).unlink(missing_ok=True)

    def template_source(self, template_id: str) -> str:
        """The YAML of an available template, as a starting point for a draft."""
        _check_id(template_id)
        if self._registry.get(template_id) is None:
            raise NotFoundError(f"No template named {template_id}")
        for folder in (self._registry.starter_dir, self._user_dir):
            path = folder / f"{template_id}.yaml"
            if path.is_file():
                return path.read_text("utf-8")
        raise NotFoundError(f"No template named {template_id}")  # pragma: no cover

    def _from_template(self, source_id: str, template_id: str) -> str:
        text = self.template_source(source_id)
        text, n = re.subn(
            r"""(?m)^id:[ \t]*["']?[a-z][a-z0-9_]*["']?[ \t]*(?:#.*)?$""",
            f"id: {template_id}",
            text,
            count=1,
        )
        if n != 1:
            raise TemplateInvalidError(f"Could not copy {source_id}: no plain top-level id line")
        return text

    # --- samples and preview ------------------------------------------------------------

    def _lines(
        self,
        kind: str,
        path: str | None,
        glob: str | None,
        text: str | None,
        framing: str,
    ) -> list[str]:
        return self._read_sample(kind, path, glob, text, framing).lines

    def _read_sample(
        self,
        kind: str,
        path: str | None,
        glob: str | None,
        text: str | None,
        framing: str,
    ) -> "SampleSnapshot":
        if kind == "pasted":
            return SampleSnapshot("pasted", (text or "").splitlines(), [])
        if kind != "file" or not path:
            return SampleSnapshot("none", [], [])
        files = self._sample_files(path, glob or "*")
        if framing == "evtx" or (files and all(is_evtx(f, self._roots) for f in files)):
            return SampleSnapshot("file", sample_evtx_files(files, self._roots), files)
        lines, _ = sample_text_files(files, self._roots)
        return SampleSnapshot("file", lines, files)

    def sample_snapshot(self, template_id: str, framing: str = "lines") -> "SampleSnapshot":
        """The sample lines and the exact files they were read from, from one read of the
        draft row, so what is sent and what is declared to the gate cannot diverge."""
        _check_id(template_id)
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT sample_kind, sample_path, sample_glob, sample_text FROM template_drafts"
                " WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"No draft named {template_id}")
        return self._read_sample(row[0], row[1], row[2], row[3], framing)

    def _sample_files(self, path: str, glob: str) -> list[Path]:
        """Up to SAMPLE_FILES regular files under the roots, looking at a bounded number of
        directory entries: a broad glob over a large tree must not stall the request."""
        if "**" in glob:
            return []  # refused when the sample is saved; a recursive walk is unbounded
        try:
            SourceConfig(source_id="sample_check", format="syslog", path=path, glob=glob)
            base = resolve_source_path(path, self._roots)
        except (SourceRejectedError, ValueError):
            return []
        if base.is_file():
            return [base]
        files: list[Path] = []
        for n, candidate in enumerate(base.glob(glob)):
            if n >= MAX_GLOB_ENTRIES or len(files) >= SAMPLE_FILES:
                break
            if path_key(candidate) != str(candidate):
                continue  # not valid UTF-8: cannot be shown or declared, so never sampled
            try:
                real = resolve_source_path(candidate, self._roots)
            except SourceRejectedError:
                continue
            if real.is_file():
                files.append(real)
        return files

    def sample_lines(self, template_id: str, framing: str = "lines") -> list[str]:
        self.get(template_id)
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT sample_kind, sample_path, sample_glob, sample_text FROM template_drafts"
                " WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        return self._lines(row[0], row[1], row[2], row[3], framing)

    def preview(self, template_id: str, yaml_text: str | None = None) -> Preview:
        draft = self.get(template_id)
        text = draft.yaml if yaml_text is None else yaml_text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result = self._preview(template_id, text)
        return replace(result, sha256=digest)

    def _preview(self, template_id: str, text: str) -> Preview:
        if len(text.encode("utf-8")) > MAX_TEMPLATE_BYTES:
            return Preview(False, [f"larger than {MAX_TEMPLATE_BYTES // 1024} KB"])
        try:
            template = parse_template(text)
        except ValueError as exc:
            return Preview(False, [str(exc)])
        problems = self._approval_problems(template, template_id)
        try:
            outcomes = run_tests(template, self._registry.tables)
        except ValueError as exc:  # a missing lookup table, reported above too
            return Preview(True, problems or [str(exc)])
        tests = [PreviewTest(o.name, o.passed, o.problems) for o in outcomes]
        if not all(t.passed for t in tests):
            problems.append("Every inline test must pass")
        norm = TemplateNormalizer(
            template, "draft_preview", clock=lambda: FIXED_NOW, tables=self._registry.tables
        )
        if self._crashes(norm):
            problems.append("The template fails on malformed input (pathological check)")
        counts = {"ok": 0, "partial": 0, "failed": 0}
        rows: list[PreviewRow] = []
        for i, line in enumerate(self.sample_lines(template_id, template.framing.mode)):
            row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
            status = row["parse_status"]
            counts["failed" if status in ("failed", "envelope_only") else status] += 1
            if len(rows) < PREVIEW_ROWS:
                rows.append(
                    PreviewRow(
                        line=i + 1,
                        raw=line[:RAW_PREVIEW_CHARS],
                        parse_status=status,
                        parse_errors=row["parse_errors"],
                        class_uid=row["class_uid"],
                        fields={
                            c: _json_value(row[c])
                            for c in COLUMN_NAMES
                            if c not in _HIDDEN_COLUMNS
                            and c != "class_uid"
                            and row.get(c) is not None
                        },
                    )
                )
        return Preview(
            valid=True,
            errors=problems,
            tests=tests,
            lines=sum(counts.values()),
            ok=counts["ok"],
            partial=counts["partial"],
            failed=counts["failed"],
            rows=rows,
            approvable=not problems,
        )

    @staticmethod
    def _crashes(norm: TemplateNormalizer) -> bool:
        for line in PATHOLOGICAL:
            row = norm.normalize(DecodedLine(text=line, bytes_invalid=False, truncated=False))
            if "internal:" in (row["parse_errors"] or "") or row["raw"] != line:
                return True
        return False

    def _approval_problems(self, template: Template, template_id: str) -> list[str]:
        problems: list[str] = []
        if template.id != template_id:
            problems.append(f"The YAML id is {template.id}; this draft is {template_id}")
        if self._is_starter(template.id):
            problems.append(f"{template.id} is a starter template id; use a new id")
        lookup = template.mapping.lookup
        if lookup is not None and lookup.table not in self._registry.tables:
            problems.append(f"Lookup table {lookup.table} is not available")
        current = self._current_version(template.id)
        if current == _UNREADABLE:
            problems.append(
                f"The approved file for {template.id} cannot be read; remove it before replacing it"
            )
        elif current is not None and _version_core(template.version) <= _version_core(current):
            problems.append(
                f"{template.id} {current} is already approved; raise the version to replace it"
            )
        return problems

    def _current_version(self, template_id: str) -> str | None:
        """The approved version: from the registry, or from the file on disk when the
        loader currently refuses it (a downgrade must not slip in that way)."""
        loaded = self._registry.get(template_id)
        if loaded is not None:
            return loaded.version
        path = self._user_path(template_id)
        if not path.is_file():
            return None
        try:
            doc = safeyaml.load(path.read_text("utf-8")[:MAX_TEMPLATE_BYTES])
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return _UNREADABLE
        version = doc.get("version") if isinstance(doc, dict) else None
        if isinstance(version, str) and _SEMVER_CORE.match(version):
            return version
        return _UNREADABLE

    # --- approval and removal -----------------------------------------------------------

    def approve(self, template_id: str, approved_by: str, reviewed_sha256: str) -> Approval:
        with self._lock:
            draft = self.get(template_id)
            if hashlib.sha256(draft.yaml.encode("utf-8")).hexdigest() != reviewed_sha256:
                # Saved by someone else (or an AI draft) after this admin's preview.
                raise ConflictError(
                    f"{template_id} changed after you previewed it. Preview it again, then approve"
                )
            preview = self.preview(template_id, draft.yaml)  # check the bytes we will write
            if not preview.valid or not preview.approvable:
                reasons = "; ".join(preview.errors) or "the template is not valid"
                raise TemplateInvalidError(f"Cannot approve {template_id}: {reasons}")
            target = self._user_path(template_id)
            previous = target.read_text("utf-8") if target.is_file() else None
            self._write(target, draft.yaml)
            self._registry.reload()
            loaded = self._registry.get(template_id)
            template = parse_template(draft.yaml)
            if loaded is None or loaded.version != template.version:
                # The loader disagreed with the checks above: put the old file back.
                self._restore(target, previous)
                problem = next(
                    (p.message for p in self._registry.problems if p.file == target.name),
                    "the loader refused it",
                )
                raise TemplateInvalidError(f"Cannot approve {template_id}: {problem}")
            approval = Approval(
                approval_id=new_id(),
                template_id=template_id,
                version=template.version,
                sha256=hashlib.sha256(draft.yaml.encode("utf-8")).hexdigest(),
                approved_by=approved_by,
                approved_at=self._clock().isoformat(),
            )
            # Provenance: which model call wrote the draft, and whether the approved bytes
            # are still exactly what it wrote or were edited by hand afterwards.
            unchanged = None
            if draft.llm_call_id is not None:
                with self._meta.connect() as con:
                    (written,) = con.execute(
                        "SELECT llm_yaml_sha256 FROM template_drafts WHERE template_id = ?",
                        (template_id,),
                    ).fetchone()
                unchanged = int(written == approval.sha256)
            try:
                with self._meta.connect() as con:
                    con.execute(
                        "INSERT INTO template_approvals (approval_id, template_id, version,"
                        " sha256, approved_by, approved_at, llm_call_id, llm_output_unchanged)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (
                            approval.approval_id,
                            approval.template_id,
                            approval.version,
                            approval.sha256,
                            approval.approved_by,
                            approval.approved_at,
                            draft.llm_call_id,
                            unchanged,
                        ),
                    )
                    con.execute("DELETE FROM template_drafts WHERE template_id = ?", (template_id,))
            except Exception:
                # No approval record, no live template: put the previous file back.
                self._restore(target, previous)
                raise
            self._draft_path(template_id).unlink(missing_ok=True)
            return approval

    def _restore(self, target: Path, previous: str | None) -> None:
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            self._write(target, previous)
        self._registry.reload()

    def with_template(self, template_id: str, action: Callable[[], T]) -> T:
        """Run `action` (adding a source that uses `template_id`) only while that template
        exists, holding the lock delete_template takes, so the two cannot interleave."""
        with self._lock:
            if self._registry.get(template_id) is None:
                raise SourceRejectedError(f"No template named {template_id}")
            return action()

    def delete_template(self, template_id: str) -> None:
        """Remove an approved user template. Starter templates and templates in use stay."""
        _check_id(template_id)
        if self._is_starter(template_id):
            raise ConflictError(f"{template_id} is a starter template and cannot be removed")
        path = self._user_path(template_id)
        # Under the lock that adding a source with a template also takes (with_template),
        # so no source can start using it between this check and the removal.
        with self._lock:
            if not path.is_file():
                raise NotFoundError(f"No user template named {template_id}")
            using = self._sources_using(template_id)
            if using:
                raise ConflictError(
                    f"{template_id} is used by {', '.join(sorted(using)[:5])};"
                    " change those sources first"
                )
            path.unlink()
            self._registry.reload()
