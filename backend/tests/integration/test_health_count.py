"""The rail's Health dot (ADR-0052 section 3.2): `/api/health/count` says how many of the
viewer's own sources are not healthy, as numbers only. It names no source and writes no
audit row, like the alert count (owner, 2026-11-11: the audit log records access, not page
loads), and it agrees with the Overview the Health page reads."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.search.source_state import needing_attention, problem
from tests.integration.test_quiet_sources import lab, tick, watch  # noqa: F401  # fixture
from tests.integration.test_schedules import NOW


def _audit_rows(env: dict[str, Any], action: str | None = None) -> int:
    where, args = ("WHERE action = ?", (action,)) if action else ("", ())
    with env["app"].state.meta.connect() as con:
        return int(
            con.execute(f"SELECT count(*) FROM audit_log {where}", args).fetchone()[0]
        )  # fixed text


def _forget(env: dict[str, Any]) -> None:
    """Both caches empty: the next read of either kind is a fresh one."""
    env["app"].state.overview._cache = {}
    env["app"].state.overview._count_cache = {}


def _count(env: dict[str, Any], who: str = "admin") -> dict[str, Any]:
    res = env[who].get("/api/health/count")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_it_counts_the_sources_that_are_not_healthy_and_agrees_with_the_overview(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    calm = _count(lab)
    assert set(calm) == {"total", "not_healthy", "unhealthy", "damaged_files"}  # numbers only
    summary = lab["admin"].get("/api/overview").json()["source_summary"]
    rows = lab["admin"].get("/api/overview").json()["sources"]
    assert calm == {
        "total": summary["total"],
        "not_healthy": sum(1 for r in rows if r["condition"] not in ("healthy", "paused")),
        "unhealthy": sum(1 for r in rows if r["problem"] == "unhealthy"),
        "damaged_files": 0,
    }

    # A source goes quiet past its threshold: its gap alert opens and Health needs a look.
    assert watch(lab, "lin_auth").status_code == 200
    lab["clock"].now = NOW + timedelta(hours=2)
    tick(lab)
    _forget(lab)
    after = _count(lab)
    rows = lab["admin"].get("/api/overview").json()["sources"]
    assert after["not_healthy"] == sum(
        1 for r in rows if r["condition"] not in ("healthy", "paused")
    )
    assert after["not_healthy"] >= 1  # the quiet source is one of them
    # One rule (fix list 2026-11-16 item 12): every source the count counts carries its
    # problem, and the count's unhealthy is the rows' (each case built on purpose in
    # test_quiet_ok.py, test_the_dot_is_red_only_for_what_health_draws_red).
    assert after["not_healthy"] == sum(1 for r in rows if r["problem"])
    lin = next(r for r in rows if r["source_id"] == "lin_auth")
    assert lin["condition"] == "quiet" and lin["quiet_since"] and lin["problem"]
    assert after["unhealthy"] == sum(1 for r in rows if r["problem"] == "unhealthy")


def test_a_source_paused_on_purpose_is_not_something_wrong(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    assert needing_attention(["healthy", "paused", "paused"]) == 0
    assert needing_attention(["healthy", "paused", "quiet", "error", "gap", "attention"]) == 4
    assert [problem(c, True, True) for c in ("healthy", "paused", "gap", "attention")] == [
        None,
        None,
        "attention",
        "attention",
    ]
    assert problem("error", False, False) == "unhealthy"
    # Red on Health only with gap hours on the chart: a source only quiet is drawn greyed.
    assert problem("quiet", True, True) == "unhealthy"
    assert problem("quiet", True, False) == "attention"
    assert problem("quiet", False, True) == "attention"

    # Through the endpoint: pausing a source that counted takes it out of the count, and it
    # stays one of the viewer's sources.
    before = _count(lab)
    rows = {r["source_id"]: r for r in lab["admin"].get("/api/overview").json()["sources"]}
    assert rows["win_dc"]["condition"] not in ("healthy", "paused")
    with lab["app"].state.meta.connect() as con:
        con.execute("UPDATE sources SET enabled = 0 WHERE source_id = 'win_dc'")
    _forget(lab)
    after = _count(lab)
    rows = {r["source_id"]: r for r in lab["admin"].get("/api/overview").json()["sources"]}
    assert rows["win_dc"]["condition"] == "paused"
    assert (after["total"], after["not_healthy"]) == (before["total"], before["not_healthy"] - 1)
    assert rows["win_dc"]["problem"] is None


def test_it_counts_only_the_sources_the_viewer_may_read(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    everything = _count(lab)
    hers = _count(lab, "ana")  # Ana reads the Linux source only
    assert hers["total"] < everything["total"]
    assert hers["total"] == lab["ana"].get("/api/overview").json()["source_summary"]["total"]


def test_it_writes_no_audit_row_and_never_hides_the_overview_row(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    """Review of #554: the count must not fill the cache the Overview reads, or a Health
    page opened within a minute of it would come from that cache and write no
    `overview.view` row (CLAUDE.md 2.14)."""
    _forget(lab)
    before = _audit_rows(lab)
    for _ in range(3):
        _count(lab)  # the first computes, the others are its own cached answer
    assert _audit_rows(lab) == before

    # The Overview read after a count is still a first read, and is recorded.
    seen = _audit_rows(lab, "overview.view")
    assert lab["admin"].get("/api/overview").status_code == 200
    assert _audit_rows(lab, "overview.view") == seen + 1

    # And the count may use what the Overview just computed, without building again.
    built = []
    real = lab["app"].state.overview._build
    lab["app"].state.overview._build = lambda *a: built.append(1) or real(*a)
    lab["app"].state.overview._count_cache = {}
    _count(lab)
    assert built == []


@pytest.mark.real_auth
def test_it_needs_a_sign_in(lab: dict[str, Any]) -> None:  # noqa: F811
    stranger = TestClient(lab["app"])
    assert stranger.get("/api/health/count").status_code == 401


def test_damaged_files_count_on_the_overview_and_the_count_alike(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    """Review of 637: the damaged-files notice is a problem on Health's Sources tab, so the
    rail's dot must see it too; both read the one number here."""
    folder = lab["app"].state.lake_dir.parent / "quarantine" / "lin_auth" / "2026-11-01"
    folder.mkdir(parents=True)
    (folder / "part-0.parquet").write_bytes(b"damaged")
    _forget(lab)
    assert _count(lab)["damaged_files"] == 1
    assert lab["admin"].get("/api/overview").json()["damaged_files"] == 1


def test_the_sources_listing_has_no_status_of_its_own_only_the_readers_fact(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    """Fix list 2026-11-16 item 19: Settings > Sources showed the reader's "reading" as a
    green status while Health said quiet. The one status is the Overview's condition; the
    listing carries the reader's own state only, which stays "reading" for a quiet file."""
    assert watch(lab, "lin_auth").status_code == 200
    lab["clock"].now = NOW + timedelta(hours=2)
    tick(lab)
    _forget(lab)
    listed = {s["source_id"]: s for s in lab["admin"].get("/api/sources").json()}
    judged = {s["source_id"]: s for s in lab["admin"].get("/api/overview").json()["sources"]}
    assert set(listed) == set(judged)  # every source the page lists has the one state
    assert listed["lin_auth"]["status"]["state"] == "reading"  # still following the file
    assert judged["lin_auth"]["condition"] == "quiet"  # what both pages say
    for s in listed.values():
        assert "condition" not in s and "condition" not in s["status"]
        assert "problem" not in s["status"]
