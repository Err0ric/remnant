"""Log integrity (ADR-0022): the lake ledger, the audit chain, seals, and the API."""

import json
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
    again = ledger.verify().warnings  # adopted once, then listed as adopted for a week
    assert [(w.kind, w.path.split("/")[-1]) for w in again] == [
        ("adopted", "part-0000-inserted.parquet")
    ]


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


# --- security review fixes (D64) -------------------------------------------------------


def test_files_outside_the_layout_are_not_read_and_are_reported(tmp_path: Path) -> None:
    from app.engine.duckdb import QueryEngine, QueryScope

    _, lake, ledger, writer = setup(tmp_path)
    writer.write(rows("a", TODAY, 3))
    src = parts(lake, "a", TODAY)[0]
    shutil.copy(src, lake / "source=a" / "evil.parquet")
    shutil.copy(src, src.with_name("evil.parquet"))
    future = src.with_name("part-future.parquet")
    shutil.copy(src, future)
    os.utime(future, (4102444800, 4102444800))  # 2100: never "just written"
    age(lake)
    os.utime(future, (4102444800, 4102444800))
    count = QueryEngine(lake).run("SELECT count(*) FROM events", QueryScope(None)).rows[0][0]
    assert count == 6  # the real file and the dated copy in the right place, not the strays
    kinds = sorted((w.kind, w.path.split("/")[-1]) for w in ledger.verify().warnings)
    assert ("stray", "evil.parquet") in kinds
    assert ("unknown", "part-future.parquet") in kinds


def test_cleanup_jobs_do_not_launder_an_edited_file(tmp_path: Path) -> None:
    from app.ingest.durable import sweep

    _, lake, ledger, writer = setup(tmp_path)
    day = TODAY - timedelta(days=1)
    for i in range(3):
        writer.write(rows("a", day, 3, start=i * 3))
    first, second = parts(lake, "a", day)[:2]
    first.write_bytes(b"")  # emptied: would look like a crash leftover
    assert sweep(lake, events=ledger) == 0 and first.exists()
    second.write_bytes(second.read_bytes() + b"x")
    Compactor(lake, today=lambda: TODAY, events=ledger).run()
    assert second.exists()  # never merged into a fresh, recorded file
    age(lake)
    failed = {(f.kind, f.path.split("/")[-1]) for f in ledger.verify().failures}
    assert ("changed", first.name) in failed and ("changed", second.name) in failed


def test_a_forged_manifest_deletes_nothing(tmp_path: Path) -> None:
    from app.ingest.compaction import MANIFEST_SUFFIX

    _, lake, ledger, writer = setup(tmp_path)
    day = TODAY  # an open day with few files: compaction itself merges nothing
    writer.write(rows("a", day, 3))
    writer.write(rows("a", day, 3, start=10))
    keep, evidence = parts(lake, "a", day)
    forged = keep.with_name(f"{keep.stem}{MANIFEST_SUFFIX}")
    forged.write_text(json.dumps({"output": keep.name, "inputs": [evidence.name]}))
    Compactor(lake, today=lambda: TODAY, events=ledger, min_files_open_day=99).run()
    assert evidence.exists() and not forged.exists()


def test_wiping_the_chains_fails_against_the_last_seal(tmp_path: Path) -> None:
    meta, _, ledger, writer = setup(tmp_path)
    audit = AuditLog(meta)
    svc = IntegrityService(meta, ledger, audit, lambda: KEY)
    writer.write(rows("a", TODAY, 3))
    audit.write("query.run", "success", "u1")
    assert svc.seal(ledger.verify())["status"] == "verified"
    with sqlite3.connect(tmp_path / "meta.sqlite") as con:
        for (n,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
            " AND tbl_name IN ('audit_log', 'lake_ledger')"
        ).fetchall():
            con.execute(f"DROP TRIGGER {n}")
        con.execute("UPDATE audit_log SET chain_hash = NULL")
        con.execute("DELETE FROM lake_ledger")
    ledger.ensure_baseline()  # a fresh start that would otherwise look clean
    seal = svc.seal(ledger.verify())
    assert seal["status"] == "failed"
    with meta.connect() as con:
        findings = json.loads(
            con.execute("SELECT findings FROM integrity_seals ORDER BY seal_id DESC").fetchone()[0]
        )
    assert {f["kind"] for f in findings} >= {"seal_mismatch"}


def test_seals_and_their_findings_cannot_be_edited(tmp_path: Path) -> None:
    meta, _, ledger, writer = setup(tmp_path)
    svc = IntegrityService(meta, ledger, AuditLog(meta), lambda: KEY)
    writer.write(rows("a", TODAY, 1))
    svc.seal(ledger.verify())
    with pytest.raises(sqlite3.DatabaseError), meta.connect() as con:
        con.execute("UPDATE integrity_seals SET findings = '[]'")
    stored = svc.seals(1)[0]
    assert svc.check_seal(stored)
    forged = {
        **stored,
        "findings": [{"severity": "warning", "kind": "x", "path": "y", "detail": "z"}],
    }
    assert not svc.check_seal(forged)


def test_one_verification_at_a_time(lab: dict[str, Any]) -> None:
    ledger = lab["app"].state.integrity
    with ledger._verify_lock:  # a verification is running
        res = lab["admin"].post("/api/integrity/verify", headers=lab["h"])
    assert res.status_code == 409


def test_files_written_while_checking_do_not_fail_the_next_check(tmp_path: Path) -> None:
    # Found on an upgraded install: the seal paired the head the check read with the ledger
    # length at sealing time, so any write (or adoption) in between failed every later check.
    meta, _, ledger, writer = setup(tmp_path)
    svc = IntegrityService(meta, ledger, AuditLog(meta), lambda: KEY)
    writer.write(rows("a", TODAY, 3))
    result = ledger.verify()
    writer.write(rows("b", TODAY, 2))  # ingest keeps writing before the seal is stored
    seal = svc.seal(result)
    assert seal["lake_seq"] == 1 and seal["lake_head"] == ledger.hash_at(1)
    assert svc.seal(ledger.verify())["status"] == "verified"


def test_an_upgrade_baselines_old_files_even_after_ingest_wrote_first(tmp_path: Path) -> None:
    # Found on an upgraded install: ingest recorded a new file before the start-up baseline
    # ran, so the baseline saw a non-empty ledger and the old files were adopted as unknown.
    meta, lake, ledger, writer = setup(tmp_path)
    LakeWriter(lake).write(rows("old", TODAY, 5))  # written by a version without the ledger
    age(lake)
    writer.write(rows("new", TODAY, 2))  # the upgraded ingest wins the race
    assert ledger.ensure_baseline() == 1
    assert ops(meta) == ["add", "baseline"]
    result = ledger.verify()
    assert result.status == "verified" and result.warnings == []
    svc = IntegrityService(meta, ledger, AuditLog(meta), lambda: KEY)
    svc.seal(result)
    LakeWriter(lake).write(rows("planted", TODAY, 1))  # after the first seal: never baselined
    age(lake)
    assert ledger.ensure_baseline() == 0
    assert {w.kind for w in ledger.verify().warnings} == {"unknown"}


def test_verify_now_waits_a_moment_between_checks(lab: dict[str, Any]) -> None:
    # Found on the homelab: repeated clicks ran 24 checks in two minutes.
    first = lab["admin"].post("/api/integrity/verify", headers=lab["h"])
    assert first.status_code == 200
    again = lab["admin"].post("/api/integrity/verify", headers=lab["h"])
    assert again.status_code == 409 and "moments ago" in again.json()["detail"]
