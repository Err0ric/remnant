"""View people in AI usage: who may see names, the masked value, the audit row (D242)."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai.people_view import HIDDEN, audit_ai_view, can_view_people, mask_person
from app.auth.users import User
from app.meta.audit import AuditLog
from app.meta.db import MetaDB


@pytest.mark.parametrize(
    ("role", "flag", "expected"),
    [
        ("admin", False, True),  # admins always have it (G1)
        ("admin", True, True),
        ("analyst", False, False),  # off by default (D242)
        ("analyst", True, True),
        ("auditor", False, False),
        ("auditor", True, True),
    ],
)
def test_can_view_people(role: str, flag: bool, expected: bool) -> None:
    user = User("u1", "ana", role, view_ai_people=flag)  # type: ignore[arg-type]  # parametrized role
    assert can_view_people(user) is expected


@pytest.mark.parametrize(
    ("name", "machine", "expected"),
    [
        ("alice@example.com", "ws-0042.corp.internal", "ws-0042.corp.internal"),
        ("alice@example.com", "10.20.1.5", "10.20.1.5"),
        ("alice@example.com", None, HIDDEN),
        ("alice@example.com", "", HIDDEN),
        (None, "ws-0042.corp.internal", None),  # no person: nothing to hide
        (None, None, None),
    ],
)
def test_mask_person(name: str | None, machine: str | None, expected: str | None) -> None:
    assert mask_person(name, machine) == expected


def _rows(path: Path) -> list[tuple[str, str, dict[str, object]]]:
    with sqlite3.connect(path) as con:
        return [
            (a, u, json.loads(d))
            for a, u, d in con.execute(
                "SELECT action, user_id, detail FROM audit_log ORDER BY audit_id"
            )
        ]


def test_audit_names_the_surface_range_and_sources(tmp_path: Path) -> None:
    meta = MetaDB(tmp_path / "meta.sqlite")
    audit = AuditLog(meta)
    user = User("u1", "ana", "analyst")
    start = datetime(2026, 11, 1, tzinfo=UTC)
    end = datetime(2026, 11, 2, tzinfo=UTC)
    audit_ai_view(audit, user, "192.0.2.10", "ai.usage", start, end, ["dns"], named=False)
    audit_ai_view(audit, user, None, "ai.usage", None, None, ["dns", "claude"], named=True, n=3)
    rows = _rows(tmp_path / "meta.sqlite")
    assert rows[0] == (
        "ai.view",
        "u1",
        {
            "surface": "ai.usage",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sources_in_scope": ["dns"],
        },
    )
    assert rows[1][0] == "ai.view_people"
    assert rows[1][2] == {
        "surface": "ai.usage",
        "start": None,
        "end": None,
        "sources_in_scope": ["dns", "claude"],
        "n": 3,
    }


def test_usage_masked_rows_keep_counts_and_drop_the_hint() -> None:
    """The AI usage answer without the permission: machines, never a hint at a name, and
    rows that tie on every shown value stay apart, keyed by place."""
    from app.api.ai import NetUseOut, PersonOut, UsageOut, _has_names, _masked

    def row(name: str, maybe: str | None = None) -> PersonOut:
        net = NetUseOut(who=name, services=["Claude"], lookups=2, devices=1, last_seen=None)
        return PersonOut(person=name, cost_usd=0.0, tokens=0, sessions=0, tool_calls=0,
                         errors=0, sensitive=0, models=[], seen_through="network",
                         network=net, maybe=maybe)  # fmt: skip

    out = UsageOut(
        services=[], mcp=[], people=[row("bob"), row("dlee", maybe="dana.lee@example.com")],
        sources_in_scope=["dns"],
    )  # fmt: skip
    assert _has_names(out)
    masked = _masked(out, {"bob": None, "dlee": None})
    assert masked.masked and not _has_names(masked)
    assert [(p.person, p.key, p.maybe) for p in masked.people] == [
        (HIDDEN, "row-0", None),
        (HIDDEN, "row-1", None),
    ]
    assert {p.network.who for p in masked.people if p.network} == {HIDDEN}
    assert [p.network.lookups for p in masked.people if p.network] == [2, 2]
    assert "bob" not in masked.model_dump_json() and "dana" not in masked.model_dump_json()


def test_usage_masked_ties_follow_the_keyed_hash_not_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows that tie on every shown value are ordered by the keyed hash, so a row's place
    never follows alphabetical order of the hidden name (D242)."""
    import app.api.ai as ai

    def row(name: str, devices: int) -> ai.PersonOut:
        net = ai.NetUseOut(who=name, services=["Claude"], lookups=2, devices=devices,
                           last_seen=None)  # fmt: skip
        return ai.PersonOut(person=name, cost_usd=0.0, tokens=0, sessions=0, tool_calls=0,
                            errors=0, sensitive=0, models=[], seen_through="network",
                            network=net)  # fmt: skip

    out = ai.UsageOut(services=[], mcp=[], people=[row("alice", 1), row("bob", 2)],
                      sources_in_scope=["dns"])  # fmt: skip
    monkeypatch.setattr(ai, "tie", lambda name: {"alice": b"\x02", "bob": b"\x01"}[name])
    masked = ai._masked(out, {"alice": None, "bob": None})
    assert [p.network.devices for p in masked.people if p.network] == [2, 1]


def test_merged_aliases_keep_the_busiest_machine() -> None:
    from app.ai.usage import NetUse, PersonUse, merge_people, seen_through

    class Ident:
        def key(self, name: str) -> str:
            return "alice"

        def org_email(self, name: str) -> bool:
            return "@" in name

        def display(self, key: str, email: bool) -> str:
            return key

    def use(name: str, sessions: int, machine: str | None) -> PersonUse:
        return PersonUse(name, 0.0, 0, sessions, 0, 0, 0, [], machine=machine)

    rows = [use("EXAMPLE\\alice", 1, "ws-1"), use("alice@example.com", 5, "ws-2"),
            use("alice", 9, None)]  # fmt: skip
    (merged,) = merge_people(rows, Ident())  # type: ignore[arg-type]  # a stub IdentityMap
    assert merged.machine == "ws-2"
    net = [NetUse("alice", ["Claude"], 1, 1, None, "ws-3"),
           NetUse("ALICE", ["Claude"], 4, 1, None, "ws-4")]  # fmt: skip
    (p,), _ = seen_through([], net)
    assert p.network is not None and p.network.machine == "ws-4"


def test_masked_personal_account_drops_the_domain_from_evidence() -> None:
    from app.api.ai import AccountRowOut, _masked_account

    def acc(email: str | None, tier: str, evidence: str) -> AccountRowOut:
        return AccountRowOut(email=email, tier=tier, account_from="claude_json",
                             devices=["ws-0042"], os_users=["carol"], sessions=2,
                             first_seen=None, last_seen=None, evidence=evidence)  # fmt: skip

    personal = _masked_account(
        acc("carol@carol-family.example", "personal",
            "carol-family.example is not an organization domain"), 0,
    )  # fmt: skip
    assert "carol" not in personal.model_dump_json()
    assert (personal.email, personal.evidence, personal.key) == (
        "ws-0042", "Not an organization domain", "row-0",
    )  # fmt: skip
    none = _masked_account(acc(None, "not_checked", "No Claude account reported"), 1)
    assert (none.email, none.evidence) == (None, "No Claude account reported")
