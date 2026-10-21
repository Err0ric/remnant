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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

import structlog

from app.core.chain import GENESIS, audit_hash, entry_hash, llm_chain_content
from app.meta.db import MetaDB

log = structlog.get_logger(__name__)

RECENT_S = 120.0
ADOPTED_LISTED = timedelta(days=7)  # a file this new may be mid-publish: never judged unknown yet
CHUNK = 1 << 20

Op = Literal["add", "remove", "baseline", "adopt"]


class LakeEvents(Protocol):
    """What the writer, compaction, retention, and quarantine report (ADR-0022 row 2)."""

    def added(self, paths: Sequence[Path]) -> None: ...

    def removed(self, paths: Sequence[Path], reason: str) -> list[Path]:
        """Record the removal and return the paths that may go. A file whose content no
        longer matches the ledger is kept, so verification reports it as changed."""
        ...

    def unchanged(self, paths: Sequence[Path]) -> list[Path]:
        """The paths whose content still matches the ledger (or that it never saw)."""
        ...


class NoEvents:
    def added(self, paths: Sequence[Path]) -> None:
        return None

    def removed(self, paths: Sequence[Path], reason: str) -> list[Path]:
        return list(paths)

    def unchanged(self, paths: Sequence[Path]) -> list[Path]:
        return list(paths)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class Finding:
    # changed, missing, chain_broken, audit_changed, seal_mismatch, unknown, adopted,
    # stray, removal_pending
    kind: str
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
    llm_rows: int = 0
    llm_unchained: int = 0
    llm_head: str = GENESIS
    head_seq: int = 0  # the ledger entry `head` belongs to (writes may follow before sealing)


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

    def removed(self, paths: Sequence[Path], reason: str) -> list[Path]:
        ok = self.unchanged(paths)
        self._record("remove", [(p, reason[:200]) for p in ok], hash_files=False)
        return ok

    def unchanged(self, paths: Sequence[Path]) -> list[Path]:
        ok = []
        for p in paths:
            rel = self._rel(p)
            last = self._last_sha(rel) if rel is not None else ""
            if last and p.is_file():
                try:
                    current = file_sha256(p)
                except OSError:
                    current = last  # unreadable: the verifier reports it
                if current != last:
                    log.warning("integrity.changed_file_kept", file=rel)
                    continue
            ok.append(p)
        return ok

    def ensure_baseline(self) -> int:
        """First start with the ledger (or an install that predates it): every file in the
        lake not yet recorded becomes a `baseline` entry. Runs until the first baseline or
        the first seal, so ingest recording a new file first does not turn the older files
        into unknown ones; after either, an unrecorded file is reported, never baselined.
        Returns how many were recorded."""
        with self._meta.connect() as con:
            if (
                con.execute("SELECT 1 FROM lake_ledger WHERE op = 'baseline' LIMIT 1").fetchone()
                or con.execute("SELECT 1 FROM integrity_seals LIMIT 1").fetchone()
            ):
                return 0
            known = {str(r[0]) for r in con.execute("SELECT DISTINCT path FROM lake_ledger")}
        files = [p for p in self._lake_files() if self._rel(p) not in known]
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
            # Take the write lock before reading the head, so another process (the admin
            # CLI) cannot chain from the same entry (security review).
            con.execute("BEGIN IMMEDIATE")
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

    def _strays(self) -> list[str]:
        """Parquet files anywhere else under the lake. Searches do not read them (the
        engine reads only source=*/day=*/part-*.parquet), but someone put them there."""
        if not self._lake.is_dir():
            return []
        canonical = {p for p in self._lake.glob("source=*/day=*/part-*.parquet")}
        return sorted(
            p.relative_to(self._lake).as_posix()
            for p in self._lake.rglob("*.parquet")
            if p not in canonical or p.is_symlink() or p.parent.is_symlink()
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
            prev, entries, head_seq = GENESIS, 0, 0
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
                    prev, head_seq = h, seq
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
                    age = now - path.stat().st_mtime
                except OSError:
                    continue
                if 0 <= age < RECENT_S:
                    continue  # may be mid-publish: the writer records it in a moment
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
            for rel in self._strays():
                warnings.append(
                    Finding("stray", rel, "not where the writer puts files; searches skip it")
                )
            # Files adopted lately stay listed, so one quiet run cannot hide them.
            for rel, at in self._recently_adopted(exclude={self._rel(p) for p in adopt_now}):
                warnings.append(Finding("adopted", rel, f"adopted {at[:10]}; check it is yours"))
            audit_rows, unchained, audit_head, audit_failures = self._verify_audit()
            failures.extend(audit_failures)
            llm_rows, llm_unchained, llm_head, llm_failures = self._verify_llm()
            failures.extend(llm_failures)
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
                head_seq=head_seq,
                audit_rows=audit_rows,
                audit_unchained=unchained,
                audit_head=audit_head,
                failures=failures,
                warnings=warnings,
                by_source=by_source,
                seconds=round(time.monotonic() - started, 2),
                llm_rows=llm_rows,
                llm_unchained=llm_unchained,
                llm_head=llm_head,
            )

    def _recently_adopted(self, exclude: set[str | None]) -> list[tuple[str, str]]:
        since = (self._clock() - ADOPTED_LISTED).isoformat()
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT path, max(at) FROM lake_ledger WHERE op = 'adopt' AND at >= ?"
                " GROUP BY path ORDER BY path LIMIT 200",
                (since,),
            ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows if r[0] not in exclude]

    def hash_at(self, seq: int) -> str | None:
        with self._meta.connect() as con:
            row = con.execute("SELECT hash FROM lake_ledger WHERE seq = ?", (seq,)).fetchone()
        return str(row[0]) if row else None

    def audit_hash_present(self, table: str, head: str) -> bool:
        """Whether a chain head recorded in a seal is still in the chain."""
        if head == GENESIS or not head:
            return True
        sql = {
            "audit_log": "SELECT 1 FROM audit_log WHERE chain_hash = ? LIMIT 1",
            "llm_calls": "SELECT 1 FROM llm_calls WHERE chain_hash = ? LIMIT 1",
            "lake_ledger": "SELECT 1 FROM lake_ledger WHERE hash = ? LIMIT 1",
        }[table]
        with self._meta.connect() as con:
            return con.execute(sql, (head,)).fetchone() is not None

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

    def _verify_llm(self) -> tuple[int, int, str, list[Finding]]:
        """AI call records (D61): completed rows chain in completion order. A completed row
        without a hash is fine only if it was completed before the first chained row."""
        failures: list[Finding] = []
        prev, expected_seq, rows = GENESIS, 1, 0
        first_chained_at: str | None = None
        with self._meta.connect() as con:
            con.row_factory = None
            names = [r[1] for r in con.execute("PRAGMA table_info(llm_calls)")]
            cursor = con.execute(
                "SELECT * FROM llm_calls WHERE chain_seq IS NOT NULL ORDER BY chain_seq"
            )
            for raw in cursor:
                row = dict(zip(names, raw, strict=True))
                rows += 1
                where = f"AI call {row['call_id']}"
                if row["chain_seq"] != expected_seq:
                    failures.append(
                        Finding("audit_changed", where, "AI call record missing before it")
                    )
                expected_seq = row["chain_seq"] + 1
                if row["chain_hash"] != audit_hash(prev, llm_chain_content(row)):
                    failures.append(Finding("audit_changed", where, "content or order changed"))
                prev = row["chain_hash"]
                first_chained_at = first_chained_at or row["finished_at"]
            late, unchained = 0, 0
            for (finished_at,) in con.execute(
                "SELECT finished_at FROM llm_calls"
                " WHERE chain_seq IS NULL AND finished_at IS NOT NULL"
            ):
                if first_chained_at is not None and finished_at >= first_chained_at:
                    late += 1
                else:
                    unchained += 1
        if late:
            failures.append(
                Finding(
                    "audit_changed", "AI call records", f"{late} completed without a chain hash"
                )
            )
        return rows + unchained + late, unchained, prev, failures

    def busy(self) -> bool:
        return self._verify_lock.locked()

    def head(self) -> tuple[str, int]:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT hash, seq FROM lake_ledger ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return (str(row[0]), int(row[1])) if row else (GENESIS, 0)
