"""scripts/restore_alert_text.py turns the codes in AI watch alerts and mutes back into
names in place, from each row's own People and the install key (review of PR 518).
Everything changed since the rewrite stays; rule alerts, read positions, the lake
ledger, and earlier audit rows are untouched; a run that changes something adds one
chained audit row with counts only; the copy is only read for People."""

import getpass
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.alerts.items import AlertItems
from app.ingest.integrity import IntegrityLedger
from app.meta.audit import AuditLog
from app.meta.db import MetaDB
from tests.integration.test_alert_grouping import NOW, Clock
from tests.integration.test_alerts_store_no_names import _at, _start, backups

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "restore_alert_text.py"
# The system python3 where there is one, as an administrator runs it.
PYTHON = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else sys.executable
NAMES = ("alice", "bob", "carol", "dave", "erin")
TEXT = ("subject", "ref_id", "entity", "title", "detail", "why")
ITEM_COLS = (
    "item_id, kind, subject, ref_id, title, detail, why, created_at, people, entity, rule,"
    " day, last_seen, changes"
)
OLD_ITEMS = [  # as older versions stored them: names in the text
    ("i-1", "ai_watch", "sensitive:alice@example.com", "sensitive:alice@example.com:2026-10-10",
     "Sensitive data to AI: alice@example.com", "", "secret x1", "2026-10-10T08:00:00+00:00",
     '["alice@example.com"]', "sensitive:alice@example.com", "sensitive", "2026-10-10",
     "2026-10-10T08:00:00+00:00",
     '{"lines": ["Sensitive data to AI: alice@example.com"], "more": 0}'),
    ("i-2", "ai_watch", "agent:cc|carol@example.com", "agent:cc|carol@example.com:agent",
     "AI agent not reviewed: Claude Code, carol@example.com", "",
     "In use; owner carol@example.com; device ws-1", "2026-10-10T09:00:00+00:00", None,
     None, None, None, None, None),
    ("i-3", "rule", "rule:r1", "rule:r1:run1", "Rule matched for bob", "bob on ws-2", None,
     "2026-10-10T10:00:00+00:00", None, "rule:r1", "rule", "2026-10-10",
     "2026-10-10T10:00:00+00:00", '{"lines": ["Rule matched for bob"], "more": 0}'),
]  # fmt: skip
VALUES = "VALUES (" + ", ".join("?" * len(OLD_ITEMS[0])) + ")"


def _seed(data: Path) -> None:
    meta = MetaDB(data / "meta.sqlite")
    with meta.connect() as con:
        con.executemany(f"INSERT INTO alert_items ({ITEM_COLS}) {VALUES}", OLD_ITEMS)
        con.execute(
            "INSERT INTO alert_mutes (mute_id, kind, subject, title, until, created_at)"
            " VALUES ('m-1', 'ai_watch', 'sensitive:alice@example.com',"
            " 'Sensitive data to AI: alice@example.com', '2099-01-01T00:00:00+00:00',"
            " '2026-10-10T08:30:00+00:00')"
        )
        con.execute(
            "INSERT INTO sources (source_id, format, path, created_at)"
            " VALUES ('s1', 'syslog', '/var/log/a', '2026-10-01T00:00:00+00:00')"
        )
        con.execute(
            "INSERT INTO checkpoints (source_id, path, inode, offset, updated_at)"
            " VALUES ('s1', '/var/log/a/x.log', 7, 100, '2026-10-10T00:00:00+00:00')"
        )
        con.execute(
            "INSERT INTO lake_ledger (at, op, path, sha256, size, prev_hash, hash) VALUES"
            " ('2026-10-10T00:00:00+00:00', 'add', 'p1.parquet', 'aa', 1, '0', 'h1')"
        )
    AuditLog(meta).write("test.seed", "success", "u0")


