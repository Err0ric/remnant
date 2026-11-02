"""D158 (owner, 2026-11-02): a failed Entra sign-in is classed by its error code. Only real
failures count as "Failed sign-ins"; interrupted, expired, and other (an unknown code) are
counted apart and stay visible. An install can move a code between classes, and the change
applies to stored events and rollup days alike."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.config import load_config
from app.core.errors import ConfigError
from app.engine import signin_classes
from app.engine.duckdb import QueryScope
from app.enrich.networks import Places
from app.search.dashboard import _identity, _Run
from app.search.m365 import overview, to_dict
from tests.integration.test_m365_area import NOW, SOURCES
from tests.integration.test_m365_consents import _row, _write
from tests.integration.test_m365_rollup import _lab
from tests.integration.test_schedules import make_lab

PLACES = Places(("US",), (), False, None)
# code, class, interactive
SIGNINS: list[tuple[int, str, bool]] = [
    (0, "ok", True),
    (50126, "failed", True),  # wrong password
    (53003, "failed", True),  # blocked by Conditional Access: also "Blocked by policy"
    (50074, "interrupted", True),  # MFA asked, then done
    (50140, "interrupted", True),  # stay signed in prompt
    (70043, "expired", False),  # background refresh, sign-in frequency
    (50058, "expired", False),  # silent sign-in, no session
    (99999, "other", False),  # a code in no class
]


@pytest.fixture(autouse=True)
def _shipped() -> Iterator[None]:
    signin_classes.set_overrides({})
    yield
    signin_classes.set_overrides({})


def _signins(day: datetime) -> list[dict[str, Any]]:
    out = []
    for i, (code, _, interactive) in enumerate(SIGNINS):
        out.append(
            _row(
                "m365_signin", "successful sign-in", "m365_signin",
                createdDateTime=(day + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                userPrincipalName="erin@example.com" if code == 50126 else "dave@example.com",
                isInteractive=interactive,
                status={"errorCode": code, "failureReason": f"code {code}"},
            )
        )  # fmt: skip
    return out


def _count(engine: Any, sql: str | None) -> int:
    filled = (sql or "").replace("{from}", "2026-10-01T00:00:00+00:00")
    filled = filled.replace("{to}", "2026-10-30T00:00:00+00:00")
    return len(engine.run(filled, QueryScope(None)).rows)


def test_each_class_is_counted_apart_and_opens_its_own_rows(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, _signins(datetime(2026, 10, 28, 10, tzinfo=UTC)))
    m = overview(engine, None, SOURCES, PLACES, "30d", NOW)
    assert m.failed is not None and m.blocked is not None and m.outcome is not None
    assert (m.failed.value, m.failed.extra, m.blocked.value) == (2, 5, 1)
    o = m.outcome
    assert (sum(o.succeeded), sum(o.failed), sum(o.interrupted)) == (1, 2, 2)
    assert (sum(o.expired), sum(o.other)) == (2, 1)
    # Every number opens exactly its rows in Search.
    assert _count(engine, m.failed.drill) == 2
    assert _count(engine, m.failed.extra_drill) == 5
    assert _count(engine, m.blocked.drill) == 1
    for sql, n in (
        (o.drill_interrupted, 2), (o.drill_expired, 2), (o.drill_other, 1), (o.drill_failed, 2),
    ):  # fmt: skip
        assert _count(engine, sql) == n
    # Reasons are real failures only.
    assert sorted(r.detail for r in m.reasons) == ["50126", "53003"]


def test_an_unknown_code_is_other_never_dropped(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    row = _signins(datetime(2026, 10, 28, 10, tzinfo=UTC))[-1]
    _write(engine, [row])
    m = overview(engine, None, SOURCES, PLACES, "30d", NOW)
    assert m.failed is not None and m.outcome is not None
    assert (m.failed.value, m.failed.extra, sum(m.outcome.other)) == (0, 1, 1)
    got = engine.run(
        "SELECT signin_class(TRY_CAST(status_code AS INTEGER)), status_code, is_interactive"
        " FROM events WHERE template_id = 'm365_signin'",
        QueryScope(None),
    ).rows
    assert got == [["other", "99999", False]]


def test_dashboard_counts_real_failures_and_names_the_rest(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, _signins(datetime(2026, 10, 28, 10, tzinfo=UTC)))
    m = overview(engine, None, SOURCES, PLACES, "30d", NOW)
    run = _Run(engine, QueryScope(None, datetime(2026, 9, 1, tzinfo=UTC), NOW), {"start": m.start})
    ident = _identity(run, ["m365_signin"], Places((), (), False, None), lambda ips: {}, "30d", NOW, {})  # fmt: skip
    assert (ident.failed.value, ident.failed.extra) == (2, 5)
    assert _count(engine, ident.failed.extra_drill) == 5
    # Top failing users: real failures only (dave's expired and interrupted are not there).
    assert [(r.label, r.count) for r in ident.top_failing] == [
        ("dave@example.com", 1),
        ("erin@example.com", 1),
    ]


def test_an_install_moves_mfa_interrupts_to_failures(tmp_path: Path) -> None:
    """For MFA-fatigue hunting: `m365.signin_classes: {"50074": failed}` counts MFA prompts
    as failures, on stored events, without editing the shipped file."""
    engine = make_lab(tmp_path)["app"].state.engine  # the lab starts with the shipped classes
    cfg = load_config(environ={"APP__M365__SIGNIN_CLASSES__50074": "failed"})
    signin_classes.set_overrides(signin_classes.parse_overrides(cfg.m365.signin_classes))
    _write(engine, _signins(datetime(2026, 10, 28, 10, tzinfo=UTC)))
    m = overview(engine, None, SOURCES, PLACES, "30d", NOW)
    assert m.failed is not None and (m.failed.value, m.failed.extra) == (3, 4)
    moved = [c for c in signin_classes.ACTIVE.adjusted()]
    assert [(c.code, c.shipped, c.cls) for c in moved] == [(50074, "interrupted", "failed")]


def test_a_rollup_day_follows_the_classes_in_force(tmp_path: Path) -> None:
    """The rollup keeps each failure's code, so a class change applies to closed days too,
    with the same numbers as events."""
    engine, rollup = _lab(tmp_path)
    _write(engine, _signins(NOW.replace(hour=1) - timedelta(days=2)))
    rollup.run()
    rolled = overview(engine, None, SOURCES, PLACES, "7d", NOW, rollup)
    live = overview(engine, None, SOURCES, PLACES, "7d", NOW)
    assert to_dict(rolled)["failed"] == to_dict(live)["failed"]
    assert rolled.failed is not None and rolled.failed.value == 2
    signin_classes.set_overrides({50074: "failed", 70043: "failed"})
    rolled = overview(engine, None, SOURCES, PLACES, "7d", NOW, rollup)
    assert rolled.failed is not None and (rolled.failed.value, rolled.failed.extra) == (4, 3)


def test_bad_overrides_are_config_errors() -> None:
    with pytest.raises(ConfigError, match="not an Entra error code"):
        load_config(environ={"APP__M365__SIGNIN_CLASSES__ABC": "failed"})
    with pytest.raises(ConfigError, match="signin_classes"):
        load_config(environ={"APP__M365__SIGNIN_CLASSES__50074": "ignored"})


def test_the_api_shows_the_classes_in_force(tmp_path: Path) -> None:
    lab = make_lab(tmp_path)
    signin_classes.set_overrides({50074: "failed"})
    got = lab["ana"].get("/api/m365/signin-classes").json()
    assert got["classes"] == ["failed", "interrupted", "expired", "other"]
    assert got["blocked_code"] == 53003
    by = {c["code"]: c for c in got["codes"]}
    assert by[50126]["cls"] == "failed" and by[70043]["cls"] == "expired"
    assert got["adjusted"] == [
        {"code": 50074, "cls": "failed", "label": by[50074]["label"], "shipped": "interrupted"}
    ]


def test_sign_ins_tab_filters_by_class_and_by_who_signed_in(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, _signins(datetime(2026, 10, 28, 10, tzinfo=UTC)))
    lists = overview(engine, None, SOURCES, PLACES, "30d", NOW).sign_in_lists
    counts = {(c, mode): _count(engine, lists[c][mode]) for c in lists for mode in lists[c]}
    assert counts[("failed", "all")] == 2 and counts[("failed", "noninteractive")] == 0
    assert counts[("interrupted", "interactive")] == 2
    assert counts[("expired", "noninteractive")] == 2 and counts[("expired", "interactive")] == 0
    assert counts[("other", "all")] == 1
    assert counts[("all", "all")] == len(SIGNINS)
    assert counts[("all", "interactive")] + counts[("all", "noninteractive")] == len(SIGNINS)


def test_a_person_page_counts_real_failures_and_names_the_rest(tmp_path: Path) -> None:
    from app.search.entity_summary import entity_summary

    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, _signins(datetime(2026, 10, 28, 10, tzinfo=UTC)))
    scope = QueryScope(None, datetime(2026, 10, 1, tzinfo=UTC), NOW)
    s = entity_summary(engine, scope, "user", "dave@example.com")
    assert s.failed == 1  # 53003; the interrupted, expired, and other ones are not counted
    by = {a.outcome: a.events for a in s.activities}
    assert by["failed"] == 1 and by["not_counted"] == 5


def test_person_and_address_pages_list_every_class_in_one_click(tmp_path: Path) -> None:
    """Owner 2026-11-02: an investigator sees each class of one person's or one address's
    sign-ins in one click, and All is everything."""
    from app.search.entity_summary import entity_summary

    engine = make_lab(tmp_path)["app"].state.engine
    _write(engine, _signins(datetime(2026, 10, 28, 10, tzinfo=UTC)))
    scope = QueryScope(None, datetime(2026, 10, 1, tzinfo=UTC), NOW)
    s = entity_summary(engine, scope, "user", "dave@example.com")
    got = {x.key: x.count for x in s.sign_in_slices}
    assert got == {"failed": 1, "interrupted": 2, "expired": 2, "other": 1, "all": 7}
    for x in s.sign_in_slices:  # each opens exactly its rows
        assert len(engine.run(x.search_sql, scope).rows) == x.count, x.key
    ip = entity_summary(engine, scope, "ip", "203.0.113.10")  # every test sign-in's address
    got = {x.key: x.count for x in ip.sign_in_slices}
    assert got == {"failed": 2, "interrupted": 2, "expired": 2, "other": 1, "all": 8}


def test_an_unsatisfied_external_challenge_is_interrupted(tmp_path: Path) -> None:
    """Owner 2026-11-02: 50158 (external security challenge not yet satisfied) ships as
    interrupted; 81014 stays other for now."""
    engine = make_lab(tmp_path)["app"].state.engine
    got = engine.run("SELECT signin_class(50158), signin_class(81014)", QueryScope(None)).rows
    assert got == [["interrupted", "other"]]
