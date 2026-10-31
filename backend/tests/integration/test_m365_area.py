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
    assert [r.label for r in m.reasons] == ["code 50126"]

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
