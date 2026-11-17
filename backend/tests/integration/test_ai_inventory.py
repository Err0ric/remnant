"""ADR-0038 section 7: one typed inventory of everything AI seen, with exclusions that
keep who and why, and audited exports for admins and analysts only."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _rows(db: Path, action: str | None = None) -> int:
    where, args = ("WHERE action = ?", (action,)) if action else ("", ())
    with MetaDB(db).connect() as con:
        return int(con.execute(f"SELECT count(*) FROM audit_log {where}", args).fetchone()[0])


def _to_review(items: list[dict[str, object]]) -> int:
    return sum(1 for i in items if i["excluded"] is None and i["status"] == "unreviewed")


def test_the_rail_count_is_numbers_only_on_the_callers_sources_and_unaudited(
    tmp_path: Path, pin_now: Callable[[datetime], None]
) -> None:
    """D258: the rail's AI usage count, like `/health/count`: the Inventory's own "to
    review" number on the caller's sources, naming nothing, with no audit row; the
    Inventory read itself is still recorded."""
    pin_now(datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    lab = make_lab(tmp_path)
    engine, admin, ana = lab["app"].state.engine, lab["admin"], lab["ana"]
    _write(engine, [])
    LakeWriter(engine._lake).write(
        [
            _hook(
                "claude_hooks.pre_tool_use", "s-9", "2026-10-29T11:00:00+00:00",
                tool_name="mcp__github__create_issue", mcp_server_name="github",
            )
        ]
    )  # fmt: skip

    before = _rows(lab["db"])
    res = admin.get("/api/ai/inventory/count")
    assert res.status_code == 200
    assert set(res.json()) == {"to_review", "not_approved"}  # numbers only, no names
    assert _rows(lab["db"]) == before  # no audit row
    assert ana.get("/api/ai/inventory/count").json()["to_review"] >= 0
    assert _rows(lab["db"]) == before

    # The same number as the Inventory's header, read by each caller on their own sources.
    seen = _rows(lab["db"], "ai.view") + _rows(lab["db"], "ai.view_people")
    mine = _to_review(admin.get("/api/ai/inventory?days=30").json()["items"])
    assert mine >= 1 and res.json()["to_review"] == mine
    assert _rows(lab["db"], "ai.view") + _rows(lab["db"], "ai.view_people") == seen + 1
    hers = _to_review(ana.get("/api/ai/inventory?days=30").json()["items"])
    assert ana.get("/api/ai/inventory/count").json()["to_review"] == hers
    assert hers < mine  # ana reads the Linux source only

    # A review shows at once: any change empties the short cache the count keeps.
    body = {"type": "mcp", "key": "github", "reason": "IT's own server"}
    assert admin.put("/api/ai/inventory/exclusions", json=body, headers=lab["h"]).status_code == 200
    assert admin.get("/api/ai/inventory/count").json()["to_review"] == mine - 1


def test_one_to_review_number_for_every_place_and_every_caller(
    tmp_path: Path, pin_now: Callable[[datetime], None]
) -> None:
    """Owner, 2026-11-16: the Inventory's header, its Status = Unreviewed rows, the rail's
    count, and AI usage's Needs attention line state one number, from one server rule
    (`to_review`), on the caller's own sources, over the Inventory's 30 days."""
    from app.ai.inventory import to_review
    from tests.integration.test_agents_overview import HOOK
    from tests.integration.test_ai_rollup import _dns
    from tests.integration.test_m365_consents import _row

    pin_now(datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    lab = make_lab(tmp_path)
    engine, admin, ana, h = lab["app"].state.engine, lab["admin"], lab["ana"], lab["h"]
    at = datetime(2026, 10, 29, 11, 0, tzinfo=UTC)

    def mcp(source: str, name: str) -> dict[str, object]:
        a = {"event_name": "claude_hooks.pre_tool_use", "session_id": f"s-{name}",
             "tool_name": f"mcp__{name}__run", "mcp_server_name": name}  # fmt: skip
        return _row("claude_hooks", HOOK, source, time=at.isoformat(),
                    event="claude_hooks.pre_tool_use", attr=a)  # fmt: skip

    LakeWriter(engine._lake).write(
        [
            *_dns("lin_auth", at, 2, "chatgpt.com"),  # unreviewed service: ana reads it
            *_dns("lin_auth", at, 2, "claude.ai"),  # approved below
            *_dns("lin_auth", at, 2, "gemini.google.com"),  # not approved below
            *_dns("lin_auth", at, 2, "perplexity.ai"),  # unreviewed, excluded below
            *_dns("lin_auth", datetime(2026, 9, 20, 11, 0, tzinfo=UTC), 2, "mistral.ai"),  # too old
            *_dns("dns_a", at, 2, "deepseek.com"),  # unreviewed, a source ana cannot read
            mcp("lin_auth", "jira"),  # unreviewed MCP server: ana reads it
            mcp("lin_auth", "github"),  # approved below
        ]
    )  # fmt: skip
    for sid, st in (("claude", "approved"), ("gemini", "not_approved")):
        res = admin.put(f"/api/ai/services/{sid}/status", json={"status": st}, headers=h)
        assert res.status_code == 200
    res = admin.put(
        "/api/ai/mcp-rules", json={"pattern": "github", "status": "approved"}, headers=h
    )
    assert res.status_code == 200
    body = {"type": "service", "key": "perplexity", "reason": "Blocked at the proxy"}
    assert admin.put("/api/ai/inventory/exclusions", json=body, headers=h).status_code == 200

    def places(client: Any) -> dict[str, object]:
        inv = client.get("/api/ai/inventory?days=30").json()
        count = client.get("/api/ai/inventory/count").json()
        active = [i for i in inv["items"] if i["excluded"] is None]
        shown = [i for i in active if i["status"] == "unreviewed"]
        # Needs attention's other number: the same on every tab, from either answer.
        refused = {inv["not_approved"], count["not_approved"],
                   sum(1 for i in active if i["status"] == "not_approved")}  # fmt: skip
        assert len(refused) == 1
        return {
            "header": inv["to_review"],  # the header and Needs attention on the Inventory tab
            "rail": count["to_review"],  # the rail, and Needs attention on the other tabs
            "rows": len(shown),  # the table with Status = Unreviewed, and its count
            "names": sorted(i["key"] for i in shown),
        }

    assert places(admin) == {"header": 3, "rail": 3, "rows": 3,
                             "names": ["chatgpt", "deepseek", "jira"]}  # fmt: skip
    assert places(ana) == {"header": 2, "rail": 2, "rows": 2, "names": ["chatgpt", "jira"]}

    # A review changes every place at once, for every caller.
    assert admin.put("/api/ai/services/chatgpt/status", json={"status": "approved"},
                     headers=h).status_code == 200  # fmt: skip
    assert places(admin) == {"header": 2, "rail": 2, "rows": 2, "names": ["deepseek", "jira"]}
    assert places(ana) == {"header": 1, "rail": 1, "rows": 1, "names": ["jira"]}
    assert to_review([]) == 0
