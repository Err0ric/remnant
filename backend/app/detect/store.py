"""Imported Sigma rules: pinned snapshots, enable state, import history (ADR-0006 rows 1, 5).

An admin imports a file or folder under `paths.rule_roots`. Every `.yml`/`.yaml` file goes
through `rules.compile_rule`; accepted files are stored as immutable versions keyed by the
sha256 of their exact bytes, and each rule id points at the version last imported. Nothing
is fetched from the network and a rule only changes when an admin imports again.

New rules start disabled. Re-importing a rule keeps its enabled state; if the content
changed, the rule moves to the new version. Every import, enable, and disable is audited.

Limits, because a rule folder is input from the internet: 10,000 files, 200 MB, 16 folder
levels, 10 minutes; hidden folders (`.git`) are skipped; each file is opened with the same
checks as log files (regular file, still inside the roots when opened).
"""

import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import ConflictError, NotFoundError, RuleRejectedError, SourceRejectedError
from app.core.ids import new_id
from app.detect.rules import MAX_RULE_BYTES, CompiledRule, compile_rule
from app.ingest.sources import display_name, open_regular, resolve_source_path
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

MAX_FILES = 10_000
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_DEPTH = 16
MAX_SECONDS = 600
MAX_STORED_REFUSALS = 1_000
_SUFFIXES = (".yml", ".yaml")


@dataclass(frozen=True, slots=True)
class Refusal:
    path: str
    reason: str


@dataclass(slots=True)
class ImportReport:
    import_id: str
    path: str
    files: int = 0
    accepted: int = 0
    new_rules: int = 0
    updated: int = 0
    unchanged: int = 0
    refusals: list[Refusal] = field(default_factory=list)
    truncated: bool = False  # a limit stopped the walk early


@dataclass(frozen=True, slots=True)
class RuleRow:
    rule_id: str
    title: str
    author: str
    level: str
    status: str
    product: str | None
    service: str | None
    category: str | None
    tags: list[str]
    path: str
    enabled: bool
    sha256: str
    import_id: str
    updated_at: str


