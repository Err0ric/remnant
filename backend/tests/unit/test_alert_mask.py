"""AI Watch alert items without View people in AI usage: no name in any text (D242)."""

import json
from dataclasses import asdict
from typing import Any

import pytest

from app.ai.alert_mask import has_names, mask_item, mask_mute, names_in
from app.alerts.items import AlertItem, ItemEvent, Mute


def _item(kind: str = "ai_watch", **kw: Any) -> AlertItem:
    base: dict[str, Any] = {
        "item_id": "i1", "kind": kind, "subject": "s", "ref_id": None, "title": "t",
        "detail": "", "why": None, "count": 1, "sources": ["claude"], "owner_id": None,
        "shared": True, "range_start": None, "range_end": None, "created_at": "c",
        "state": "open", "closed_at": None, "closed_by": None, "close_reason": None,
        "note": None, "resolved": None,
    }  # fmt: skip
    return AlertItem(**{**base, **kw})


def _text(i: AlertItem) -> str:
    return json.dumps(asdict(i))


# The shapes app.ai.watch writes, old items included.
CASES = [
    # (subject, title, why, detail, people, changes, expected title, why, detail)
    pytest.param(
        "sensitive:alice@example.com", "Sensitive data to AI: alice@example.com",
        "secret x2", "", ["alice@example.com"], [],
        ("Sensitive data to AI: a person", "secret x2", ""), id="sensitive",
    ),
    pytest.param(
        "service:openai", "AI service not reviewed: OpenAI", "Not reviewed yet",
        "2 people: alice@example.com, bob. 1 device not matched to a person: ws-0042",
        ["alice@example.com", "bob"], [],
        ("AI service not reviewed: OpenAI", "Not reviewed yet",
         "2 people: a person, a person. 1 device not matched to a person: ws-0042"),
        id="service",
    ),
    pytest.param(
        "account:carol@personal.example", "Personal Claude account carol@personal.example on ws-7",
        "Personal Claude account carol@personal.example on ws-7", "",
        ["carol@personal.example"], [],
        ("Personal Claude account a person on ws-7", "Personal Claude account a person on ws-7",
         ""), id="personal account",
    ),
    pytest.param(
        "agent:cc|alice@example.com", "AI agent not reviewed: Claude Code, alice@example.com: ws-1",
        "In use; owner alice@example.com; device ws-1", "", ["alice@example.com"], [],
        ("AI agent not reviewed: Claude Code, a person: ws-1",
         "In use; owner a person; device ws-1", ""), id="claude code agent",
    ),
    pytest.param(
        # Keyed by a bare user name: not in people, still a name.
        "agent:cc|dave", "AI agent: blocked or failed calls, dave",
        "3 blocked or failed tool calls in an hour by Claude Code for dave", "", [],
        ["3 blocked or failed tool calls in an hour by Claude Code for dave"],
        ("AI agent: blocked or failed calls, a person",
         "3 blocked or failed tool calls in an hour by Claude Code for a person", ""),
        id="blocked calls, bare name",
    ),
    pytest.param(
        # An MCP client's owners are only in the lines.
        "agent:mcp|ws-2|cursor", "AI agent changed: Cursor MCP setup on ws-2",
        "Cursor MCP setup on ws-2 (erin, frank): new MCP server notes", "", [],
        ["Cursor MCP setup on ws-2 (erin, frank): new MCP server notes"],
        ("AI agent changed: Cursor MCP setup on ws-2",
         "Cursor MCP setup on ws-2 (a person, a person): new MCP server notes", ""),
        id="mcp client owners",
    ),
    pytest.param(
        "agent:mcp|ws-2|cursor", "AI agent not reviewed: Cursor MCP setup on ws-2",
        "In use; owner grace, heidi; devices ws-2, ws-3", "", [], [],
        ("AI agent not reviewed: Cursor MCP setup on ws-2",
         "In use; owner a person, a person; devices ws-2, ws-3", ""), id="standing owners",
    ),
    # Stored before people were kept apart (migration 57): names only in the text.
    pytest.param(
        "service:openai", "AI service not reviewed: OpenAI", "Not reviewed yet",
        "2 people: alice@example.com, bob. 1 device not matched to a person: ws-0042", [], [],
        ("AI service not reviewed: OpenAI", "Not reviewed yet",
         "2 people: a person, a person. 1 device not matched to a person: ws-0042"),
        id="service, before people were stored",
    ),
    pytest.param(
        "mcp:notes", "MCP server not reviewed: notes", "Not reviewed yet", "1 person: carol",
        [], [], ("MCP server not reviewed: notes", "Not reviewed yet", "1 person: a person"),
        id="mcp server, before people were stored",
    ),
    pytest.param(
        "mcp:notes", "MCP server not reviewed: notes", "Not reviewed yet",
        "6 people: ana, bob, carol, dana, erin and more", [], [],
        ("MCP server not reviewed: notes", "Not reviewed yet",
         "6 people: a person, a person, a person, a person, a person and more"),
        id="more than five, before people were stored",
    ),
    pytest.param(
        # Before 2026-10-22 people and machines were one list: all of it is masked.
        "service:openai", "New AI service: OpenAI", None,
        "Used by 3: alice@example.com, bob, ws-0042 and more", [], [],
        ("New AI service: OpenAI", None, "Used by 3: a person, a person, a person and more"),
        id="used by, before people and devices were apart",
    ),
    pytest.param(
        "sensitive:alice@example.com", "Sensitive data to AI: alice@example.com",
        "secret x2", "", [], [], ("Sensitive data to AI: a person", "secret x2", ""),
        id="sensitive, before people were stored",
    ),
    pytest.param(
        "agent:cc|alice@example.com", "New AI agent: Claude Code on ws-1",
        "Claude Code on ws-1 (alice@example.com): new agent", "", [], [],
        ("New AI agent: Claude Code on ws-1", "Claude Code on ws-1 (a person): new agent", ""),
        id="claude code agent, before people were stored",
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("subject", "title", "why", "detail", "people", "changes", "expected"), CASES
)
def test_known_shapes_name_no_one(
    subject: str,
    title: str,
    why: str | None,
    detail: str,
    people: list[str],
    changes: list[str],
    expected: tuple[str, str | None, str],
) -> None:
    item = _item(subject=subject, title=title, why=why, detail=detail, people=people,
                 ref_id=f"{subject}:2026-11-11", entity=subject, changes=changes)  # fmt: skip
    names = names_in(subject, people, [title, why, detail, *changes])
    assert names and has_names(item)
    out = mask_item(item)
    assert (out.title, out.why, out.detail) == expected
    assert out.people == []
    text = _text(out).lower()
    for n in names:
        assert n.lower() not in text
        assert n.split("@")[0].lower() not in text
    assert out.subject.split(":")[0] == subject.split(":")[0]  # the kind of subject stays


def test_a_claude_code_agent_on_a_machine_keeps_the_machine() -> None:
    item = _item(subject="agent:cc|ws-0042", title="AI agent not reviewed: Claude Code on ws-0042",
                 why="In use; owner no person matched; device ws-0042")  # fmt: skip
    assert not has_names(item)
    assert mask_item(item).title == item.title
    assert mask_item(item).subject == "agent:cc|ws-0042"


MACHINE = "ws-0042"
BLOCKED = f"3 blocked or failed tool calls in an hour by Claude Code for {MACHINE}"


@pytest.mark.parametrize(
    ("subject", "title", "why"),
    [
        pytest.param(f"agent:cc|{MACHINE}", f"AI agent: blocked or failed calls, {MACHINE}",
                     BLOCKED, id="blocked calls"),
        pytest.param(f"sensitive:{MACHINE}", f"Sensitive data to AI: {MACHINE}", "secret x1",
                     id="sensitive"),
    ],
)  # fmt: skip
def test_an_item_keyed_by_a_machine_it_lists_keeps_the_machine(
    subject: str, title: str, why: str
) -> None:
    """AI Watch lists the machine in devices when no person was seen: proven, so kept, and
    the item names no one (a permitted viewer's audit is ai.view)."""
    item = _item(subject=subject, title=title, why=why, devices=[MACHINE])
    assert not has_names(item)
    out = mask_item(item)
    assert (out.subject, out.title, out.why) == (subject, title, why)
    # The same shape with a person, or a machine it does not list, is masked.
    for key, people, devices in (("bob", [], [MACHINE]), (MACHINE, [], []),
                                 (MACHINE, [MACHINE], [MACHINE])):  # fmt: skip
        other = _item(subject=subject.replace(MACHINE, key), title=title.replace(MACHINE, key),
                      why=why.replace(MACHINE, key), people=people, devices=devices)  # fmt: skip
        assert has_names(other), (key, people, devices)
        out = mask_item(other)
        assert key not in f"{out.subject} {out.title} {out.why}"


def test_claude_code_on_a_longer_machine_name_is_no_proof() -> None:
    item = _item(subject="agent:cc|ws", title="AI agent not reviewed: Claude Code on ws-0042",
                 why="In use; owner no person matched; device ws-0042")  # fmt: skip
    assert has_names(item)
    assert mask_item(item).subject == "agent:cc|a person"


def test_forms_of_a_name_are_masked_as_words_ignoring_case() -> None:
    item = _item(
        subject="sensitive:Alice@Example.com", title="Sensitive data to AI: alice@example.com",
        why="ALICE on ws-1; malice stays", people=["Alice@Example.com"],
        note="closed after a call with alice", history=[ItemEvent("t", "u", "close", "x", "alice")],
    )  # fmt: skip
    out = mask_item(item)
    assert out.title == "Sensitive data to AI: a person"
    assert out.why == "a person on ws-1; malice stays"
    assert out.note == "closed after a call with a person"
    assert out.history[0].note == "a person"


def test_a_short_local_part_is_left_alone() -> None:
    """Only the whole email is a name when its local part is under 3 characters."""
    item = _item(subject="sensitive:al@example.com", title="Sensitive data to AI: al@example.com",
                 why="all of al's", people=["al@example.com"])  # fmt: skip
    out = mask_item(item)
    assert out.title == "Sensitive data to AI: a person" and out.why == "all of al's"


@pytest.mark.parametrize("kind", ["rule", "gap", "schedule"])
def test_other_kinds_are_unchanged(kind: str) -> None:
    item = _item(kind, subject="rule:r1", title="Many failed sign-ins: alice", people=["alice"])
    assert mask_item(item) is item
    assert not has_names(item)


def test_a_mute_names_no_one() -> None:
    m = Mute("m1", "ai_watch", "sensitive:alice@example.com",
             "Sensitive data to AI: alice@example.com", "u", None, "c")  # fmt: skip
    out = mask_mute(m)
    assert (out.subject, out.title) == ("sensitive:a person", "Sensitive data to AI: a person")
    rule = Mute("m2", "rule", "rule:r1", "Many failed sign-ins: alice", "u", None, "c")
    assert mask_mute(rule) is rule
