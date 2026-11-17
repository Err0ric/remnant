"""Dashboard > Detections with no rules enabled (ADR-0052, DESIGN.md 6.3): the sections
answer says so, so the page can offer Enable rules where it would otherwise show nothing."""

from pathlib import Path
from typing import Any

from tests.integration.test_schedules import WIN_ID, make_lab


def sections(client: Any) -> dict[str, Any]:
    res = client.get("/api/dashboard/sections?window=7d&part=detections")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_no_rules_enabled_is_said_and_only_then(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    # The lab enables one rule: the section is there, or would be once it matches.
    assert sections(admin)["no_rules"] is False
    off = admin.post("/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=h)
    assert off.status_code == 200, off.text
    got = sections(admin)
    assert got["detections"] is None and got["no_rules"] is True
    # Another part of the page does not carry the answer.
    other = admin.get("/api/dashboard/sections?window=7d&part=identity").json()
    assert other["no_rules"] is False


def test_someone_with_no_readable_source_is_not_told(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    off = admin.post("/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=h)
    assert off.status_code == 200, off.text
    # ana reads one source through her group: the answer says no rule is enabled.
    assert sections(lab["ana"])["no_rules"] is True
    # With no source left there is nothing rules could run on, so nothing is said.
    gid = lab["gid"]
    res = admin.put(f"/api/groups/{gid}/sources", json={"source_ids": []}, headers=h)
    assert res.status_code == 200, res.text
    got = sections(lab["ana"])
    assert got["detections"] is None and got["no_rules"] is False


def test_the_overview_says_what_the_dashboard_draws_before_its_sections(tmp_path: Path) -> None:
    """Fix list 2026-11-16 item 27: the Overview, one of the Dashboard's quick reads, says
    whether any rule is enabled and whether a company egress is listed, so Detections' empty
    state and Attacks and access's note are drawn from the first paint, not moved in later."""
    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    first = admin.get("/api/overview").json()
    assert first["rules_enabled"] == 1 and first["egress_listed"] is False
    # An analyst gets the same two settings, which name nothing.
    assert lab["ana"].get("/api/overview").json()["rules_enabled"] == 1
    off = admin.post("/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=h)
    assert off.status_code == 200, off.text
    places = {"approved_countries": [], "internal_networks": ["10.0.0.0/8", "203.0.113.9/32"]}
    assert admin.put("/api/enrichment/places", json=places, headers=h).status_code == 200
    now = admin.get("/api/overview").json()
    assert now["rules_enabled"] == 0 and now["egress_listed"] is True
    # No rule on and no match kept: nothing to read, as the sections answer says.
    assert now["rules_last_match"] is None and sections(admin)["no_rules"] is True


def test_with_no_rule_on_the_overview_names_the_newest_match_on_readable_sources(
    tmp_path: Path,
) -> None:
    """Matches kept from before the rules were turned off still show on the Dashboard, so
    the Overview gives the newest one (code review of PR 650): the page then waits for
    the section instead of saying no rule is enabled."""
    from app.search.dashboard import rules_state

    lab = make_lab(tmp_path)
    admin, h = lab["admin"], lab["h"]
    assert (
        admin.post(
            "/api/rules/enabled", json={"rule_ids": [WIN_ID], "enabled": False}, headers=h
        ).status_code
        == 200
    )
    meta = lab["app"].state.meta
    with meta.connect() as con:
        run = "00000000-0000-4000-8000-000000000001"
        con.execute(
            "INSERT INTO rule_runs (run_id, rule_id, sha256, started_by, started_at,"
            " range_start, range_end, status, match_count, matches_stored, elapsed_ms,"
            " sources_in_scope) SELECT ?, rule_id, sha256, 'test', '2026-11-16 10:05:00',"
            " '2026-11-16 09:00:00', '2026-11-16 10:05:00', 'ok', 1, 1, 1, '[]'"
            " FROM rule_versions LIMIT 1",
            (run,),
        )
        con.execute(
            "INSERT INTO rule_matches (run_id, event_id, event_time, source_id)"
            " VALUES (?, 'e1', '2026-11-16 10:00:00', 'win_dc')",
            (run,),
        )
    assert admin.get("/api/overview").json()["rules_last_match"] == "2026-11-16 10:00:00"
    # Only matches on sources the caller may read count.
    assert rules_state(meta, ["lin_auth"]) == (0, None)
    assert rules_state(meta, ["win_dc"]) == (0, "2026-11-16 10:00:00")