def _tables(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    con = sqlite3.connect(db)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {
            n: sorted(con.execute(f'SELECT * FROM "{n}"').fetchall(), key=repr) for n in names
        }  # table names from the schema
    finally:
        con.close()


def _rows(db: Path, table: str, key: str) -> dict[str, dict[str, Any]]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return {r[key]: dict(r) for r in con.execute(f"SELECT * FROM {table}")}  # fixed names
    finally:
        con.close()


def _sql(db: Path, sql: str, args: tuple[Any, ...] = ()) -> None:
    con = sqlite3.connect(db)
    try:
        with con:
            con.execute(sql, args)
    finally:
        con.close()


def _run(meta: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(  # our own script, fixed arguments
        [PYTHON, str(SCRIPT), "--meta", str(meta), *extra],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    out = (res.stdout + res.stderr).lower()
    assert not [n for n in NAMES if n in out], out  # counts only, never names
    return res


def _migrated(tmp_path: Path) -> tuple[Path, Path, str, Any]:
    """Seed old-style data, start the app (backup and rewrite), then raise a new AI watch
    alert as the new version stores it. Returns meta, backup, the new item's id, and the
    app's person codes."""
    data = tmp_path / "data"
    _seed(data)
    app = _start(tmp_path)
    refs = app.state.alert_items.refs
    ref = refs.ref("erin@example.com")  # as the watch stores it
    new = app.state.alert_items.raise_item(
        "ai_watch", f"sensitive:{ref}", f"Sensitive data to AI: {ref}",
        ref_id=f"sensitive:{ref}:2026-11-11", people=["erin@example.com"],
    )  # fmt: skip
    (copy,) = backups(data)
    return data / "meta.sqlite", copy, new.item_id, refs


def _restore_rows(meta: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(meta)
    try:
        return [
            {"user_id": r[0], "outcome": r[1], "ip": r[2], "detail": json.loads(r[3])}
            for r in con.execute(
                "SELECT user_id, outcome, ip, detail FROM audit_log"
                " WHERE action = 'alerts.restore_text' ORDER BY audit_id"
            )
        ]
    finally:
        con.close()


def _chain_verifies(meta: Path) -> None:
    """The app's own check of the audit chain finds nothing changed."""
    result = IntegrityLedger(MetaDB(meta), meta.parent / "lake").verify(adopt=False)
    assert result.audit_rows > 0 and result.audit_unchained == 0
    assert not [f for f in result.failures if f.kind.startswith("audit")], result.failures


def _read_as(row: dict[str, Any]) -> dict[str, Any]:
    out = {c: row[c] for c in TEXT}
    out["changes"] = json.loads(row["changes"]) if row["changes"] else None
    return out


def test_codes_become_names_in_place_and_later_changes_stay(tmp_path: Path) -> None:
    meta, backup, new_id, refs = _migrated(tmp_path)
    original = _rows(backup, "alert_items", "item_id")
    # The new version kept i-1 current after the rewrite: a repeat about dave.
    dave = refs.ref("dave@example.com")
    i1 = _rows(meta, "alert_items", "item_id")["i-1"]
    assert "alice" not in i1["title"] and "{p:" in i1["ref_id"]
    log = json.loads(i1["changes"])
    log["lines"].append(f"Sensitive data to AI: {dave}")
    _sql(
        meta,
        "UPDATE alert_items SET changes = ?, people = ?, count = 2 WHERE item_id = 'i-1'",
        (json.dumps(log), '["alice@example.com", "dave@example.com"]'),
    )
    migrated = _tables(meta)
    pre = _rows(meta, "alert_items", "item_id")

    dry = _run(meta, "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "alerts: 3; mutes: 1." in dry.stdout and "nothing was changed" in dry.stdout
    assert _tables(meta) == migrated

    done = _run(meta)
    assert done.returncode == 0, done.stderr
    assert "Put back names in AI watch alerts: 3; mutes: 1." in done.stdout
    assert "Left with codes" not in done.stdout

    items = _rows(meta, "alert_items", "item_id")
    i1 = items["i-1"]  # the repeat and dave, added after the copy, are kept
    assert json.loads(i1["changes"])["lines"] == [
        "Sensitive data to AI: alice@example.com",
        "Sensitive data to AI: dave@example.com",
    ]
    assert json.loads(i1["people"]) == ["alice@example.com", "dave@example.com"]
    assert i1["count"] == 2
    for item_id in ("i-1", "i-2"):  # old items read as the original names did
        want = _read_as(original[item_id])
        if item_id == "i-1":
            want["changes"]["lines"].append("Sensitive data to AI: dave@example.com")
        assert _read_as(items[item_id]) == want
    for item_id, row in items.items():  # only the text changed; People, count, ... stay
        assert {c: v for c, v in row.items() if c not in (*TEXT, "changes")} == {
            c: v for c, v in pre[item_id].items() if c not in (*TEXT, "changes")
        }
    assert items[new_id]["title"] == "Sensitive data to AI: erin@example.com"
    assert items["i-3"] == pre["i-3"]  # rule alerts untouched
    mute = _rows(meta, "alert_mutes", "mute_id")["m-1"]
    assert mute == _rows(backup, "alert_mutes", "mute_id")["m-1"]
    after = _tables(meta)
    for table in migrated.keys() - {"alert_items", "alert_mutes", "audit_log", "sqlite_sequence"}:
        assert after[table] == migrated[table], table
    assert after["checkpoints"] and after["lake_ledger"]
    # earlier audit rows stay; one row more, with counts only, chained as the server does
    assert set(migrated["audit_log"]) <= set(after["audit_log"])
    assert len(after["audit_log"]) == len(migrated["audit_log"]) + 1
    assert _restore_rows(meta) == [
        {
            "user_id": None,
            "outcome": "success",
            "ip": None,
            "detail": {
                "alerts_decoded": 3,
                "mutes_decoded": 1,
                "alerts_left_with_codes": 0,
                "mutes_left_with_codes": 0,
                "alerts_clashed": 0,
                "key_check_stored": False,
                "backup_used": False,
                "os_user": getpass.getuser(),
            },
        }
    ]
    con = sqlite3.connect(meta)
    try:
        (detail,) = con.execute(
            "SELECT detail FROM audit_log WHERE action = 'alerts.restore_text'"
        ).fetchone()
    finally:
        con.close()
    assert not [n for n in NAMES if n in detail.lower()]  # counts only, never names
    _chain_verifies(meta)
    AuditLog(MetaDB(meta)).write("test.after", "success", "u0")  # the server chains on
    _chain_verifies(meta)
    after = _tables(meta)

    again = _run(meta)  # a second run finds nothing left to put back
    assert again.returncode == 0, again.stderr
    assert "alerts: 0; mutes: 0." in again.stdout
    assert _tables(meta) == after


def test_a_wrong_key_is_refused(tmp_path: Path) -> None:
    meta, _, _, _ = _migrated(tmp_path)
    before = _tables(meta)
    other = tmp_path / "other.key"
    other.write_bytes(b"x" * 44 + b"\n")
    res = _run(meta, "--key", str(other))
    assert res.returncode == 3 and "not the key these alerts were coded with" in res.stderr
    assert _tables(meta) == before
    res = _run(meta, "--key", str(tmp_path / "missing.key"))
    assert res.returncode == 2 and "Key file not found" in res.stderr
    res = _run(meta, "--backup", str(tmp_path / "missing.sqlite"))
    assert res.returncode == 2 and "Backup not found" in res.stderr
    assert _tables(meta) == before


def _check(meta: Path) -> Any:
    con = sqlite3.connect(meta)
    try:
        row = con.execute(
            "SELECT value FROM one_time_fixes WHERE fix_id = 'alerts.person_codes'"
        ).fetchone()
        return row[0]
    finally:
        con.close()


def test_the_server_stores_the_key_check(tmp_path: Path) -> None:
    meta, _, _, refs = _migrated(tmp_path)
    assert _check(meta) == refs.ref("remnant-key-check")
    _sql(meta, "UPDATE one_time_fixes SET value = NULL")  # coded before the check existed
    _start(tmp_path)
    assert _check(meta) == refs.ref("remnant-key-check")


def test_a_wrong_key_is_refused_with_nothing_left_to_decode(tmp_path: Path) -> None:
    meta, _, _, _ = _migrated(tmp_path)
    assert _run(meta).returncode == 0
    before = _tables(meta)
    assert "{p:" not in str(before["alert_items"])
    other = tmp_path / "other.key"
    other.write_bytes(b"x" * 44 + b"\n")
    res = _run(meta, "--key", str(other))
    assert res.returncode == 3 and "not the key these alerts were coded with" in res.stderr
    assert _tables(meta) == before


@pytest.mark.parametrize("stored", [True, False])
def test_a_second_run_with_only_unmatched_codes_left(tmp_path: Path, stored: bool) -> None:
    """The first run leaves a code no name matches; the second, with the same key, is no
    wrong-key refusal. Without a stored check (coded before it existed), the first run
    proves the key by its matches and stores the check."""
    meta, _, _, refs = _migrated(tmp_path)
    if not stored:
        _sql(meta, "UPDATE one_time_fixes SET value = NULL")
    _sql(meta, "UPDATE alert_items SET people = '[\"bob@example.com\"]' WHERE item_id = 'i-1'")
    first = _run(meta)
    assert first.returncode == 0, first.stderr
    assert "Left with codes: 1 alerts and 1 mutes" in first.stdout
    assert ("no stored key check" in first.stderr) is not stored
    assert _check(meta) == refs.ref("remnant-key-check")
    after = _tables(meta)
    again = _run(meta)
    assert again.returncode == 0, again.stderr
    assert "alerts: 0; mutes: 0." in again.stdout
    assert "Left with codes: 1 alerts and 1 mutes" in again.stdout
    assert "no stored key check" not in again.stderr
    assert _tables(meta) == after


def test_without_a_stored_check_a_key_matching_nothing_is_refused(tmp_path: Path) -> None:
    meta, _, _, _ = _migrated(tmp_path)
    _sql(meta, "UPDATE one_time_fixes SET value = NULL")
    before = _tables(meta)
    other = tmp_path / "other.key"
    other.write_bytes(b"y" * 44 + b"\n")
    res = _run(meta, "--key", str(other))
    assert res.returncode == 3, res.stderr
    assert _tables(meta) == before


def test_a_name_gone_from_people_is_found_in_the_copy(tmp_path: Path) -> None:
    """A refresh replaced i-1's People since the copy: without --backup its codes stay
    and are counted; with it, they are found in the People the copy holds."""
    meta, backup, _, _ = _migrated(tmp_path)
    _sql(meta, "UPDATE alert_items SET people = '[\"bob@example.com\"]' WHERE item_id = 'i-1'")
    alone = _run(meta)
    assert alone.returncode == 0, alone.stderr
    assert "alerts: 2; mutes: 0." in alone.stdout
    assert "Left with codes: 1 alerts and 1 mutes" in alone.stdout
    assert "{p:" in _rows(meta, "alert_items", "item_id")["i-1"]["title"]
    copied = backup.read_bytes()
    found = _run(meta, "--backup", str(backup))
    assert found.returncode == 0, found.stderr
    assert "alerts: 1; mutes: 1." in found.stdout and "Left with codes" not in found.stdout
    i1 = _rows(meta, "alert_items", "item_id")["i-1"]
    assert i1["title"] == "Sensitive data to AI: alice@example.com"
    assert i1["people"] == '["bob@example.com"]'  # People stays as it is
    assert backup.read_bytes() == copied  # read only, nothing made beside it
    first, second = (r["detail"] for r in _restore_rows(meta))
    assert (first["alerts_left_with_codes"], first["mutes_left_with_codes"]) == (1, 1)
    assert not first["backup_used"] and second["backup_used"]
    assert (second["alerts_decoded"], second["mutes_decoded"]) == (1, 1)
    _chain_verifies(meta)
    assert sorted(p.name for p in backup.parent.iterdir()) == [backup.name]


def test_an_alert_whose_subject_was_taken_since_is_left(tmp_path: Path) -> None:
    """After the rollback the older version may raise an alert with the original ref id;
    decoding the old row would clash, so that row keeps its codes."""
    meta, _, _, _ = _migrated(tmp_path)
    _sql(meta, f"INSERT INTO alert_items ({ITEM_COLS}) {VALUES}", ("i-9", *OLD_ITEMS[0][1:]))
    res = _run(meta)
    assert res.returncode == 0, res.stderr
    assert "alerts: 2; mutes: 1." in res.stdout
    assert "Left with codes: 1 alerts (another alert" in res.stdout
    assert [r["detail"]["alerts_clashed"] for r in _restore_rows(meta)] == [1]
    items = _rows(meta, "alert_items", "item_id")
    assert all("{p:" in str(items["i-1"][c]) for c in ("subject", "ref_id", "title"))
    assert items["i-2"]["title"] == "AI agent not reviewed: Claude Code, carol@example.com"


def test_after_a_second_roll_forward_one_run_decodes_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The older version raised a named alert after a rollback, and rolling forward again
    coded it: one run decodes the alerts of both rewrites."""
    data = tmp_path / "data"
    _seed(data)
    _at(monkeypatch, NOW)
    _start(tmp_path)
    meta_db = MetaDB(data / "meta.sqlite")
    bob = AlertItems(meta_db, AuditLog(meta_db), clock=Clock()).raise_item(  # older version
        "ai_watch", "sensitive:bob@example.com", "Sensitive data to AI: bob@example.com",
        ref_id="sensitive:bob@example.com:2026-11-04", people=["bob@example.com"],
    )  # fmt: skip
    _at(monkeypatch, NOW.replace(day=5))
    _start(tmp_path)
    assert len(backups(data)) == 2
    meta = data / "meta.sqlite"
    assert "{p:" in str(_rows(meta, "alert_items", "item_id")[bob.item_id])
    res = _run(meta)
    assert res.returncode == 0, res.stderr
    assert "alerts: 3; mutes: 1." in res.stdout
    items = _rows(meta, "alert_items", "item_id")
    assert items[bob.item_id]["ref_id"] == "sensitive:bob@example.com:2026-11-04"
    assert "{p:" not in str(items)
