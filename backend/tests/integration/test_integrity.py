"""Log integrity (ADR-0022): the lake ledger, the audit chain, seals, and the API."""

import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.chain import GENESIS
from app.ingest.compaction import Compactor
from app.ingest.durable import quarantine
from app.ingest.integrity import IntegrityLedger
from app.ingest.retention import RetentionJob
from app.ingest.writer import LakeWriter
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from app.ops.integrity import IntegrityService
from tests.integration.test_lake_maintenance import TODAY, parts, rows
from tests.integration.test_schedules import make_lab

KEY = b"k" * 44


def setup(tmp_path: Path) -> tuple[MetaDB, Path, IntegrityLedger, LakeWriter]:
    meta = MetaDB(tmp_path / "meta.sqlite")
    lake = tmp_path / "lake"
    ledger = IntegrityLedger(meta, lake)
    return meta, lake, ledger, LakeWriter(lake, ledger)


def age(lake: Path) -> None:
    """Make every file old enough that the verifier judges it (RECENT_S)."""
    old = datetime.now(UTC).timestamp() - 3600
    for p in lake.rglob("*.parquet"):
        os.utime(p, (old, old))


def ops(meta: MetaDB) -> list[str]:
    with meta.connect() as con:
        return [r[0] for r in con.execute("SELECT op FROM lake_ledger ORDER BY seq")]


def test_writes_are_recorded_and_a_clean_lake_verifies(tmp_path: Path) -> None:
    meta, _, ledger, writer = setup(tmp_path)
    writer.write(rows("app", TODAY, 5))
    writer.write(rows("web", TODAY, 3))
    assert ops(meta) == ["add", "add"]
    result = ledger.verify()
    assert result.status == "verified"
    assert result.files == 2 and result.by_source == {"app": 1, "web": 1}
    assert result.head == ledger.head()[0] != GENESIS


def test_baseline_covers_files_written_before_the_ledger(tmp_path: Path) -> None:
    meta, lake, ledger, _ = setup(tmp_path)
    LakeWriter(lake).write(rows("app", TODAY, 5))  # no events: an older install
    assert ledger.ensure_baseline() == 1
    assert ledger.ensure_baseline() == 0  # once only
    assert ops(meta) == ["baseline"]
    assert ledger.verify().status == "verified"


def test_compaction_retention_and_quarantine_are_recorded(tmp_path: Path) -> None:
    meta, lake, ledger, writer = setup(tmp_path)
    old_day, day = TODAY - timedelta(days=40), TODAY - timedelta(days=1)
    writer.write(rows("app", old_day, 2))
    for i in range(4):
        writer.write(rows("app", day, 5, start=i * 5))
    Compactor(lake, today=lambda: TODAY, events=ledger).run()
    assert len(parts(lake, "app", day)) == 1
    RetentionJob(lake, {}, default_days=30, today=lambda: TODAY, events=ledger).run()
    assert not parts(lake, "app", old_day)
    writer.write(rows("app", TODAY, 1))
    quarantine(lake, parts(lake, "app", TODAY)[0], "test", events=ledger)
    with meta.connect() as con:
        reasons = [r[0] for r in con.execute("SELECT reason FROM lake_ledger WHERE op='remove'")]
    assert sum(r.startswith("compacted into") for r in reasons) == 4
    assert any(r.startswith("retention") for r in reasons)
    assert any(r.startswith("quarantine") for r in reasons)
    age(lake)
    assert ledger.verify().status == "verified"


def test_changed_missing_and_inserted_files(tmp_path: Path) -> None:
    meta, lake, ledger, writer = setup(tmp_path)
    for s in ("a", "b", "c"):
        writer.write(rows(s, TODAY, 3))
    a, b = parts(lake, "a", TODAY)[0], parts(lake, "b", TODAY)[0]
    a.write_bytes(a.read_bytes()[:-8] + b"tampered")
    b.unlink()
    extra = lake / "source=c" / f"day={TODAY.isoformat()}" / "part-0000-inserted.parquet"
    shutil.copy(parts(lake, "c", TODAY)[0], extra)
    age(lake)
    result = ledger.verify()
    assert result.status == "failed"
    kinds = {(f.kind, f.path.split("/")[0]) for f in result.failures}
    assert kinds == {("changed", "source=a"), ("missing", "source=b")}
    assert [w.kind for w in result.warnings] == ["unknown"]
    assert ops(meta)[-1] == "adopt"
    assert not ledger.verify().warnings  # adopted once, then known


def test_new_unrecorded_files_are_not_judged_yet(tmp_path: Path) -> None:
    _, lake, ledger, writer = setup(tmp_path)
    writer.write(rows("a", TODAY, 3))
    src = parts(lake, "a", TODAY)[0]
    shutil.copy(src, src.with_name("part-ffff-new.parquet"))  # mid-publish
    assert ledger.verify().status == "verified"


def test_edited_ledger_breaks_the_chain(tmp_path: Path) -> None:
    _, _, ledger, writer = setup(tmp_path)
    writer.write(rows("a", TODAY, 3))
    writer.write(rows("a", TODAY, 3))
    with sqlite3.connect(tmp_path / "meta.sqlite") as con:
        names = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='lake_ledger'"
            )
        ]
        for n in names:
            con.execute(f"DROP TRIGGER {n}")
        con.execute("UPDATE lake_ledger SET size = size + 1 WHERE seq = 1")
    assert any(f.kind == "chain_broken" for f in ledger.verify().failures)


