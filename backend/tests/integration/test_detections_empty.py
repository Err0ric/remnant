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
