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
