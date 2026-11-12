"""The query connection cannot write, even with the SQL guard bypassed (T2, ADR-0047).

Logs SQL, Search, saved searches, Ask, and MCP all run through `QueryEngine.run`, which
opens its connection with `_connect`. Two layers are proven here apart from the guard:
the connection itself (exact files only, external access off, configuration locked), and
the engine's statement check with DuckDB's own parser (one SELECT, nothing else).
"""

import hashlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

import app.engine.duckdb as engine_mod
from app.core.errors import QueryFailedError, QueryRejectedError
from app.engine.duckdb import QueryEngine, QueryScope
from app.engine.guard import GuardedQuery
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SCOPE = QueryScope(sources=["linux_auth"])


def _load(lake: Path, source: str, data: bytes) -> None:
    n = Normalizer(SourceSpec(source_id=source, format="syslog"), clock=lambda: NOW)
    rows = [r for f in Framer().frames([data]) if (r := n.normalize(decode_frame(f)))]
    LakeWriter(lake).write(rows)


def _rollup_file(root: Path, source: str) -> Path:
    path = root / f"source={source}" / "day=2026-10-09" / "part-1.parquet"
    path.parent.mkdir(parents=True)
    duckdb.connect().execute(
        f"COPY (SELECT TIMESTAMPTZ '2026-10-09 20:00:00+00' AS t, 3 AS n) TO '{path}'"
    )
    return path


@pytest.fixture
def eng(tmp_path: Path) -> QueryEngine:
    lake = tmp_path / "lake"
    _load(
        lake, "linux_auth", b"<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for alice\n"
    )
    _load(lake, "hr_vpn", b"<38>Oct  9 22:00:00 vpn01 vpnd[1]: user login bob\n")
    _rollup_file(tmp_path / "rollup" / "ai", "linux_auth")
    _rollup_file(tmp_path / "rollup" / "m365", "linux_auth")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.txt").write_text("do not read")
    (tmp_path / "spill").mkdir()
    return QueryEngine(
        lake,
        rollup_dir=tmp_path / "rollup" / "ai",
        m365_rollup_dir=tmp_path / "rollup" / "m365",
        temp_dir=tmp_path / "spill",  # as the server passes it (F46)
    )