def test_audit_rows_are_chained_and_edits_detected(tmp_path: Path) -> None:
    meta, _, ledger, _ = setup(tmp_path)
    audit = AuditLog(meta)
    for i in range(3):
        audit.write("query.run", "success", "u1", None, {"n": i})
    result = ledger.verify()
    assert result.audit_rows == 3 and result.audit_unchained == 0
    assert result.status == "verified"
    with sqlite3.connect(tmp_path / "meta.sqlite") as con:
        for (n,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
        ).fetchall():
            con.execute(f"DROP TRIGGER {n}")
        con.execute("UPDATE audit_log SET user_id = 'someone-else' WHERE audit_id = 2")
    failures = ledger.verify().failures
    assert [(f.kind, f.path) for f in failures] == [("audit_changed", "audit row 2")]


def test_seals_are_signed_and_failures_alert(tmp_path: Path) -> None:
    meta, lake, ledger, writer = setup(tmp_path)
    sent: list[tuple[Any, list[str]]] = []

    class Dispatcher:
        def enqueue(self, alert: Any, targets: list[str], *_: Any) -> None:
            sent.append((alert, targets))

    svc = IntegrityService(meta, ledger, AuditLog(meta), lambda: KEY, Dispatcher())  # type: ignore[arg-type]  # a fake with the one method used
    writer.write(rows("a", TODAY, 3))
    seal = svc.seal(ledger.verify(), "admin1")
    stored = svc.seals(1)[0]
    assert stored["signature"] == seal["signature"] and svc.check_seal(stored)
    assert not svc.check_seal({**stored, "files": stored["files"] + 1})
    assert not sent  # no targets yet

    svc.save_settings(["t1"], send_seals=True, user_id="admin1")
    svc.seal(ledger.verify())
    assert sent == []  # a seal message already counted today (first seal of the day)
    parts(lake, "a", TODAY)[0].unlink()
    svc.seal(ledger.verify())
    assert [a.kind for a, _ in sent] == ["integrity_failed"]
    assert sent[0][1] == ["t1"]

    report = svc.report(30, "aud1")
    assert len(report["seals"]) == 3 and len(report["signature"]) == 64
    with meta.connect() as con:
        actions = [r[0] for r in con.execute("SELECT action FROM audit_log")]
    assert actions.count("integrity.verify") == 3 and "integrity.report" in actions


def test_daily_seal_is_sent_once_per_day(tmp_path: Path) -> None:
    meta, _, ledger, _ = setup(tmp_path)
    sent: list[Any] = []

    class Dispatcher:
        def enqueue(self, alert: Any, *_: Any) -> None:
            sent.append(alert)

    svc = IntegrityService(meta, ledger, AuditLog(meta), lambda: KEY, Dispatcher())  # type: ignore[arg-type]  # a fake with the one method used
    svc.save_settings(["t1"], send_seals=True, user_id="admin1")
    svc.seal(ledger.verify())
    svc.seal(ledger.verify())
    assert [a.kind for a in sent] == ["integrity_seal"]
    assert "lake" in sent[0].detail and "audit" in sent[0].detail


# --- API ----------------------------------------------------------------------------


@pytest.fixture
def lab(tmp_path: Path) -> dict[str, Any]:
    return make_lab(tmp_path)


def test_api_roles_verify_report_and_settings(lab: dict[str, Any]) -> None:
    assert lab["ana"].get("/api/integrity").status_code == 403
    assert lab["aud"].post("/api/integrity/verify").status_code in (403, 400)
    age(lab["app"].state.lake_dir)
    res = lab["admin"].post("/api/integrity/verify", headers=lab["h"])
    assert res.status_code == 200, res.text
    seal = res.json()
    assert seal["status"] == "verified" and seal["signature_ok"] and seal["files"] >= 1

    status = lab["aud"].get("/api/integrity").json()
    assert status["latest"]["seal_id"] == seal["seal_id"]
    assert status["settings"]["target_ids"] == []

    report = lab["aud"].get("/api/integrity/report", params={"days": 7})
    assert report.status_code == 200 and report.json()["seals"][0]["seal_id"] == seal["seal_id"]

    bad = lab["admin"].put(
        "/api/integrity/settings",
        json={"target_ids": ["nope"], "send_seals": True},
        headers=lab["h"],
    )
    assert bad.status_code == 404
    ok = lab["admin"].put(
        "/api/integrity/settings", json={"target_ids": [], "send_seals": True}, headers=lab["h"]
    )
    assert ok.status_code == 200 and ok.json()["send_seals"] is True
    actions = {
        r["action"]
        for r in lab["aud"].get("/api/audit/events", params={"action": "integrity."}).json()
    }
    assert {
        "integrity.verify",
        "integrity.view",
        "integrity.report",
        "integrity.settings",
    } <= actions


def test_lake_tampering_shows_in_the_api(lab: dict[str, Any]) -> None:
    lake: Path = lab["app"].state.lake_dir
    victim = sorted(lake.rglob("part-*.parquet"))[0]
    victim.write_bytes(victim.read_bytes() + b"x")
    age(lake)
    seal = lab["admin"].post("/api/integrity/verify", headers=lab["h"]).json()
    assert seal["status"] == "failed"
    assert seal["findings"][0]["kind"] == "changed"