class RuleStore:
    def __init__(self, meta: MetaDB, audit: AuditLog, rule_roots: list[Path]) -> None:
        self._meta = meta
        self._audit = audit
        self._roots = rule_roots
        self._importing = threading.Lock()

    # --- import -------------------------------------------------------------------------

    def import_path(self, path: str, actor_id: str, ip: str | None) -> ImportReport:
        if not self._importing.acquire(blocking=False):
            raise ConflictError("Another rule import is running; try again when it finishes")
        try:
            return self._import(path, actor_id, ip)
        finally:
            self._importing.release()

    def _import(self, path: str, actor_id: str, ip: str | None) -> ImportReport:
        if not self._roots:
            raise RuleRejectedError(
                "No rule folders are allowed yet. Set paths.rule_roots "
                "(or APP__PATHS__RULE_ROOTS) to the folders rules may be imported from."
            )
        try:
            root = resolve_source_path(path, self._roots)
        except SourceRejectedError:
            self._audit.write("rule.import", "denied", actor_id, ip, {"path": path[:500]})
            raise
        report = ImportReport(import_id=new_id(), path=str(root))
        compiled: list[tuple[str, CompiledRule, str]] = []  # (shown path, rule, yaml text)
        seen_ids: dict[str, str] = {}
        total = 0
        deadline = time.monotonic() + MAX_SECONDS
        for listed in self._files(root, report, deadline):
            shown = _shown(listed, root)
            report.files += 1
            try:
                with open_regular(listed, self._roots) as fh:
                    data = fh.read(MAX_RULE_BYTES + 1)
            except OSError:
                report.refusals.append(Refusal(shown, "File could not be opened"))
                continue
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                report.truncated = True
                break
            try:
                rule = compile_rule(data)
            except RuleRejectedError as exc:
                report.refusals.append(Refusal(shown, str(exc)[:300]))
                continue
            if rule.rule_id in seen_ids:
                report.refusals.append(
                    Refusal(shown, f"Same rule id as {seen_ids[rule.rule_id]}; first one kept")
                )
                continue
            seen_ids[rule.rule_id] = shown
            compiled.append((shown, rule, data.decode("utf-8")))
        report.accepted = len(compiled)
        self._save(report, compiled, actor_id)
        self._audit.write(
            "rule.import",
            "success",
            actor_id,
            ip,
            {
                "import_id": report.import_id,
                "path": report.path,
                "files": report.files,
                "accepted": report.accepted,
                "refused": len(report.refusals),
                "new": report.new_rules,
                "updated": report.updated,
                "truncated": report.truncated,
            },
        )
        return report

    def _files(self, root: Path, report: ImportReport, deadline: float) -> Iterator[Path]:
        if root.is_file():
            yield root
            return
        count = 0
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            depth = len(Path(dirpath).relative_to(root).parts)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and depth < MAX_DEPTH)
            for name in sorted(filenames):
                if name.startswith(".") or not name.lower().endswith(_SUFFIXES):
                    continue
                count += 1
                if count > MAX_FILES or time.monotonic() > deadline:
                    report.truncated = True
                    return
                yield Path(dirpath) / name

    def _save(
        self, report: ImportReport, compiled: list[tuple[str, CompiledRule, str]], actor_id: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO rule_imports (import_id, path, imported_by, imported_at, files,"
                " accepted, refused, new_rules, updated) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                (
                    report.import_id,
                    report.path,
                    actor_id,
                    now,
                    report.files,
                    report.accepted,
                    len(report.refusals),
                ),
            )
            for shown, rule, text in compiled:
                con.execute(
                    "INSERT OR IGNORE INTO rule_versions (sha256, rule_id, title, author, level,"
                    " status, product, service, category, tags, yaml, import_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rule.sha256,
                        rule.rule_id,
                        rule.title,
                        rule.author,
                        rule.level,
                        rule.status,
                        rule.logsource.product,
                        rule.logsource.service,
                        rule.logsource.category,
                        json.dumps(list(rule.tags)),
                        text,
                        report.import_id,
                    ),
                )
                row = con.execute(
                    "SELECT sha256 FROM rules WHERE rule_id = ?", (rule.rule_id,)
                ).fetchone()
                if row is None:
                    con.execute(
                        "INSERT INTO rules (rule_id, sha256, path, enabled, import_id, updated_at)"
                        " VALUES (?, ?, ?, 0, ?, ?)",
                        (rule.rule_id, rule.sha256, shown, report.import_id, now),
                    )
                    report.new_rules += 1
                elif row["sha256"] != rule.sha256:
                    con.execute(
                        "UPDATE rules SET sha256 = ?, path = ?, import_id = ?, updated_at = ?"
                        " WHERE rule_id = ?",
                        (rule.sha256, shown, report.import_id, now, rule.rule_id),
                    )
                    report.updated += 1
                else:
                    report.unchanged += 1
            con.executemany(
                "INSERT INTO rule_refusals (import_id, path, reason) VALUES (?, ?, ?)",
                [
                    (report.import_id, r.path, r.reason)
                    for r in report.refusals[:MAX_STORED_REFUSALS]
                ],
            )
            con.execute(
                "UPDATE rule_imports SET new_rules = ?, updated = ? WHERE import_id = ?",
                (report.new_rules, report.updated, report.import_id),
            )

    # --- enable, list, read ---------------------------------------------------------------

    def set_enabled(self, rule_ids: list[str], enabled: bool, actor_id: str, ip: str | None) -> int:
        ids = sorted(set(rule_ids))
        with self._meta.connect() as con:
            changed = 0
            for rid in ids:
                cur = con.execute(
                    "UPDATE rules SET enabled = ? WHERE rule_id = ? AND enabled != ?",
                    (int(enabled), rid, int(enabled)),
                )
                changed += cur.rowcount
        self._audit.write(
            "rule.enable" if enabled else "rule.disable",
            "success",
            actor_id,
            ip,
            {"requested": len(ids), "changed": changed, "rule_ids": ids[:50]},
        )
        return changed

    def all(self) -> list[RuleRow]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT r.rule_id, v.title, v.author, v.level, v.status, v.product, v.service,"
                " v.category, v.tags, r.path, r.enabled, r.sha256, r.import_id, r.updated_at"
                " FROM rules r JOIN rule_versions v ON v.sha256 = r.sha256"
                " ORDER BY v.title COLLATE NOCASE, r.rule_id"
            ).fetchall()
        return [_row(r) for r in rows]

    def get(self, rule_id: str) -> tuple[RuleRow, str]:
        with self._meta.connect() as con:
            r = con.execute(
                "SELECT r.rule_id, v.title, v.author, v.level, v.status, v.product, v.service,"
                " v.category, v.tags, r.path, r.enabled, r.sha256, r.import_id, r.updated_at,"
                " v.yaml FROM rules r JOIN rule_versions v ON v.sha256 = r.sha256"
                " WHERE r.rule_id = ?",
                (rule_id,),
            ).fetchone()
        if r is None:
            raise NotFoundError("No such rule")
        return _row(r), str(r["yaml"])

    def imports(self, limit: int = 50) -> list[dict[str, object]]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT import_id, path, imported_by, imported_at, files, accepted, refused,"
                " new_rules, updated FROM rule_imports ORDER BY imported_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def refusals(self, import_id: str) -> list[Refusal]:
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT path, reason FROM rule_refusals WHERE import_id = ? ORDER BY path",
                (import_id,),
            ).fetchall()
        return [Refusal(r["path"], r["reason"]) for r in rows]


def _shown(listed: Path, root: Path) -> str:
    """The file's path as shown and stored: relative to the import root."""
    rel = listed.name if listed == root else str(listed.relative_to(root))
    return display_name(rel)[:500]


def _row(r: sqlite3.Row) -> RuleRow:
    tags = json.loads(r["tags"])
    return RuleRow(
        rule_id=r["rule_id"],
        title=r["title"],
        author=r["author"],
        level=r["level"],
        status=r["status"],
        product=r["product"],
        service=r["service"],
        category=r["category"],
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        path=r["path"],
        enabled=bool(r["enabled"]),
        sha256=r["sha256"],
        import_id=r["import_id"],
        updated_at=r["updated_at"],
    )
