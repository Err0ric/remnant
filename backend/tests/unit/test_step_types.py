"""A session step's type (BACKLOG P1): derived on the server from what the hook record
carries, in one place (`app.ai.sessions.step_type`). Pinned for every event the hooks
plugin sends and every tool the fixtures know; anything else is "other", never a guess.

It agrees with how the session page groups steps today (`groupTurns`): a prompt is
`user_prompt_submit`, a call is `pre_tool_use` (a tool call, a file access, or an access),
a result is `post_tool_use` or `post_tool_use_failure`, and the session start, turn end,
and session end are none of those."""

import json
from pathlib import Path

import pytest

from app.ai.sessions import STEP_TYPES, step_type

FIXTURE = Path(__file__).parents[1] / "fixtures" / "logs" / "claude_hooks" / "sample.log"
PLUGIN = Path(__file__).parents[2] / "app" / "ai" / "claude_plugin" / "posix" / "hooks"

# (event, tool, MCP server, web host, path) -> type. Tools as the plugin fills them: a path
# from file_path, notebook_path, or path; a web host from url; an MCP server from mcp__x__y.
TABLE = [
    ("user_prompt_submit", None, None, None, None, "prompt"),
    ("session_start", None, None, None, None, "other"),
    ("stop", None, None, None, None, "other"),
    ("session_end", None, None, None, None, "other"),
    ("pre_tool_use", "Bash", None, None, None, "tool_call"),
    ("pre_tool_use", "Task", None, None, None, "tool_call"),
    ("pre_tool_use", "TodoWrite", None, None, None, "tool_call"),
    ("pre_tool_use", "SubagentHandback", None, None, None, "tool_call"),
    ("pre_tool_use", "Grep", None, None, None, "tool_call"),
    ("pre_tool_use", "Read", None, None, "/home/alice/app/src/main.py", "file_access"),
    ("pre_tool_use", "Write", None, None, "/etc/hosts", "file_access"),
    ("pre_tool_use", "Edit", None, None, "src/app/main.py", "file_access"),
    ("pre_tool_use", "MultiEdit", None, None, "src/a.py", "file_access"),
    ("pre_tool_use", "NotebookEdit", None, None, "nb/a.ipynb", "file_access"),
    ("pre_tool_use", "Glob", None, None, "src", "file_access"),
    ("pre_tool_use", "WebFetch", None, "docs.example.com", None, "access"),
    ("pre_tool_use", "mcp__github__search_issues", "github", None, None, "access"),
    ("pre_tool_use", "mcp__files__read", "files", None, "/srv/a.txt", "access"),
    # An empty field is not there: the summary's SQL counts by the same test (sessions.has).
    ("pre_tool_use", "WebFetch", None, "", None, "tool_call"),
    ("pre_tool_use", "Read", None, None, "", "tool_call"),
    ("pre_tool_use", "mcp__x__y", "", None, None, "tool_call"),
    ("post_tool_use", "Read", None, None, "/home/alice/app/src/main.py", "tool_result"),
    ("post_tool_use", "WebFetch", None, "docs.example.com", None, "tool_result"),
    ("post_tool_use", "mcp__github__search_issues", "github", None, None, "tool_result"),
    ("post_tool_use_failure", "Bash", None, None, None, "tool_result"),
    ("notification", None, None, None, None, "other"),  # an event the plugin does not send
    ("", None, None, None, None, "other"),
]


@pytest.mark.parametrize(("event", "tool", "mcp", "host", "path", "want"), TABLE)
def test_the_type_of_each_step(
    event: str, tool: str | None, mcp: str | None, host: str | None, path: str | None, want: str
) -> None:
    assert step_type(event, mcp, host, path) == want
    assert step_type(f"claude_hooks.{event}", mcp, host, path) == want  # stored form


def test_every_event_the_plugin_sends_is_in_the_table() -> None:
    sent = {
        line.split("name=", 1)[1].split()[0]
        for line in (PLUGIN / "send.sh").read_text().splitlines()
        if ") name=" in line
    }
    assert sent == {
        "session_start", "user_prompt_submit", "pre_tool_use", "post_tool_use",
        "post_tool_use_failure", "stop", "session_end",
    }  # fmt: skip
    assert sent <= {row[0] for row in TABLE}
    assert {row[-1] for row in TABLE} == set(STEP_TYPES)


def _base(event: str) -> str:
    return event.removeprefix("claude_hooks.")


def test_every_fixture_record_has_the_type_today_s_grouping_reads() -> None:
    seen = set()
    for line in FIXTURE.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        a = rec.get("attr") or {}
        event = str(rec.get("event") or "")
        got = step_type(event, a.get("mcp_server_name"), a.get("web_host"), a.get("path"))
        seen.add((_base(event), a.get("tool_name"), got))
        if _base(event) == "user_prompt_submit":
            assert got == "prompt"
        elif _base(event) == "pre_tool_use":
            assert got in ("tool_call", "file_access", "access")
        elif _base(event) in ("post_tool_use", "post_tool_use_failure"):
            assert got == "tool_result"
        else:
            assert got == "other"
    calls = {(tool, t) for e, tool, t in seen if e == "pre_tool_use"}
    assert calls == {
        ("Bash", "tool_call"), ("Edit", "file_access"), ("Read", "file_access"),
        ("WebFetch", "access"), ("mcp__github__search_issues", "access"),
    }  # fmt: skip
