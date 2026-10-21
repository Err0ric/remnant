"""Read-only query engine over the lake: scoping, sandbox, limits, timeout."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.errors import QueryRejectedError, QueryTimeoutError
from app.engine.duckdb import QueryEngine, QueryScope
from app.ingest.framer import Framer
from app.ingest.normalizer import Normalizer, SourceSpec
from app.ingest.records import decode_frame
from app.ingest.writer import LakeWriter

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def load(lake: Path, source: str, data: bytes) -> None:
    n = Normalizer(SourceSpec(source_id=source, format="syslog"), clock=lambda: NOW)
    rows = [r for f in Framer().frames([data]) if (r := n.normalize(decode_frame(f)))]
    LakeWriter(lake).write(rows)


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    lake = tmp_path / "lake"
    load(
        lake,
        "linux_auth",
        b"<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for jordan\n"
        b"<38>Oct  9 21:00:00 bastion sshd[2]: Failed password for admin\n"
        b"<38>Oct 10 09:00:00 bastion sshd[3]: Accepted publickey for kelly\n",
    )
    load(lake, "hr_vpn", b"<38>Oct  9 22:00:00 vpn01 vpnd[1]: payroll user login\n")
    (tmp_path / "secret.txt").write_text("do not read")
    return lake


def engine(lake: Path, **kw: float) -> QueryEngine:
    return QueryEngine(lake, **kw)  # type: ignore[arg-type]  # test passthrough


def test_counts_all_permitted_sources(lake: Path) -> None:
    res = engine(lake).run("SELECT count(*) AS n FROM events", QueryScope(sources=None))
    assert res.columns == ["n"]
    assert res.rows == [[4]]


def test_scope_hides_other_sources(lake: Path) -> None:
    res = engine(lake).run(
        "SELECT DISTINCT source_id FROM events", QueryScope(sources=["linux_auth"])
    )
    assert res.rows == [["linux_auth"]]


def test_scope_with_no_sources_sees_nothing(lake: Path) -> None:
    res = engine(lake).run("SELECT count(*) FROM events", QueryScope(sources=[]))
    assert res.rows == [[0]]


def test_time_range_filters_view(lake: Path) -> None:
    scope = QueryScope(
        sources=None,
        start=datetime(2026, 10, 9, 20, 30, tzinfo=UTC),
        end=datetime(2026, 10, 9, 21, 30, tzinfo=UTC),
    )
    res = engine(lake).run("SELECT count(*) FROM events", scope)
    assert res.rows == [[2]]


def test_cannot_read_restricted_source_files_directly(lake: Path) -> None:
    hr_glob = str(lake / "source=hr_vpn" / "**" / "*.parquet")
    with pytest.raises(QueryRejectedError):
        engine(lake).run(
            f"SELECT * FROM read_parquet('{hr_glob}')", QueryScope(sources=["linux_auth"])
        )


def test_sandbox_blocks_files_even_if_guard_were_bypassed(lake: Path) -> None:
    eng = engine(lake)
    con = eng._connect(QueryScope(sources=["linux_auth"]))  # internal: prove defense in depth
    with pytest.raises(Exception, match=r"(?i)permission"):
        con.execute(f"SELECT * FROM read_csv('{lake.parent / 'secret.txt'}')").fetchall()
    with pytest.raises(Exception, match=r"(?i)permission"):
        con.execute(
            f"SELECT * FROM read_parquet('{lake / 'source=hr_vpn' / '**' / '*.parquet'}')"
        ).fetchall()
    with pytest.raises(Exception):  # noqa: B017  # any error: config is locked
        con.execute("SET enable_external_access = true")


def test_default_limit_and_truncation_flag(lake: Path) -> None:
    res = engine(lake, default_limit=2).run("SELECT * FROM events", QueryScope(sources=None))
    assert len(res.rows) == 2
    assert res.truncated is True


def test_values_are_json_safe(lake: Path) -> None:
    res = engine(lake).run(
        "SELECT time, actor_process_pid, raw_bytes_invalid FROM events ORDER BY time LIMIT 1",
        QueryScope(sources=None),
    )
    assert res.rows == [["2026-10-09T20:41:12+00:00", 1, False]]
    assert res.executed_sql.upper().endswith("LIMIT 1")


def test_timeout_interrupts_long_query(lake: Path) -> None:
    with pytest.raises(QueryTimeoutError):
        engine(lake, timeout_s=0.2).run(
            "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 10000000000) "
            "SELECT count(*) FROM r",
            QueryScope(sources=None),
        )


def test_empty_lake_still_has_events_table(tmp_path: Path) -> None:
    res = engine(tmp_path / "missing").run("SELECT count(*) FROM events", QueryScope(sources=None))
    assert res.rows == [[0]]
