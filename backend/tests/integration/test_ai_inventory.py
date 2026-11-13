"""ADR-0038 section 7: one typed inventory of everything AI seen, with exclusions that
keep who and why, and audited exports for admins and analysts only."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.ingest.writer import LakeWriter
from app.meta.db import MetaDB
from tests.integration.test_agents_overview import _hook
from tests.integration.test_m365_consents import _write
from tests.integration.test_schedules import make_lab


def test_inventory_lists_types_excludes_and_exports(
    tmp_path: Path, pin_now: Callable[[datetime], None]
) -> None:
    pin_now(datetime(2026, 11, 1, 12, 0, tzinfo=UTC))  # after this file's event dates
    lab = make_lab(tmp_path)
    engine, admin, h = lab["app"].state.engine, lab["admin"], lab["h"]
    _write(engine, [])  # one granted and one blocked consent
    LakeWriter(engine._lake).write(
        [
            _hook(
                "claude_hooks.pre_tool_use", "s-9", "2026-10-29T11:00:00+00:00",
                tool_name="mcp__github__create_issue", mcp_server_name="github",
            )
        ]
    )  # fmt: skip
    got = admin.get("/api/ai/inventory?days=30").json()["items"]
    types = {(i["type"], i["name"]) for i in got}
    assert ("m365_app", "Lab Notes App") in types  # granted only; the blocked one is not
    assert ("mcp", "github") in types
    assert any(t == "agent" for t, _ in types)

    body = {"type": "mcp", "key": "github", "reason": "IT's own server"}
    assert admin.put("/api/ai/inventory/exclusions", json=body, headers=h).status_code == 200
    gh = next(i for i in admin.get("/api/ai/inventory").json()["items"] if i["key"] == "github")
    assert gh["excluded"]["by"] == "admin" and gh["excluded"]["reason"] == "IT's own server"

    res = admin.get("/api/ai/inventory/export?format=json&excluded=true")
    assert [i["key"] for i in json.loads(res.text)] == ["github"]
    csv = admin.get("/api/ai/inventory/export?format=csv&type=m365_app").text
    assert csv.splitlines()[0].startswith("type,name,status") and "Lab Notes App" in csv
    # The Status filter of the page (redesign row 10): the file is the view. Before the
    # exclusion github was unreviewed; excluded items carry their status too.
    by_status = admin.get("/api/ai/inventory/export?format=json&excluded=true&status=unreviewed")
    assert [i["key"] for i in json.loads(by_status.text)] == ["github"]
    none = admin.get("/api/ai/inventory/export?format=json&excluded=true&status=approved")
    assert json.loads(none.text) == []
    assert admin.get("/api/ai/inventory/export?status=loud").status_code == 422
    assert lab["aud"].get("/api/ai/inventory/export").status_code == 403
    assert lab["ana"].get("/api/ai/inventory/export").status_code == 200

    with MetaDB(lab["db"]).connect() as con:
        rows = con.execute(
            "SELECT detail FROM audit_log WHERE action = 'ai.inventory_export'"
        ).fetchall()
    assert len(rows) == 5
    assert json.loads(rows[0][0])["rows"] == 1
    assert json.loads(rows[2][0])["status"] == "unreviewed"
    assert json.loads(rows[0][0])["status"] is None

    gone = "/api/ai/inventory/exclusions?type=mcp&key=github"
    assert admin.delete(gone, headers=h).status_code == 204
    assert admin.delete(gone, headers=h).status_code == 404


def test_csv_cells_from_logs_cannot_be_formulas() -> None:
    from app.ai.inventory import Item, export

    row = Item("m365_app", "=HYPERLINK(1)", "=HYPERLINK(1)", None, 1, None, None, None, [])
    assert "'=HYPERLINK(1)" in export([row], "csv")
