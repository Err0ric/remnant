"""Log integrity: a hash-chained ledger of lake files and the audit log chain (ADR-0022).

Every file the product adds to or removes from the lake is one ledger entry; each entry
holds the hash of the one before it. Verification recomputes the chain, re-hashes every
file the ledger says is present, and looks for files the ledger never saw. The audit log
carries its own chain (`audit_log.chain_hash`, written by `AuditLog.write`).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import structlog

from app.core.chain import GENESIS, audit_hash, entry_hash
from app.meta.db import MetaDB

log = structlog.get_logger(__name__)

RECENT_S = 120.0  # a file this new may be mid-publish: never judged unknown yet
CHUNK = 1 << 20

Op = Literal["add", "remove", "baseline", "adopt"]


class LakeEvents(Protocol):
    """What the writer, compaction, retention, and quarantine report (ADR-0022 row 2)."""

    def added(self, paths: Sequence[Path]) -> None: ...

    def removed(self, paths: Sequence[Path], reason: str) -> None: ...


class NoEvents:
    def added(self, paths: Sequence[Path]) -> None:
        return None

    def removed(self, paths: Sequence[Path], reason: str) -> None:
        return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class Finding:
    kind: str  # changed, missing, chain_broken, audit_changed, unknown, removal_pending
    path: str
    detail: str


@dataclass(slots=True)
class Verification:
    status: Literal["verified", "warnings", "failed"]
    checked_at: str
    files: int
    bytes: int
    entries: int
    head: str
    audit_rows: int
    audit_unchained: int
    audit_head: str
    failures: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    by_source: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0


class IntegrityLedger:
    def __init__(
        self,
        meta: MetaDB,
        lake: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._lake = lake
        self._clock = clock
        self._verify_lock = threading.Lock()

    # --- recording ------------------------------------------------------------------------

    def added(self, paths: Sequence[Path]) -> None:
        self._record("add", [(p, "") for p in paths])

    def removed(self, paths: Sequence[Path], reason: str) -> None:
        self._record("remove", [(p, reason[:200]) for p in paths], hash_files=False)

    def ensure_baseline(self) -> int:
        """First start with the ledger (or an install that predates it): every file in the
        lake becomes a `baseline` entry. Returns how many were recorded."""
        with self._meta.connect() as con:
            if con.execute("SELECT 1 FROM lake_ledger LIMIT 1").fetchone():
                return 0
        files = list(self._lake_files())
        self._record("baseline", [(p, "present when integrity checks started") for p in files])
        return len(files)

    def _record(self, op: Op, items: Iterable[tuple[Path, str]], hash_files: bool = True) -> None:
        rows = []
        for path, reason in items:
            rel = self._rel(path)
            if rel is None:
                continue
            sha, size = "", 0
            if hash_files:
                try:
                    sha, size = file_sha256(path), path.stat().st_size
                except OSError as exc:  # gone already: the verifier will report it
                    log.warning("integrity.hash_failed", file=rel, error=type(exc).__name__)
                    continue
            elif op == "remove":
                sha = self._last_sha(rel)
            rows.append((rel, sha, size, reason))
        if not rows:
            return
        at = self._clock().isoformat()
        with self._meta.connect() as con:
            prev_row = con.execute(
                "SELECT hash FROM lake_ledger ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev = prev_row[0] if prev_row else GENESIS
            for rel, sha, size, reason in rows:
                h = entry_hash(prev, op, rel, sha, size, reason, at)
                con.execute(
                    "INSERT INTO lake_ledger (at, op, path, sha256, size, reason, prev_hash, hash)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (at, op, rel, sha, size, reason, prev, h),
                )
                prev = h

    def _last_sha(self, rel: str) -> str:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT sha256 FROM lake_ledger WHERE path = ? AND op != 'remove'"
                " ORDER BY seq DESC LIMIT 1",
                (rel,),
            ).fetchone()
        return str(row[0]) if row else ""

    def _rel(self, path: Path) -> str | None:
        try:
            return path.relative_to(self._lake).as_posix()
        except ValueError:
            return None

    def _lake_files(self) -> Iterable[Path]:
        if not self._lake.is_dir():
            return []
        return (
            p
            for p in sorted(self._lake.glob("source=*/day=*/part-*.parquet"))
            if p.is_file()
            and not p.is_symlink()
            and not p.parent.is_symlink()
            and not p.parent.parent.is_symlink()
        )

    # --- verifying ------------------------------------------------------------------------

    def verify(self, adopt: bool = True) -> Verification:
        """Recompute the chain, re-hash present files, look for unknown ones. Unknown files
        old enough to not be mid-publish are adopted (recorded) and reported once."""
        with self._verify_lock:
            started = time.monotonic()
            failures: list[Finding] = []
            warnings: list[Finding] = []
            state: dict[str, tuple[str, int]] = {}
            removed: dict[str, str] = {}
            prev, entries = GENESIS, 0
            with self._meta.connect() as con:
                cursor = con.execute(
                    "SELECT seq, at, op, path, sha256, size, reason, prev_hash, hash"
                    " FROM lake_ledger ORDER BY seq"
                )
                for seq, at, op, path, sha, size, reason, prev_hash, h in cursor:
                    entries += 1
                    expected = entry_hash(prev, op, path, sha, size, reason, at)
                    if prev_hash != prev or h != expected:
                        failures.append(
                            Finding("chain_broken", path, f"ledger entry {seq} does not chain")
                        )
                    prev = h
                    if op == "remove":
                        state.pop(path, None)
                        removed[path] = reason
                    else:
                        state[path] = (sha, size)
                        removed.pop(path, None)
            head = prev
            present = {self._rel(p): p for p in self._lake_files()}
            now = time.time()
            total = 0
            by_source: dict[str, int] = {}
            for rel, (sha, size) in sorted(state.items()):
                path = present.pop(rel, None)
                if path is None:
                    failures.append(Finding("missing", rel, "recorded as present; not found"))
                    continue
                try:
                    actual = file_sha256(path)
                except OSError as exc:
                    failures.append(Finding("missing", rel, f"cannot read: {exc.strerror}"))
                    continue
                if actual != sha:
                    failures.append(
                        Finding("changed", rel, f"SHA-256 {actual[:16]}, recorded {sha[:16]}")
                    )
                    continue
                total += size
                source = rel.split("/", 1)[0].removeprefix("source=")
                by_source[source] = by_source.get(source, 0) + 1
            adopt_now: list[Path] = []
            for rel, path in sorted((k, v) for k, v in present.items() if k is not None):
                try:
                    if now - path.stat().st_mtime < RECENT_S:
                        continue  # may be mid-publish: the writer records it in a moment
                except OSError:
                    continue
                if rel in removed:
                    warnings.append(
                        Finding(
                            "removal_pending",
                            rel,
                            f"recorded as removed ({removed[rel]}) but still present",
                        )
                    )
                    continue
                warnings.append(
                    Finding(
                        "unknown",
                        rel,
                        "present but never recorded; adopted"
                        if adopt
                        else "present but never recorded",
                    )
                )
                adopt_now.append(path)
            if adopt and adopt_now:
                self._record("adopt", [(p, "found during verification") for p in adopt_now])
            audit_rows, unchained, audit_head, audit_failures = self._verify_audit()
            failures.extend(audit_failures)
            status: Literal["verified", "warnings", "failed"] = (
                "failed" if failures else "warnings" if warnings else "verified"
            )
            return Verification(
                status=status,
                checked_at=self._clock().isoformat(),
                files=sum(by_source.values()),
                bytes=total,
                entries=entries,
                head=head,
                audit_rows=audit_rows,
                audit_unchained=unchained,
                audit_head=audit_head,
                failures=failures,
                warnings=warnings,
                by_source=by_source,
                seconds=round(time.monotonic() - started, 2),
            )

    def _verify_audit(self) -> tuple[int, int, str, list[Finding]]:
        failures: list[Finding] = []
        rows = unchained = 0
        prev: str | None = None
        with self._meta.connect() as con:
            cursor = con.execute(
                "SELECT audit_id, ts, user_id, action, outcome, ip, detail, chain_hash"
                " FROM audit_log ORDER BY audit_id"
            )
            for audit_id, *content, chain in cursor:
                rows += 1
                if chain is None:
                    if prev is not None:
                        failures.append(
                            Finding("audit_changed", f"audit row {audit_id}", "chain hash removed")
                        )
                    else:
                        unchained += 1
                    continue
                expected = audit_hash(prev or GENESIS, content)
                if chain != expected:
                    failures.append(
                        Finding(
                            "audit_changed", f"audit row {audit_id}", "content or order changed"
                        )
                    )
                prev = chain
        return rows, unchained, prev or GENESIS, failures

    def head(self) -> tuple[str, int]:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT hash, seq FROM lake_ledger ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return (str(row[0]), int(row[1])) if row else (GENESIS, 0)
