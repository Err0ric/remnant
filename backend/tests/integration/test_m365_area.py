"""ADR-0038 section 5: the Microsoft 365 area counts each operation once, splits sign-ins
into succeeded, interrupted, and failed, and opens every number in Search (ADR-0039)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.engine.duckdb import QueryScope
from app.enrich.networks import Places
from app.search.m365 import overview
from tests.integration.test_m365_consents import _row, _write
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
SOURCES = [
    ("m365_signin", "file", "m365_signin"),
    ("m365_graph", "file", "m365_directory_audit"),
    ("m365_mgmt", "file", "m365_management_activity"),
]


def _signin(code: int, when: str, **more: Any) -> dict[str, Any]:
    return _row(
        "m365_signin", "successful sign-in", "m365_signin",
        createdDateTime=when, status={"errorCode": code, "failureReason": f"code {code}"},
        **more,
    )  # fmt: skip


def test_overview_splits_outcomes_and_every_number_opens_its_rows(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    _write(
        engine,
        [
            _signin(0, "2026-10-28T10:00:00Z"),
            _signin(50126, "2026-10-28T10:05:00Z", riskLevelDuringSignIn="high"),
            _signin(50074, "2026-10-28T10:06:00Z"),  # MFA asked: interrupted, not failed
            _signin(0, "2026-10-28T11:00:00Z", ipAddress="198.51.100.20"),
        ],
    )
    places = Places(("US",), (), False, None)
    m = overview(engine, None, SOURCES, places, "30d", NOW)
    assert m.has_source and m.sign_ins and m.failed and m.risky and m.consents and m.outcome
    assert (m.sign_ins.value, m.failed.value, m.risky.value) == (4, 1, 1)
    assert (sum(m.outcome.succeeded), sum(m.outcome.interrupted), sum(m.outcome.failed)) == (
        2,
        1,
        1,
    )
    assert (m.consents.value, m.consents.extra) == (1, 1)  # both feeds counted once (D122)
    assert [r.label for r in m.reasons] == ["code 50126 (50126)"]  # the code beside the text

    def count(sql: str | None) -> int:
        assert sql
        filled = sql.replace("{from}", m.start.isoformat()).replace("{to}", m.end.isoformat())
        res = engine.run(f"SELECT count(*) FROM ({filled})", QueryScope(None))
        return int(res.rows[0][0])

    for kpi in (m.sign_ins, m.failed, m.risky, m.consents):
        assert count(kpi.drill) == kpi.value
    assert count(m.consents.extra_drill) == m.consents.extra
    assert count(m.outcome.drill_interrupted) == 1
    for r in m.reasons + m.apps:
        assert count(r.drill) == r.count
    for c in m.counts:
        assert count(c.kpi.drill) == c.kpi.value
    for sql in m.lists.values():
        count(sql)
    # No Microsoft 365 source for this viewer: the area says so instead of zeros.
    assert overview(engine, ["other"], SOURCES, places, "7d", NOW).has_source is False


def test_failure_reasons_read_the_record_when_the_column_is_empty(tmp_path: Path) -> None:
    """Owner 2026-10-31: events stored before m365_signin 1.1.0 have no status_detail; the
    reason comes from Entra's own text in the record, with its error code. "No reason
    given" only when the record has neither."""
    engine = make_lab(tmp_path)["app"].state.engine
    old = _signin(50126, "2026-10-28T10:00:00Z")
    old["status_detail"] = None  # as stored before 1.1.0
    bare = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        createdDateTime="2026-10-28T10:01:00Z", status={"errorCode": 50053},
    )  # fmt: skip
    nothing = _row(
        "m365_signin", "successful sign-in", "m365_signin",
        createdDateTime="2026-10-28T10:02:00Z", status={"errorCode": "x"},
    )  # fmt: skip
    nothing["status_id"] = 2
    _write(engine, [old, bare, nothing])
    m = overview(engine, None, SOURCES, Places(("US",), (), False, None), "30d", NOW)
    labels = sorted(r.label for r in m.reasons)
    assert labels == ["Error 50053", "No reason given", "code 50126 (50126)"]
    by = {r.label: r for r in m.reasons}
    for r in m.reasons:  # each row opens its own failures
        sql = (
            (r.drill or "")
            .replace("{from}", "2026-10-01T00:00:00+00:00")
            .replace("{to}", "2026-10-30T00:00:00+00:00")
        )
        got = engine.run(sql, QueryScope(None))
        assert len(got.rows) == r.count, r.label
    assert by["Error 50053"].detail == "50053"
    # The spike tooltip: who and which app failed most that day.
    assert m.outcome is not None
    assert "alice@example.com (3)" in m.outcome.top_user
    assert any(a.endswith("(3)") for a in m.outcome.top_app)


def test_mail_rules_are_one_definition_on_both_pages(tmp_path: Path) -> None:
    """Owner 2026-10-31: the Dashboard's "Inbox rules and forwarding" is Microsoft 365's
    "Mail rules" plus "Forwarding", and two rules made in the same minute count twice."""
    from app.search.dashboard import CHANGES_SQL

    engine = make_lab(tmp_path)["app"].state.engine

    def op(name: str, i: int, **more: Any) -> dict[str, Any]:
        return _row(
            "m365_management_activity", "SharePoint file download", "m365_mgmt",
            Operation=name, Id=f"6b2f3a10-0000-4000-8000-0000000000{i:02d}",
            CreationTime="2026-10-28T09:30:00", Workload="Exchange", **more,
        )  # fmt: skip

    _write(
        engine,
        [
            op("New-InboxRule", 1),
            op("New-InboxRule", 2),  # same person, same minute: a second rule
            op("Set-Mailbox", 3, Parameters=[{"Name": "ForwardingSmtpAddress", "Value": "x"}]),
        ],
    )
    m = overview(engine, None, SOURCES, Places(("US",), (), False, None), "30d", NOW)
    counts = {c.key: c.kpi.value for c in m.counts}
    assert (counts["mail_rules"], counts["forwarding"]) == (2, 1)
    got = engine.run(
        CHANGES_SQL, QueryScope(None), {"start": datetime(2026, 10, 1, tzinfo=UTC)}
    ).rows
    inbox = {k: now for k, now, _ in got}["inbox"]
    assert inbox == counts["mail_rules"] + counts["forwarding"]
