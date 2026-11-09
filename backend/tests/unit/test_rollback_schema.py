"""Rolling back: an older version starts on a database a newer version migrated.

Migrations are additive only (CLAUDE.md rule 9), so the older migration set finds every
version it knows already applied and the newer ones unknown. It must start, change
nothing, and say so without data values; rolling forward again applies nothing twice.
The test uses the current migration set with its last scripts cut off, which is exactly
an older release's set (scripts are never edited or reordered)."""

import sqlite3
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.ingest import sources as sources_mod
from app.ingest.connectors.proxmox import ProxmoxSettings
from app.ingest.sources import SourceConfig, SourceStore
from app.meta import db as metadb
from app.meta.db import MIGRATIONS, MetaDB

OLDER = 3  # the older release knows all but the last three migrations


def _dump(path: Path) -> tuple[list[int], list[tuple[str, str]]]:
    with sqlite3.connect(path) as con:
        versions = [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY 1")]
        schema = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        ).fetchall()
    return versions, schema


def test_older_migrations_start_on_a_newer_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "meta.sqlite"
    MetaDB(path)  # the newer version migrated it
    before = _dump(path)
    monkeypatch.setattr(metadb, "MIGRATIONS", MIGRATIONS[:-OLDER])
    with capture_logs() as logs:
        db = MetaDB(path)  # the older version starts
    assert _dump(path) == before  # nothing dropped, rewritten, or re-applied
    newer = [e for e in logs if e["event"] == "meta.schema_newer"]
    assert newer == [
        {
            "event": "meta.schema_newer",
            "log_level": "warning",
            "known": len(MIGRATIONS) - OLDER,
            "database": len(MIGRATIONS),
            "newer": OLDER,
        }
    ]
    with db.connect() as con:  # and it works: reads and writes go through
        con.execute("INSERT INTO audit_log (ts, action, outcome) VALUES ('t', 'x', 'success')")
    monkeypatch.setattr(metadb, "MIGRATIONS", MIGRATIONS)
    with capture_logs() as logs:
        MetaDB(path)  # rolled forward
    assert _dump(path) == before
    assert not [e for e in logs if e["event"] == "meta.schema_newer"]


def test_a_current_database_logs_no_warning(tmp_path: Path) -> None:
    MetaDB(tmp_path / "meta.sqlite")
    with capture_logs() as logs:
        MetaDB(tmp_path / "meta.sqlite")
    assert not [e for e in logs if e["event"] == "meta.schema_newer"]


def test_a_source_of_a_kind_this_version_does_not_know_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found on rollback (2026-11-08): a version that did not know a newer source kind
    failed to list sources at all, which stopped ingest for every source. Now the row
    is skipped with a warning, kept in the database, and still counted for retention and
    watches, so its data is neither ingested wrongly nor aged out early."""
    roots = [tmp_path]
    store = SourceStore(MetaDB(tmp_path / "meta.sqlite"), roots)
    (tmp_path / "a.log").write_text("x\n")
    store.add(
        SourceConfig(
            source_id="files", format="json", path=str(tmp_path / "a.log"), retention_days=90
        )
    )
    settings = ProxmoxSettings(host="pve1.example.internal", token_id="remnant@pve!inventory")
    store.add(
        SourceConfig(
            source_id="later", kind="proxmox", format="json", proxmox=settings,
            retention_days=365,
        )
    )  # fmt: skip
    monkeypatch.setattr(
        sources_mod, "KNOWN_KINDS", sources_mod.KNOWN_KINDS - {"proxmox"}
    )  # this version predates the kind
    with capture_logs() as logs:
        listed = store.list()
    assert [s.source_id for s in listed] == ["files"]
    assert [e for e in logs if e["event"] == "sources.unknown_kind_skipped"] == [
        {"event": "sources.unknown_kind_skipped", "log_level": "warning", "count": 1}
    ]
    assert store.retention_days() == {"files": 90, "later": 365}
    assert store.ids() == {"files", "later"}
    monkeypatch.undo()  # rolled forward: the source is back as it was
    assert [s.source_id for s in store.list()] == ["files", "later"]
