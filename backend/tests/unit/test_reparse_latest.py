"""The source list reads each source's latest reparse job with one indexed query, never the
whole `reparse_jobs` table (review of #503, CLAUDE.md section 9 rule 1)."""

from pathlib import Path

from app.ingest import reparse
from app.meta.db import MetaDB


def add(meta: MetaDB, job_id: str, source_id: str, started_at: str) -> None:
    with meta.connect() as con:
        con.execute(
            "INSERT INTO reparse_jobs (job_id, source_id, template_id, state, started_at)"
            " VALUES (?, ?, 'linux_sshd', 'done', ?)",
            (job_id, source_id, started_at),
        )


def test_each_sources_latest_job(tmp_path: Path) -> None:
    meta = MetaDB(tmp_path / "meta.sqlite")
    add(meta, "a1", "alpha", "2026-10-01T00:00:00+00:00")
    add(meta, "a2", "alpha", "2026-10-03T00:00:00+00:00")
    add(meta, "a3", "alpha", "2026-10-02T00:00:00+00:00")
    add(meta, "b1", "beta", "2026-10-01T00:00:00+00:00")
    add(meta, "b2", "beta", "2026-10-01T00:00:00+00:00")  # same start: the later row wins
    add(meta, "g1", "gamma", "2026-10-05T00:00:00+00:00")  # not asked for
    got = reparse.latest_jobs(meta, ["alpha", "beta", "delta"])
    assert {k: v.job_id for k, v in got.items()} == {"alpha": "a2", "beta": "b2"}
    assert reparse.latest_jobs(meta, []) == {}


def test_the_query_reads_the_source_index_not_the_table(tmp_path: Path) -> None:
    meta = MetaDB(tmp_path / "meta.sqlite")
    sql, args = reparse.latest_jobs_query(["alpha", "beta"])
    with meta.connect() as con:
        plan = [r["detail"] for r in con.execute(f"EXPLAIN QUERY PLAN {sql}", args)]
    assert any("reparse_jobs_source" in d for d in plan), plan
    assert not any(d.startswith("SCAN") and "reparse_jobs" in d for d in plan), plan


def test_a_partial_rule_re_run_stays_shown_over_a_newer_job(tmp_path: Path) -> None:
    """Review of #503: a newer reparse must not hide "Run the remaining rules" of an older
    job whose rule re-run is partial (its failed rules would never run)."""
    meta = MetaDB(tmp_path / "meta.sqlite")
    add(meta, "p1", "alpha", "2026-10-01T00:00:00+00:00")
    add(meta, "p2", "alpha", "2026-10-02T00:00:00+00:00")
    with meta.connect() as con:
        con.execute("UPDATE reparse_jobs SET rules_state = 'partial' WHERE job_id = 'p1'")
    assert reparse.latest_jobs(meta, ["alpha"])["alpha"].job_id == "p1"
    with meta.connect() as con:
        con.execute("UPDATE reparse_jobs SET rules_state = 'done' WHERE job_id = 'p1'")
    assert reparse.latest_jobs(meta, ["alpha"])["alpha"].job_id == "p2"
