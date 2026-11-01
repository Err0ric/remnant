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


def _op(name: str, i: int, when: str = "2026-10-28T09:30:00", **params: str) -> dict[str, Any]:
    return _row(
        "m365_management_activity", "SharePoint file download", "m365_mgmt",
        Operation=name, Id=f"6b2f3a10-0000-4000-8000-{i:012d}", CreationTime=when,
        Workload="Exchange", UserId="dana@example.com",
        Parameters=[{"Name": k, "Value": v} for k, v in params.items()],
    )  # fmt: skip


def test_mail_rules_are_one_definition_on_both_pages(tmp_path: Path) -> None:
    """Owner 2026-10-31 (D132): the Dashboard's card and Microsoft 365's count are the same
    risky rules, organizing ones counted apart, and two rules in one minute count twice."""
    from app.search.dashboard import _identity, _Run

    engine = make_lab(tmp_path)["app"].state.engine
    _write(
        engine,
        [
            _op("New-InboxRule", 1, Name="a", MoveToFolder="Junk Email"),
            _op("New-InboxRule", 2, Name="b", MoveToFolder="Junk Email"),  # same minute
            _op("New-InboxRule", 3, Name="c", MoveToFolder="Projects"),
            _op("Set-Mailbox", 4, ForwardingSmtpAddress="smtp:out@elsewhere.example"),
        ],
    )
    m = overview(engine, None, SOURCES, Places(("US",), (), False, None), "30d", NOW)
    mail = next(c.kpi for c in m.counts if c.key == "mail_rules")
    assert (mail.value, mail.extra) == (3, 1)
    run = _Run(engine, QueryScope(None, datetime(2026, 9, 1, tzinfo=UTC), NOW), {"start": m.start})
    ident = _identity(
        run, ["m365_mgmt"], Places((), (), False, None), lambda ips: {}, "30d", NOW, {}
    )
    assert (ident.inbox_rules.value, ident.inbox_rules.extra) == (mail.value, mail.extra)


def test_a_burst_of_organizing_rules_is_not_risky(tmp_path: Path) -> None:
    """Owner 2026-10-31: 62 rules filing coworkers' mail into department folders over two
    evenings, plus 2 junk rules, read as 2 risky rules and 60 organizing, in one burst."""
    from app.search.mail_rules import list_sql

    engine = make_lab(tmp_path)["app"].state.engine
    rows = [
        _op(
            "New-InboxRule",
            i,
            f"2026-10-{27 + i // 31}T19:{i % 31:02d}:00",
            Name=f"From co{i}",
            From=f"co{i}@example.com",
            MoveToFolder=f":\\Dept {i % 4}",
            StopProcessingRules="True",
        )
        for i in range(60)
    ]
    rows += [
        _op("New-InboxRule", 60, "2026-10-28T20:00:00", Name="j1", MoveToFolder="Junk Email"),
        _op(
            "New-InboxRule",
            61,
            "2026-10-28T20:01:00",
            Name="Invoices",
            SubjectContainsWords="invoice;wire transfer",
            MoveToFolder="RSS Feeds",
            MarkAsRead="True",
        ),
        _op("New-InboxRule", 62, "2026-10-28T20:02:00", Name="fw", ForwardTo="boss@example.com"),
        _op("New-InboxRule", 63, "2026-10-28T20:03:00", Name="del", DeleteMessage="True"),
    ]
    _write(engine, rows)
    sql = (
        list_sql()
        .replace("{from}", "2026-10-01 00:00:00+00")
        .replace("{to}", "2026-11-01 00:00:00+00")
    )
    res = engine.run(sql, QueryScope(None))
    got = [dict(zip(res.columns, r, strict=True)) for r in res.rows]
    mine = [g for g in got if g["person"] == "dana@example.com"]
    by = {g["rule"]: g for g in mine}
    assert sum(g["class"] == "organizing" for g in mine) == 60
    assert by["j1"]["class"] == "hiding" and by["j1"]["severity"] == "medium"
    assert by["Invoices"]["severity"] == "high"  # money words: BEC hiding
    assert by["Invoices"]["action"] == "mark read, move to RSS Feeds"
    assert by["fw"]["class"] == "forwarding" and not by["fw"]["risky"]  # internal
    assert by["del"]["class"] == "deleting" and by["del"]["risky"]
    assert by["From co3"]["folder"] == "Dept 3" and by["From co3"]["stop_processing"]
    assert by["From co3"]["from_address"] == "co3@example.com"
    assert len({g["burst"] for g in mine}) == 1  # two evenings, one burst
    assert [g["risky"] for g in mine[:3]] == [True, True, True]  # risky first


def test_days_follow_the_viewers_time_zone(tmp_path: Path) -> None:
    """Owner 2026-10-31: a chart showed Nov 1 at 7 PM on Oct 31 in Pacific time. Days are
    the viewer's: a sign-in at 03:00 UTC on Oct 28 is Oct 27 in Los Angeles."""
    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, [_signin(50126, "2026-10-28T03:00:00Z")])
    la = overview(engine, None, SOURCES, Places((), (), False, None), "30d", NOW,
                  tz="America/Los_Angeles")  # fmt: skip
    assert la.outcome is not None
    assert all(p.hour == 7 for p in la.outcome.points)  # PDT midnights in UTC
    day = {
        p.date().isoformat(): f for p, f in zip(la.outcome.points, la.outcome.failed, strict=True)
    }
    assert day["2026-10-27"] == 1 and day["2026-10-28"] == 0
    utc = overview(engine, None, SOURCES, Places((), (), False, None), "30d", NOW)
    assert utc.outcome is not None and all(p.hour == 0 for p in utc.outcome.points)
    # Not a zone: UTC, never an error.
    bad = overview(engine, None, SOURCES, Places((), (), False, None), "30d", NOW, tz="Mars/Base")
    assert bad.outcome is not None and bad.outcome.points == utc.outcome.points
