"""Person references in stored AI Watch alert text (D242, ADR-0029 C6)."""

import hashlib

from app.ai.alert_codes import Coder
from app.alerts.person_refs import A_PERSON, REF, PersonRefs

KEY = b"k" * 44


def test_a_name_is_a_keyed_reference_and_reads_back() -> None:
    refs = PersonRefs(lambda: KEY)
    text = "Claude Code, alice@example.com: ws-0042: new MCP server wiki"
    c = Coder(refs, "agent:cc|alice@example.com", ["alice@example.com"], [text])
    stored = c.text(text)
    assert stored is not None and "alice" not in stored and REF.search(stored)
    assert refs.render(stored, refs.known(["alice@example.com"])) == text
    # Someone who is not in the item's people reads as "a person".
    assert refs.render(stored, refs.known(["bob"])) == text.replace("alice@example.com", A_PERSON)


def test_the_same_person_is_the_same_reference_across_restarts_never_a_plain_hash() -> None:
    a, b = PersonRefs(lambda: KEY), PersonRefs(lambda: KEY)
    assert a.ref("alice@example.com") == b.ref("alice@example.com")
    assert a.ref("alice@example.com") != a.ref("bob@example.com")
    assert PersonRefs(lambda: b"other" * 9).ref("alice") != a.ref("alice")
    plain = hashlib.sha256(b"alice@example.com").hexdigest()[:16]
    assert plain not in a.ref("alice@example.com")


def _round_trip(c: Coder, refs: PersonRefs, text: str | None) -> str | None:
    return refs.render(c.text(text), refs.known(c.all_people()))


def test_a_person_is_coded_by_where_it_stands_never_inside_a_machine_or_client() -> None:
    """Review of PR 515, finding 1: `alice` is an owner; the host `ALICE-PC` and the
    client stay exactly as they are, and every line reads back byte for byte."""
    refs = PersonRefs(lambda: KEY)
    subject = "agent:mcp|ALICE-PC|Claude Desktop"
    title = "AI agent not reviewed: Claude Desktop MCP setup on ALICE-PC"
    why = "In use; owner alice; device ALICE-PC"
    line = "Claude Desktop MCP setup on ALICE-PC (alice): new agent"
    c = Coder(refs, subject, [], [title, why, line])
    assert c.key(subject) == subject and c.key(subject + ":agent") == subject + ":agent"
    assert c.text(title) == title
    assert c.text(why) == "In use; owner " + refs.ref("alice") + "; device ALICE-PC"
    assert c.text(line) == f"Claude Desktop MCP setup on ALICE-PC ({refs.ref('alice')}): new agent"
    assert c.all_people() == ["alice"]
    for text in (title, why, line):
        assert _round_trip(c, refs, text) == text


def test_a_person_in_a_key_is_replaced_whole_and_a_machine_never() -> None:
    refs = PersonRefs(lambda: KEY)
    a = refs.ref("Alice")
    c = Coder(refs, "sensitive:Alice", ["Alice"], ["Sensitive data to AI: Alice"])
    assert c.key("sensitive:Alice") == f"sensitive:{a}"
    assert c.key("sensitive:Alice:2026-10-10") == f"sensitive:{a}:2026-10-10"
    assert c.text("Sensitive data to AI: Alice") == f"Sensitive data to AI: {a}"
    assert refs.render(c.key("sensitive:Alice"), refs.known(c.all_people())) == "sensitive:Alice"
    # Keyed by its machine (listed in its devices): nothing is coded.
    m = Coder(refs, "sensitive:alice-pc", [], ["Sensitive data to AI: alice-pc"], ["alice-pc"])
    assert m.key("sensitive:alice-pc:2026-10-10") == "sensitive:alice-pc:2026-10-10"
    assert m.text("Sensitive data to AI: alice-pc") == "Sensitive data to AI: alice-pc"
    # A Claude Code agent with no person is its machine.
    cc = Coder(refs, "agent:cc|ws-1", [], ["AI agent not reviewed: Claude Code on ws-1"])
    assert cc.key("agent:cc|ws-1:agent") == "agent:cc|ws-1:agent"
    # Account: the email in the subject and in the ref id, never the device.
    e = refs.ref("dana@example.org")
    acc = Coder(refs, "account:dana@example.org", ["dana@example.org"],
                ["Personal Claude account dana@example.org on dana-mac"])  # fmt: skip
    assert acc.key("personal:dana@example.org:dana-mac") == f"personal:{e}:dana-mac"
    assert (
        acc.text("Personal Claude account dana@example.org on dana-mac")
        == f"Personal Claude account {e} on dana-mac"
    )


def test_lists_of_people_code_each_one_whole_and_keep_machines() -> None:
    refs = PersonRefs(lambda: KEY)
    detail = "2 people: bob, bob@example.com. 1 device not matched to a person: bobby-pc (10.0.0.5)"
    c = Coder(refs, "service:chatgpt", ["bob", "bob@example.com"], [detail])
    stored = c.text(detail) or ""
    assert "bob" not in stored.replace("bobby-pc", "") and "bobby-pc (10.0.0.5)" in stored
    assert _round_trip(c, refs, detail) == detail
    # Idempotent: a coded text has no person left to code.
    again = Coder(refs, "service:chatgpt", ["bob", "bob@example.com"], [stored])
    assert again.text(stored) == stored
