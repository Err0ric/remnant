"""ADR-0038 section 9: a person's timeline across sources and forms of the name, each row
opening its own events."""

from datetime import UTC, datetime
from pathlib import Path

from app.ingest.writer import LakeWriter
from app.search.identity import IdentityMap
from app.search.timeline import timeline
from tests.integration.test_agents_overview import _hook
from tests.integration.test_around_event import _signin
from tests.integration.test_m365_consents import _write
from tests.integration.test_schedules import make_lab

START, END = datetime(2026, 10, 20, tzinfo=UTC), datetime(2026, 10, 30, tzinfo=UTC)


def test_timeline_joins_forms_and_counts_m365_once(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    engine = lab["app"].state.engine
    _write(engine, [])  # erin's blocked consent and admin's granted one, from both feeds
    LakeWriter(engine._lake).write(
        [
            _signin("m365_signin", "2026-10-29T09:58:00Z", "Erin@example.com", 50126),
            _signin("m365_signin", "2026-10-29T09:59:00Z", "EXAMPLE\\erin", 50126),
            _signin("m365_signin", "2026-10-29T10:30:00Z", "bob@example.com"),
            _hook("claude_hooks.pre_tool_use", "s-1", "2026-10-29T11:00:00+00:00"),
        ]
    )
    ident = IdentityMap(domains=["example.com"])
    t = timeline(engine, None, ident, [], "erin@example.com", START, END)
    assert t.person == "erin"
    assert {"Erin@example.com", "EXAMPLE\\erin"} <= set(t.forms)
    kinds = [r.kind for r in t.rows]
    failed = [r for r in t.rows if r.kind == "signin"]
    assert len(failed) == 1 and failed[0].count == 2 and failed[0].tone == "warn"
    assert failed[0].title.startswith("Failed to ")
    consents = [r for r in t.rows if r.kind == "consent"]
    assert len(consents) == 1 and consents[0].title.startswith("Consent blocked")
    assert "bob" not in " ".join(r.title for r in t.rows)
    assert all(r.sql and "{from}" in r.sql for r in t.rows if r.kind != "ai_first")
    assert [r.start for r in t.rows] == sorted((r.start for r in t.rows), reverse=True)
    assert "session" not in kinds  # the hook row names no person
    res = lab["admin"].get("/api/people/erin@example.com/timeline", params={"days": 30})
    assert res.status_code == 200
