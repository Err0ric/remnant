"""D221: the Detections headline counts distinct matched events, rule matches second, and
its click-through carries the same source filter the count used."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.search import dashboard

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
START = NOW - timedelta(days=7)
BEFORE = START - timedelta(days=7)
AT = NOW - timedelta(hours=2)

# (title, level, event id, event time, source, rule version)
MATCHES = [
    ("SSH failed password", "medium", "e1", AT, "lin_auth", "sha-a"),
    ("SSH failed password", "medium", "e2", AT, "lin_auth", "sha-a"),
    ("SSH unknown user", "low", "e1", AT, "lin_auth", "sha-b"),
    ("SSH unknown user", "low", "e3", AT, "bastion_auth", "sha-b"),
]
CONDS = {"sha-a": "message ILIKE '%Failed password%'", "sha-b": "message ILIKE '%invalid user%'"}


def _detect(monkeypatch: pytest.MonkeyPatch) -> dashboard.Detections:
    monkeypatch.setattr(dashboard, "_matches", lambda *a: (MATCHES, 2))
    monkeypatch.setattr(dashboard, "rule_conditions", lambda meta, shas: CONDS)

    def run(sql: str, sources: list[str], **kw: Any) -> list[list[Any]]:
        return []

    buckets = [START + timedelta(days=i) for i in range(7)]
    out = dashboard._detections(
        run,  # type: ignore[arg-type]  # a fake runner: no events are read here
        None,  # type: ignore[arg-type]  # rule_conditions is replaced, so no meta is read
        None,
        ["lin_auth", "bastion_auth", "web"],
        START,
        BEFORE,
        buckets,
        "7d",
        {},
    )
    assert out is not None
    return out


def test_headline_is_distinct_events_with_rule_matches_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = _detect(monkeypatch)
    assert d.matches.value == 3  # e1, e2, e3
    assert d.matches.extra == 4  # one per rule and event


def test_click_through_keeps_each_rules_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _detect(monkeypatch)
    assert d.matches.drill is not None
    # Each rule's condition is limited to the sources it matched on, never every source.
    assert "list_contains(['lin_auth'], source_id)" in d.matches.drill
    assert "list_contains(['bastion_auth', 'lin_auth'], source_id)" in d.matches.drill
    assert "'web'" not in d.matches.drill
    by = {s.label: s.drill for s in d.by_rule}
    assert by["SSH failed password"] and "['lin_auth']" in by["SSH failed password"]
    assert by["SSH unknown user"] and "['bastion_auth', 'lin_auth']" in by["SSH unknown user"]
    assert d.hosts.drill and "list_contains(['lin_auth'], source_id)" in d.hosts.drill
