"""D189 (owner, 2026-11-03): one person's AI activity on one page: accounts and devices,
AI services the network saw, sessions newest first with a one-line summary, rollups, and
flags. Metadata only."""

from datetime import timedelta
from typing import Any

from app.ai.accounts import accounts
from app.ai.person_ai import activity, first_word, outside
from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"
CALL, OK, FAIL = (
    "claude_hooks.pre_tool_use",
    "claude_hooks.post_tool_use",
    "claude_hooks.post_tool_use_failure",
)


def _h(event: str, session: str, minutes: int, **attr: Any) -> dict[str, Any]:
    a = {"event_name": event, "session_id": session, "claude_account_email": "erin@example.net",
         "os_user": "erin", "cwd": "/home/erin/app", **attr}  # fmt: skip
    when = (NOW - timedelta(minutes=minutes)).isoformat()
    return _row("claude_hooks", HOOK, "claude", time=when, event=event, attr=a)


def _activity(lab: dict[str, Any], person: str) -> Any:  # noqa: F811
    app = lab["app"]
    ident = app.state.identities.load()
    accts = accounts(app.state.engine, None, ["claude"], [], ident.domains, NOW, 30)
    cat = app.state.ai_catalog
    return activity(
        app.state.engine, None, ident, cat.domain_table(),
        {s.id: s.name for s in cat.services()}, accts.rows, person, NOW, 7,
    )  # fmt: skip


def test_one_persons_ai_activity(lab: dict[str, Any]) -> None:  # noqa: F811
    LakeWriter(lab["app"].state.engine._lake).write(
        [
            _h("claude_hooks.session_start", "s-1", 90),
            _h("claude_hooks.user_prompt_submit", "s-1", 89),
            _h(CALL, "s-1", 88, tool_name="Edit", path="/home/erin/app/main.py"),
            _h(OK, "s-1", 88, tool_name="Edit", path="/home/erin/app/main.py"),
            _h(CALL, "s-1", 87, tool_name="Write", path="/etc/hosts"),  # outside the folder
            _h(FAIL, "s-1", 87, tool_name="Write", path="/etc/hosts"),
            _h(CALL, "s-1", 86, tool_name="Bash", program="git status"),
            _h(CALL, "s-1", 85, tool_name="Bash", program="/usr/bin/curl -s x"),
            _h(CALL, "s-1", 84, tool_name="WebFetch", web_host="docs.example.com"),
            _h(CALL, "s-1", 83, tool_name="SubagentHandback"),  # bookkeeping: not counted
            _h("claude_hooks.user_prompt_submit", "s-2", 20),
            _h(CALL, "s-2", 19, tool_name="mcp__notes__add", mcp_server_name="notes"),
        ]
    )
    a = _activity(lab, "erin@example.net")
    assert [s.session_id for s in a.sessions] == ["s-2", "s-1"]  # newest first
    s1 = a.sessions[1]
    assert s1.summary == (
        "1 prompt; 5 tool calls (Bash, Edit, WebFetch); 2 files; 1 domain; 1 failed"
    )
    assert s1.flagged
    assert {c.name: c.n for c in a.tools} == {
        "Bash": 2, "Edit": 1, "Write": 1, "WebFetch": 1, "notes": 1,
    }  # fmt: skip
    assert [c.name for c in a.files] == ["/etc/hosts", "/home/erin/app/main.py"]
    assert {c.name for c in a.commands} == {"git", "curl"}  # first word, no path
    assert [c.name for c in a.domains] == ["docs.example.com"]
    assert [c.name for c in a.mcp] == ["notes"]
    flags = {f.kind: f for f in a.flags}
    assert flags["failed_calls"].count == 1
    assert flags["outside_folder"].examples == ["/etc/hosts"]
    assert flags["shell"].count == 2
    assert flags["new_mcp"].examples == ["notes"]
    assert [x.email for x in a.accounts] == ["erin@example.net"]
    if a.accounts[0].tier == "personal":
        assert "personal_account" in flags
    assert "ws-0418" in a.devices  # the machine the records came from


def test_network_services_for_a_person(lab: dict[str, Any]) -> None:  # noqa: F811
    """The lab's DNS names no person; the same lookups named for frank are his AI use."""
    import pyarrow.parquet as pq

    from app.core.ids import uuid7

    lake = lab["app"].state.engine._lake
    rows = []
    for f in sorted(lake.glob("source=dns/day=*/part-*.parquet")):
        for r in pq.read_table(f).to_pylist():
            rows.append({**r, "actor_user_name": "frank@example.com", "event_id": str(uuid7())})
    assert rows
    LakeWriter(lake).write(rows)
    a = _activity(lab, "frank@example.com")
    assert a.services and all(s.name and s.events > 0 and s.last_seen for s in a.services)
    assert "ChatGPT" in {s.name for s in a.services}


def test_helpers() -> None:
    assert outside("/etc/hosts", "/home/erin/app")
    assert not outside("/home/erin/app/src/x.py", "/home/erin/app/")
    assert not outside("src/x.py", "/home/erin/app")  # relative: under the folder
    assert not outside("/home/erin/application/x", None)  # no folder: nothing assumed
    assert outside("/home/erin/application/x", "/home/erin/app")
    assert not outside("C:\\Users\\Erin\\App\\x.py", "c:/users/erin/app")
    assert first_word("/usr/bin/git status") == "git"
    assert first_word("  ") is None


def test_endpoint(lab: dict[str, Any]) -> None:  # noqa: F811
    res = lab["admin"].get("/api/ai/people/alice@example.com/activity")
    assert res.status_code == 200, res.text
    assert res.json()["person"]
