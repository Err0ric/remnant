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


def test_each_what_it_did_row_opens_exactly_its_events(tmp_path: Path) -> None:
    """Review of PR 671: a row's link filters on the rule that grouped it, so a sign-in with
    no status (outcome other) opens itself, not the person's other sign-ins too; and a row
    with no user or no target opens only the rows without one (the address's page)."""
    from app.search.entity_summary import entity_summary

    engine = make_lab(tmp_path)["app"].state.engine
    rows = _signins(datetime(2026, 10, 28, 10, tzinfo=UTC))
    for status in (None, 0, 99):
        r = _row(
            "m365_signin", "successful sign-in", "m365_signin",
            createdDateTime="2026-10-28T11:00:00Z", userPrincipalName="dave@example.com",
        )  # fmt: skip
        r["status_id"] = status
        rows.append(r)
    for column in ("actor_user_name", "device_hostname"):  # no user; no target
        r = _row("m365_signin", "successful sign-in", "m365_signin")
        r[column] = None
        rows.append(r)
    _write(engine, rows)
    scope = QueryScope(None, datetime(2026, 10, 1, tzinfo=UTC), NOW)
    s = entity_summary(engine, scope, "user", "dave@example.com")
    assert {a.outcome for a in s.activities} >= {"succeeded", "other", "not_counted"}
    ip = entity_summary(engine, scope, "ip", "203.0.113.10")  # every test sign-in's address
    assert any(a.user is None for a in ip.activities)
    assert any(a.target is None for a in ip.activities)
    for a in s.activities + ip.activities:
        got = len(engine.run(a.search_sql, scope).rows)
        assert got == a.events, (a.outcome, a.user, a.target)


def test_access_outcome_names_each_outcome(tmp_path: Path) -> None:
    """The one outcome rule (D279), one row per outcome: firewall traffic, a sign-out, and
    a sign-in that succeeded, really failed, was not counted (D158), or says nothing."""
    engine = make_lab(tmp_path)["app"].state.engine
    cases = [
        ("4001, 1, 1, 'paloalto_traffic', NULL, NULL", "allowed"),
        ("4001, 1, 2, 'paloalto_traffic', NULL, NULL", "denied"),
        ("4001, 1, 3, 'paloalto_traffic', NULL, NULL", "other"),
        ("3002, 2, 1, 'linux_sshd', NULL, NULL", "signed out"),
        ("3002, 1, 1, 'linux_sshd', NULL, NULL", "succeeded"),
        ("3002, 1, 2, 'linux_sshd', NULL, NULL", "failed"),
        ("3002, 1, 2, 'm365_signin', '50126', NULL", "failed"),
        ("3002, 1, 2, 'm365_signin', NULL, '{\"status\": {\"errorCode\": 50126}}'", "failed"),
        ("3002, 1, 2, 'm365_signin', NULL, '{\"status\": {\"errorCode\": 50074}}'", "not counted"),
        ("3002, 1, NULL, 'linux_sshd', NULL, NULL", "other"),
    ]
    values = ", ".join(f"({v})" for v, _ in cases)
    got = engine.run(
        f"SELECT {signin_classes.ACCESS_OUTCOME} FROM (VALUES {values})"
        " AS t(class_uid, activity_id, status_id, template_id, status_code, raw)",
        QueryScope(None),
    ).rows
    assert [r[0] for r in got] == [want for _, want in cases]


def test_the_entity_pages_sign_in_rule_reads_the_code_as_the_plain_conditions(
    tmp_path: Path,
) -> None:
    """Speed (owner, 2026-11-17): the entity pages' one sign-in rule (`access_outcome`,
    the summary's counts, the person record) reads the error code only on Microsoft 365
    sign-ins; on every row it agrees with `REAL_FAILURE_SQL` and `class_sql`, with the code
    from the record (no column) and with other sources' sign-ins too."""
    from app.search import entities as en

    engine = make_lab(tmp_path)["app"].state.engine  # Windows and Linux sign-ins as well
    rows = _signins(datetime(2026, 10, 28, 10, tzinfo=UTC))
    for r in rows[1::2]:
        r["status_code"] = None  # stored before the column: the code comes from the record
    _write(engine, rows)
    pairs = [(signin_classes.REAL_FAILURE_SQL, signin_classes.REAL_FAILURE)]
    pairs += [
        (f"template_id = 'm365_signin' AND {signin_classes.class_sql(c)}", en.failed_class(c))
        for c in ("failed", "interrupted", "expired", "other")
    ]
    attempt = "class_uid = 3002 AND coalesce(activity_id, 0) <> 2"
    pairs += [
        (
            f"{attempt} AND {signin_classes.REAL_FAILURE_SQL}",
            f"{attempt} AND {signin_classes.ACCESS_OUTCOME} = 'failed'",
        )
    ]
    for shown, counted in pairs:
        same = f"coalesce({shown}, false) = coalesce({counted}, false)"
        got = engine.run(
            f"SELECT count(*), count(*) FILTER (WHERE {same}),"
            f" count(*) FILTER (WHERE class_uid = 3002 AND {shown}) FROM events",
            QueryScope(None),
        ).rows[0]
        assert got[0] == got[1] and got[0] > 10, shown
        assert got[2] > 0, shown  # each condition matches sign-ins here


def test_an_unsatisfied_external_challenge_is_interrupted(tmp_path: Path) -> None:
    """Owner 2026-11-02: 50158 (external security challenge not yet satisfied) ships as
    interrupted; 81014 stays other for now."""
    engine = make_lab(tmp_path)["app"].state.engine
    got = engine.run("SELECT signin_class(50158), signin_class(81014)", QueryScope(None)).rows
    assert got == [["interrupted", "other"]]
