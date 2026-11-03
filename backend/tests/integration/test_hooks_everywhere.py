"""Owner 2026-11-02 (first real hooks record on the test install): a person seen only through
the hooks plugin counts as Claude Code use everywhere (Agents, the header count, People, AI
usage); a session with no record for the idle time reads "Ended (no end event)"; and each
Claude user says whether the plugin, the network, or both saw them."""

from datetime import timedelta
from typing import Any

from app.ai.usage import PersonUse, seen_through
from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab, usage  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"


def _hook(event: str, session: str, minutes: int) -> dict[str, Any]:
    attr = {
        "event_name": event, "session_id": session, "claude_account_email": "erin@example.com",
        "os_user": "erin", "tool_name": "Bash",
    }  # fmt: skip
    when = (NOW - timedelta(minutes=minutes)).isoformat()
    return _row("claude_hooks", HOOK, "claude", time=when, event=event, attr=attr)


def _erin(lab: dict[str, Any], *rows: dict[str, Any]) -> None:  # noqa: F811
    LakeWriter(lab["app"].state.engine._lake).write(list(rows))


def test_a_hooks_only_person_counts_everywhere(lab: dict[str, Any]) -> None:  # noqa: F811
    # The owner's case: one manual SessionStart and nothing else.
    _erin(lab, _hook("claude_hooks.session_start", "h-1", 40))
    a = lab["admin"]
    agents = a.get("/api/ai/agents").json()
    assert any(r["agent"] == "cc|erin@example.com" for r in agents), agents
    body = usage(a)
    people = {p["person"]: p for p in body["people"]}
    assert "erin@example.com" in people, people
    erin = people["erin@example.com"]
    assert erin["sessions"] == 1 and erin["via"] == ["hooks"]
    assert erin["seen_through"] == "plugin"
    # The header counts plugin users; alice (telemetry) and erin (hooks) are both there.
    plugin_users = [p for p in body["people"] if p["seen_through"] != "network"]
    assert {p["person"] for p in plugin_users} >= {"alice@example.com", "erin@example.com"}
    assert body["claude_seen"]["plugin"] + body["claude_seen"]["both"] == len(plugin_users)


def test_hooks_calls_add_to_people_once(lab: dict[str, Any]) -> None:  # noqa: F811
    _erin(
        lab,
        _hook("claude_hooks.session_start", "h-2", 50),
        _hook("claude_hooks.pre_tool_use", "h-2", 49),
        _hook("claude_hooks.pre_tool_use", "h-2", 48),
        _hook("claude_hooks.post_tool_use_failure", "h-2", 47),
    )
    erin = next(p for p in usage(lab["admin"])["people"] if p["person"] == "erin@example.com")
    assert (erin["sessions"], erin["tool_calls"], erin["errors"]) == (1, 2, 1)


def test_a_quiet_session_reads_ended_with_no_end_event(lab: dict[str, Any]) -> None:  # noqa: F811
    _erin(
        lab,
        _hook("claude_hooks.session_start", "quiet", 300),
        _hook("claude_hooks.session_start", "done", 200),
        _hook("claude_hooks.session_end", "done", 190),
    )
    got = {s["session_id"]: s for s in lab["admin"].get("/api/ai/sessions?days=90").json()}
    # The clock is real time, weeks after the lab's records: no record for over 2 hours.
    assert got["quiet"]["state"] == "idle" and not got["quiet"]["stopped"]
    assert got["done"]["state"] == "ended"


def test_seen_through_marks_plugin_network_and_both() -> None:
    def person(name: str) -> PersonUse:
        return PersonUse(name, 0.0, 0, 1, 0, 0, 0, [])

    people = [person("alice@example.com"), person("erin@example.com")]
    out, counts = seen_through(people, ["ALICE@example.com", "dana@example.com"])
    by = {p.person: p.seen_through for p in out}
    assert by == {
        "alice@example.com": "both",
        "erin@example.com": "plugin",
        "dana@example.com": "network",
    }
    assert counts == {"both": 1, "plugin": 1, "network": 1}
    dana = next(p for p in out if p.person == "dana@example.com")
    assert (dana.sessions, dana.tool_calls, dana.tokens) == (0, 0, 0)
