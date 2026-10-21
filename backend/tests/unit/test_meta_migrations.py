"""Schema migrations are atomic and safe when two processes start at once."""

import multiprocessing
import sqlite3
from pathlib import Path

import pytest

from app.meta import db as metadb
from app.meta.db import MIGRATIONS, MetaDB


def _versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as con:
        return [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY 1")]


def _tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as con:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_database_gets_every_migration(tmp_path: Path) -> None:
    MetaDB(tmp_path / "meta.sqlite")
    assert _versions(tmp_path / "meta.sqlite") == list(range(1, len(MIGRATIONS) + 1))
    MetaDB(tmp_path / "meta.sqlite")  # a second start changes nothing
    assert _versions(tmp_path / "meta.sqlite") == list(range(1, len(MIGRATIONS) + 1))


def test_a_failing_migration_leaves_nothing_half_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "meta.sqlite"
    MetaDB(path)
    broken = "CREATE TABLE half_done (x INTEGER);\nCREATE TABLE half_done (y INTEGER);"
    monkeypatch.setattr(metadb, "MIGRATIONS", (*MIGRATIONS, broken))
    with pytest.raises(sqlite3.OperationalError):
        MetaDB(path)
    assert "half_done" not in _tables(path)
    assert len(MIGRATIONS) + 1 not in _versions(path)
    # Once fixed, the next start applies it cleanly.
    monkeypatch.setattr(metadb, "MIGRATIONS", (*MIGRATIONS, "CREATE TABLE half_done (x);"))
    MetaDB(path)
    assert "half_done" in _tables(path)


def _start(path: str) -> None:
    MetaDB(Path(path))


def test_two_processes_starting_together(tmp_path: Path) -> None:
    path = tmp_path / "meta.sqlite"
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_start, args=(str(path),)) for _ in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    assert [p.exitcode for p in procs] == [0, 0, 0]
    assert _versions(path) == list(range(1, len(MIGRATIONS) + 1))


def test_triggers_survive_statement_splitting(tmp_path: Path) -> None:
    path = tmp_path / "meta.sqlite"
    MetaDB(path)
    with sqlite3.connect(path) as con:
        con.execute(
            "INSERT INTO audit_log (ts, action, outcome, user_id, ip, detail)"
            " VALUES ('2026-10-13T00:00:00+00:00', 'x', 'success', NULL, NULL, '{}')"
        )
    with sqlite3.connect(path) as con, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM audit_log")


def test_source_kind_rebuild_keeps_rows_checkpoints_and_the_grant_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "meta.sqlite"
    before = MIGRATIONS[:27]  # an install from before OTLP sources
    monkeypatch.setattr(metadb, "MIGRATIONS", before)
    MetaDB(path)
    with sqlite3.connect(path) as con:
        con.execute(
            "INSERT INTO sources (source_id, format, path, glob, timezone, classification,"
            " retention_days, enabled, created_at, kind)"
            " VALUES ('fw', 'syslog', '/logs/fw', '*', 'UTC', 'local_only', 30, 1, 'x', 'file')"
        )
        con.execute(
            "INSERT INTO checkpoints (source_id, path, inode, offset, updated_at)"
            " VALUES ('fw', 'a.log', 1, 99, 'x')"
        )
        con.execute("INSERT INTO source_groups VALUES ('g1', 'Net', '', 'x')")
        con.execute("INSERT INTO group_sources VALUES ('g1', 'fw')")
    monkeypatch.setattr(metadb, "MIGRATIONS", MIGRATIONS)
    db = MetaDB(path)
    with db.connect() as con:
        assert con.execute("SELECT kind, path FROM sources").fetchall()[0][:] == (
            "file",
            "/logs/fw",
        )
        assert con.execute("SELECT offset FROM checkpoints").fetchone()[0] == 99
        con.execute(
            "INSERT INTO sources (source_id, format, path, glob, timezone, classification,"
            " retention_days, enabled, created_at, kind)"
            " VALUES ('cc', 'json', '', '*', 'UTC', 'local_only', 30, 1, 'x', 'otlp')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE sources SET kind = 'bogus' WHERE source_id = 'cc'")
    with db.connect() as con:
        con.execute("DELETE FROM sources WHERE source_id = 'fw'")
        # The grant trigger survived the rebuild, and checkpoints still cascade.
        assert con.execute("SELECT count(*) FROM group_sources").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0
