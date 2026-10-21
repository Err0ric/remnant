"""Integrity seals, alerts, and the exportable report (ADR-0022 rows 5 to 7).

Every verification is sealed: chain heads, counts, findings, and the result, signed with
HMAC-SHA256 under the install key. A failed check alerts the chosen targets; when
asked, each day's seal is sent to them too, so a copy of the heads lives off the server.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.alerts.dispatch import AlertDispatcher
from app.alerts.render import Alert
from app.core.branding import PRODUCT_NAME
from app.ingest.integrity import Finding, IntegrityLedger, Verification
from app.meta.audit import AuditLog
from app.meta.db import MetaDB

MAX_FINDINGS = 500  # kept per seal; the count is always exact


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


class IntegrityService:
    def __init__(
        self,
        meta: MetaDB,
        ledger: IntegrityLedger,
        audit: AuditLog,
        key: Callable[[], bytes],
        dispatcher: AlertDispatcher | None = None,
        link: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._meta = meta
        self._ledger = ledger
        self._audit = audit
        self._install_key = key  # read on first seal; the key file is created lazily
        self._subkey: bytes | None = None
        self._dispatcher = dispatcher
        self._link = link
        self._clock = clock

    @property
    def _key(self) -> bytes:
        if self._subkey is None:  # own subkey, never the install key itself
            self._subkey = hmac.new(
                self._install_key(), b"integrity-seal-v1", hashlib.sha256
            ).digest()
        return self._subkey

    # --- settings -------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT target_ids, send_seals, updated_at FROM integrity_settings WHERE id = 1"
            ).fetchone()
        if row is None:
            return {"target_ids": [], "send_seals": False, "updated_at": None}
        return {
            "target_ids": list(json.loads(row[0] or "[]")),
            "send_seals": bool(row[1]),
            "updated_at": row[2],
        }

    def save_settings(self, target_ids: list[str], send_seals: bool, user_id: str) -> None:
        now = self._clock().isoformat()
        with self._meta.connect() as con:
            con.execute(
                "INSERT INTO integrity_settings"
                " (id, target_ids, send_seals, updated_at, updated_by)"
                " VALUES (1, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET"
                " target_ids = excluded.target_ids, send_seals = excluded.send_seals,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (json.dumps(target_ids), int(send_seals), now, user_id),
            )

    # --- sealing --------------------------------------------------------------------------

    def against_last_seal(self, result: Verification) -> None:
        """Compare the chains with the newest seal that still verifies (security review):
        what a seal recorded must still be in the chains, so wiping or rewriting them
        cannot pass as a fresh start. Adds failures to `result`."""
        seals = self.seals(days=400)[:50]
        if not seals:
            return
        good = next((s for s in seals if self.check_seal(s)), None)
        found: list[Finding] = []
        if good is None:
            found.append(
                Finding("seal_mismatch", "integrity seals", "no stored seal verifies any more")
            )
        else:
            label = f"seal {good['seal_id']}"
            # By hash, not position: seals made before D69 paired the head with a later
            # ledger length, and the verified chain proves everything before the head.
            if not self._ledger.audit_hash_present("lake_ledger", good["lake_head"]):
                found.append(
                    Finding("seal_mismatch", label, "the ledger no longer holds what it sealed")
                )
            if not self._ledger.audit_hash_present("audit_log", good["audit_head"]):
                found.append(
                    Finding(
                        "seal_mismatch", label, "the audit chain no longer holds what it sealed"
                    )
                )
            if good.get("llm_head") and not self._ledger.audit_hash_present(
                "llm_calls", good["llm_head"]
            ):
                found.append(
                    Finding(
                        "seal_mismatch", label, "the AI call chain no longer holds what it sealed"
                    )
                )
        if found:
            result.failures.extend(found)
            result.status = "failed"

    def seal(self, result: Verification, user_id: str | None = None) -> dict[str, Any]:
        """Store a signed seal for one verification, audit it, and alert as configured."""
        self.against_last_seal(result)
        seq = result.head_seq  # the entry the checked head belongs to, not the newest one
        findings = [{"severity": "failure", **asdict(f)} for f in result.failures] + [
            {"severity": "warning", **asdict(f)} for f in result.warnings
        ]
        body = {
            "at": result.checked_at,
            "status": result.status,
            "lake_head": result.head,
            "lake_seq": seq,
            "audit_head": result.audit_head,
            "audit_rows": result.audit_rows,
            "files": result.files,
            "failures": len(result.failures),
            "warnings": len(result.warnings),
            "llm_head": result.llm_head,
            "llm_rows": result.llm_rows,
        }
        stored = json.dumps(findings[:MAX_FINDINGS])
        body["findings_sha256"] = hashlib.sha256(stored.encode()).hexdigest()
        signature = hmac.new(self._key, _canonical(body), hashlib.sha256).hexdigest()
        with self._meta.connect() as con:
            cur = con.execute(
                "INSERT INTO integrity_seals (at, status, lake_head, lake_seq, audit_head,"
                " audit_rows, files, failures, warnings, findings, signature, llm_head, llm_rows,"
                " findings_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    body["at"],
                    body["status"],
                    body["lake_head"],
                    body["lake_seq"],
                    body["audit_head"],
                    body["audit_rows"],
                    body["files"],
                    body["failures"],
                    body["warnings"],
                    stored,
                    signature,
                    body["llm_head"],
                    body["llm_rows"],
                    body["findings_sha256"],
                ),
            )
            seal_id = int(cur.lastrowid or 0)
        self._audit.write(
            "integrity.verify",
            "success" if result.status != "failed" else "failure",
            user_id,
            None,
            {
                "seal_id": seal_id,
                "status": result.status,
                "failures": len(result.failures),
                "warnings": len(result.warnings),
                "lake_head": result.head,
            },
        )
        self._notify(result, seal_id, signature)
        return {"seal_id": seal_id, **body, "signature": signature}

    def _notify(self, result: Verification, seal_id: int, signature: str) -> None:
        settings = self.settings()
        targets = settings["target_ids"]
        if self._dispatcher is None or not targets:
            return
        if result.status == "failed":
            first = result.failures[0]
            alert = Alert(
                kind="integrity_failed",
                title="Log integrity",
                detail=f"{len(result.failures)} problem(s); first: {first.kind} {first.path}"[:300],
                count=len(result.failures),
                reason=None,
                range_start=result.checked_at,
                range_end=None,
                link=f"{self._link}/health#integrity" if self._link else None,
                product=PRODUCT_NAME,
            )
        elif settings["send_seals"] and self._due_daily(seal_id):
            alert = Alert(
                kind="integrity_seal",
                title="Log integrity seal",
                # The heads are the anchor: keep this message; it proves what the lake and
                # audit log held today if the server is ever changed (ADR-0022 row 5).
                detail=(
                    f"Seal {seal_id}: lake {result.head[:16]}, audit {result.audit_head[:16]},"
                    f" AI calls {result.llm_head[:16]},"
                    f" signature {signature[:16]}"
                ),
                count=result.files,
                reason=result.status,
                range_start=result.checked_at,
                range_end=None,
                link=f"{self._link}/health#integrity" if self._link else None,
                product=PRODUCT_NAME,
            )
        else:
            return
        self._dispatcher.enqueue(alert, targets, None, None)

    def _due_daily(self, seal_id: int) -> bool:
        """One seal message per UTC day, whatever the verification interval."""
        today = self._clock().date().isoformat()
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT count(*) FROM integrity_seals WHERE seal_id < ? AND substr(at, 1, 10) = ?",
                (seal_id, today),
            ).fetchone()
        return int(row[0]) == 0

    def checked_within(self, seconds: float) -> bool:
        """Whether a check was sealed in the last `seconds` (a burst of clicks on Verify now
        would otherwise fill the history with identical seals)."""
        with self._meta.connect() as con:
            row = con.execute(
                "SELECT at FROM integrity_seals ORDER BY seal_id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return False
        try:
            last = datetime.fromisoformat(str(row[0]))
        except ValueError:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (self._clock() - last).total_seconds() < seconds

    # --- reading --------------------------------------------------------------------------

    def seals(self, days: int = 30) -> list[dict[str, Any]]:
        since = (self._clock() - timedelta(days=days)).isoformat()
        with self._meta.connect() as con:
            rows = con.execute(
                "SELECT seal_id, at, status, lake_head, lake_seq, audit_head, audit_rows, files,"
                " failures, warnings, findings, signature, llm_head, llm_rows, findings_sha256"
                " FROM integrity_seals"
                " WHERE at >= ? ORDER BY seal_id DESC LIMIT 400",
                (since,),
            ).fetchall()
        return [
            {
                "seal_id": r[0],
                "at": r[1],
                "status": r[2],
                "lake_head": r[3],
                "lake_seq": r[4],
                "audit_head": r[5],
                "audit_rows": r[6],
                "files": r[7],
                "failures": r[8],
                "warnings": r[9],
                "findings": json.loads(r[10] or "[]"),
                "signature": r[11],
                "llm_head": r[12],
                "llm_rows": r[13],
                "findings_sha256": r[14],
            }
            for r in rows
        ]

    def check_seal(self, seal: dict[str, Any]) -> bool:
        body = {
            k: seal[k]
            for k in (
                "at",
                "status",
                "lake_head",
                "lake_seq",
                "audit_head",
                "audit_rows",
                "files",
                "failures",
                "warnings",
            )
        }
        if seal.get("llm_head"):  # seals made before AI calls were chained (D61) lack it
            body |= {"llm_head": seal["llm_head"], "llm_rows": seal["llm_rows"]}
        if seal.get("findings_sha256"):  # since D64 the findings are signed too
            stored = json.dumps(seal.get("findings", []))
            if hashlib.sha256(stored.encode()).hexdigest() != seal["findings_sha256"]:
                return False
            body["findings_sha256"] = seal["findings_sha256"]
        expected = hmac.new(self._key, _canonical(body), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(seal.get("signature", "")))

    def report(self, days: int, user_id: str | None) -> dict[str, Any]:
        """Everything a third party needs, signed (ADR-0022 row 7)."""
        seals = self.seals(days)
        head, seq = self._ledger.head()
        body = {
            "product": PRODUCT_NAME,
            "generated_at": self._clock().isoformat(),
            "period_days": days,
            "lake_head": head,
            "lake_entries": seq,
            "seals": seals,
            "how_to_check": (
                "lake_head, audit_head, and llm_head in each seal are SHA-256 chain heads: "
                "compare them with the copies sent to your alert targets. The signature is "
                "HMAC-SHA256 over the seal's canonical JSON without findings and signature, "
                "keyed from this install's key, so only this install can check it."
            ),
        }
        body["signature"] = hmac.new(self._key, _canonical(body), hashlib.sha256).hexdigest()
        self._audit.write(
            "integrity.report", "success", user_id, None, {"days": days, "seals": len(seals)}
        )
        return body