def _digest(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _attempts(tmp: Path) -> dict[str, str]:
    lake_file = next((tmp / "lake" / "source=linux_auth").rglob("part-*.parquet"))
    rollup_file = next((tmp / "rollup" / "ai").rglob("part-*.parquet"))
    day = lake_file.parent
    return {
        "copy_new_lake": f"COPY (SELECT 1 AS x) TO '{day / 'x.parquet'}'",
        "copy_new_lake_root": f"COPY (SELECT 1 AS x) TO '{tmp / 'lake' / 'x.parquet'}'",
        "copy_new_rollup": f"COPY (SELECT 1 AS x) TO '{rollup_file.parent / 'x.parquet'}'",
        "copy_outside": f"COPY (SELECT 1 AS x) TO '{tmp / 'outside' / 'x.csv'}'",
        "copy_spill": f"COPY (SELECT 1 AS x) TO '{tmp / 'spill' / 'x.csv'}'",
        "copy_over_lake": f"COPY (SELECT 1 AS x) TO '{lake_file}'",
        "copy_over_rollup": f"COPY (SELECT 1 AS x) TO '{rollup_file}'",
        "export": f"EXPORT DATABASE '{tmp / 'outside' / 'dump'}'",
        "install": "INSTALL httpfs",
        "load_named": "LOAD httpfs",
        "load_file": f"LOAD '{tmp / 'outside' / 'x.duckdb_extension'}'",
        "attach_file": f"ATTACH '{tmp / 'outside' / 'x.db'}' AS x",
        "set_access": "SET enable_external_access = true",
        "set_paths": f"SET allowed_directories = ['{tmp}']",
        "set_autoload": "SET autoload_known_extensions = true",
        "reset_lock": "RESET lock_configuration",
        "read_outside": "SELECT * FROM read_text('/etc/hostname')",
        "read_outside_csv": f"SELECT * FROM read_csv('{tmp / 'outside' / 'secret.txt'}')",
        "read_other_source": (
            f"SELECT * FROM read_parquet('{tmp / 'lake' / 'source=hr_vpn' / '**' / '*.parquet'}')"
        ),
        "read_lake_glob": f"SELECT * FROM read_parquet('{tmp / 'lake' / '**' / '*.parquet'}')",
        "list_files": f"SELECT * FROM glob('{tmp}/**')",
    }


# Writes the connection alone also refuses; the rest are refused by the engine's statement
# check (DuckDB has no per-file read-only switch, ADR-0047).
ENGINE_ONLY = {
    "create_table": "CREATE TABLE t AS SELECT 1 AS x",
    "create_temp": "CREATE TEMP TABLE t AS SELECT 1 AS x",
    "replace_view": "CREATE OR REPLACE VIEW events AS SELECT 1 AS x",
    "drop_view": "DROP VIEW events",
    "attach_memory": "ATTACH ':memory:' AS m",
    # PRAGMA database_list and SHOW TABLES are rewritten by DuckDB into a SELECT and read
    # metadata only; the pragmas below act and are refused.
    "pragma": "PRAGMA force_checkpoint",
    "pragma_profiling": "PRAGMA enable_profiling",
    "pragma_set": "PRAGMA threads = 64",
    "checkpoint": "CHECKPOINT",
    "vacuum": "VACUUM",
    "call": "CALL pragma_version()",
    "two_statements": "SELECT 1; SELECT 2",
}


# Left to the statement check on the raw connection (ADR-0047): DuckDB allows its own
# spill folder, and a COPY with USE_TMP_FILE false can overwrite a listed file.
RAW_OPEN = {"copy_spill", "copy_over_lake_no_tmp"}


def _all_attempts(tmp: Path) -> dict[str, str]:
    lake_file = next((tmp / "lake" / "source=linux_auth").rglob("part-*.parquet"))
    return (
        _attempts(tmp)
        | ENGINE_ONLY
        | {"copy_over_lake_no_tmp": f"COPY (SELECT 1 AS x) TO '{lake_file}' (USE_TMP_FILE false)"}
    )


def test_connection_refuses_files_extensions_and_settings(eng: QueryEngine, tmp_path: Path) -> None:
    before = _digest(tmp_path)
    con = eng._connect(SCOPE, rollup=True)  # the connection every query surface gets
    try:
        for name, sql in _attempts(tmp_path).items():
            if name in RAW_OPEN:
                continue
            with pytest.raises(duckdb.Error):
                con.execute(sql).fetchall()
                pytest.fail(f"{name} ran on the raw connection")
        # An existing listed file: the default COPY writes a temporary file beside it first.
        with pytest.raises(duckdb.Error, match=r"(?i)permission"):
            con.execute(_attempts(tmp_path)["copy_over_lake"]).fetchall()
        assert con.execute("SELECT count(*) FROM events").fetchone() == (1,)
    finally:
        con.close()
    assert _digest(tmp_path) == before


def _names() -> list[str]:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        part = root / "lake" / "source=linux_auth" / "day=x" / "part-1.parquet"
        part.parent.mkdir(parents=True)
        part.touch()
        (root / "rollup" / "ai" / "r").mkdir(parents=True)
        (root / "rollup" / "ai" / "r" / "part-1.parquet").touch()
        return sorted(_all_attempts(root))


@pytest.mark.parametrize("name", _names())
def test_engine_refuses_writes_with_the_guard_bypassed(
    eng: QueryEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    sql = _all_attempts(tmp_path)[name]
    monkeypatch.setattr(engine_mod, "guard", lambda sql, *a, **k: GuardedQuery(sql, None))
    before = _digest(tmp_path)
    with pytest.raises((QueryRejectedError, QueryFailedError)):
        eng.run(sql, SCOPE, rollup=True)
    assert _digest(tmp_path) == before


def test_lake_and_rollups_still_read(eng: QueryEngine) -> None:
    assert eng.run("SELECT count(*) FROM events", SCOPE).rows == [[1]]
    assert eng.run("SELECT sum(n) FROM ai_rollup", SCOPE, rollup=True).rows == [[3]]
    assert eng.run("SELECT sum(n) FROM m365_rollup", SCOPE, rollup=True).rows == [[3]]
    other = QueryScope(sources=["hr_vpn"])
    assert eng.run("SELECT count(*) FROM events", other).rows == [[1]]
    assert eng.run("SELECT count(*) FROM ai_rollup", other, rollup=True).rows == [[0]]


def test_allowed_paths_are_the_view_files_only(eng: QueryEngine, tmp_path: Path) -> None:
    """No folder is allowed but DuckDB's own spill folder, which it adds itself (outside the
    lake, emptied at every start; a COPY there is refused by the statement check)."""
    con = eng._connect(SCOPE, rollup=True)
    try:
        listed = {
            os.path.realpath(p.strip("'"))
            for (v,) in con.execute("SELECT value FROM duckdb_settings() WHERE name = 'allowed_paths'").fetchall()
            for p in v.strip("[]").split(", ")
            if p
        }  # fmt: skip
        dirs, spill = (
            con.execute("SELECT value FROM duckdb_settings() WHERE name = $n", {"n": n}).fetchone()[
                0
            ]  # type: ignore[index]  # the setting always exists
            for n in ("allowed_directories", "temp_directory")
        )
    finally:
        con.close()
    allowed = dirs.strip("[]").rstrip("/")
    assert allowed == "" or os.path.realpath(allowed) == os.path.realpath(spill)
    assert listed and all(Path(p).is_file() and p.endswith(".parquet") for p in listed)
    assert not any("source=hr_vpn" in p for p in listed)


def test_lock_costs_no_noticeable_latency(eng: QueryEngine) -> None:
    """Median of a small query, connection included; the lock is a few SET statements and
    one extra parse. A hang guard only: every page in the speed check (scripts/
    bench_compare.py) runs on a locked connection, so real latency is measured there."""
    eng.run("SELECT count(*) FROM events", SCOPE)
    times = []
    for _ in range(15):
        t = time.perf_counter()
        eng.run("SELECT count(*) FROM events", SCOPE, rollup=True)
        times.append(time.perf_counter() - t)
    assert sorted(times)[len(times) // 2] < 5.0
