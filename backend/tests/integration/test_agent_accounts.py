"""ADR-0030 amendment: Claude accounts the hooks plugin reports, by tier, with evidence."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.ai.accounts import accounts, tier
from app.ingest.writer import LakeWriter
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 30, tzinfo=UTC)
HOOK = "a failed tool call from the Windows plugin names the Claude account"


def _hook(email: str | None, session: str) -> dict[str, object]:
    attr = {
        "event_name": "claude_hooks.pre_tool_use",
        "session_id": session,
        "os_user": "erin",
        "tool_name": "Bash",
    }
    if email:
        attr |= {"claude_account_email": email, "account_from": "claude_json"}
    return _row(
        "claude_hooks", HOOK, "hooks",
        time="2026-10-29T18:02:00+00:00", event="claude_hooks.pre_tool_use", attr=attr,
    )  # fmt: skip


def test_each_tier_names_its_evidence() -> None:
    last = NOW - timedelta(hours=1)
    domains, signins = ["example.com"], {"ana@example.com": NOW - timedelta(days=2)}
    assert tier(None, last, domains, True, signins)[0] == "not_checked"
    assert tier("ana@example.com", last, [], True, signins)[0] == "not_checked"
    assert tier("ana@gmail.test", last, domains, True, signins)[0] == "personal"
    assert tier("ana@example.com", last, domains, False, {})[0] == "company_reported"
    which, why = tier("ana@example.com", last, domains, True, signins)
    assert which == "company_confirmed" and why.startswith("Entra sign-in to Claude Oct 28")
    old = {"ana@example.com": NOW - timedelta(days=40)}
    assert tier("ana@example.com", last, domains, True, old)[0] == "company_unconfirmed"


def test_accounts_reads_the_hooks_and_sign_ins(tmp_path: Path) -> None:
    engine = make_lab(tmp_path)["app"].state.engine
    rows = [_hook("erin@example.com", "s-1"), _hook("erin@gmail.test", "s-2"), _hook(None, "s-3")]
    rows.append(
        _row(
            "m365_signin",
            "successful sign-in",
            "m365_signin",
            userPrincipalName="erin@example.com",
            appDisplayName="Claude",
            createdDateTime="2026-10-25T09:00:00Z",
        )
    )
    LakeWriter(engine._lake).write(rows)
    out = accounts(engine, None, ["hooks"], ["m365_signin"], ["example.com"], NOW, 30)
    got = {r.email: r.tier for r in out.rows}
    assert got == {
        "erin@example.com": "company_confirmed",
        "erin@gmail.test": "personal",
        None: "not_checked",
    }
    assert out.counts["personal"] == 1 and out.rows[0].devices
    # No Microsoft 365 source: a company email is reported, not confirmed.
    alone = accounts(engine, None, ["hooks"], [], ["example.com"], NOW, 30)
    assert {r.email: r.tier for r in alone.rows}["erin@example.com"] == "company_reported"
