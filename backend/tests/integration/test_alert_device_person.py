"""Owner item 5 (2026-11-08): an unsanctioned AI service alert names a device; Alerts names
the person through the hooks plugin's own host-to-user records, in the viewer's scope only,
"possible" when several people used the host (ADR-0048 C1), and says why it matters by the
service's catalog status."""

from datetime import timedelta
from typing import Any

from app.ingest.writer import LakeWriter
from tests.integration.test_ai_usage import lab  # noqa: F401  # the fixture
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import NOW

HOOK = "a failed tool call from the Windows plugin names the Claude account"
HOST = "ws-0101.corp.internal"


def _hook(user: str, host: str, minutes: int) -> dict[str, Any]:
    attr = {
        "event_name": "claude_hooks.pre_tool_use", "session_id": f"s-{user}",
        "claude_account_email": user, "tool_name": "Bash",
    }  # fmt: skip
    return _row(
        "claude_hooks", HOOK, "claude",
        time=(NOW - timedelta(minutes=minutes)).isoformat(),
        event="claude_hooks.pre_tool_use", attr=attr,
        resource={"service_name": "claude-hooks", "host_name": host},
    )  # fmt: skip


def _item(lab: dict[str, Any], sid: str, devices: list[str]) -> str:  # noqa: F811
    item = lab["app"].state.alert_items.raise_item(
        "ai_watch", f"service:{sid}", f"AI service not approved: {sid}",
        ref_id=f"service:{sid}", devices=devices, sources=["lin_auth"],
        range_start=(NOW - timedelta(days=7)).isoformat(), range_end=NOW.isoformat(),
    )  # fmt: skip
    return str(item.item_id)


def _get(client: Any, iid: str) -> dict[str, Any]:
    res = client.get(f"/api/alerts/{iid}")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def test_not_approved_service_on_a_hooks_host_names_the_person(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    lab["app"].state.ai_catalog.set_status("gemini", "not_approved", "", "admin")
    LakeWriter(lab["app"].state.engine._lake).write(
        [_hook("erin@example.com", HOST, 40), _hook("erin@example.com", HOST, 30)]
    )
    iid = _item(lab, "gemini", [HOST, "10.20.1.50"])
    got = _get(lab["admin"], iid)
    assert got["review_status"] == "not_approved"
    (dp,) = got["device_people"]
    assert dp == {
        "device": HOST, "level": "attributed", "people": ["erin@example.com"], "count": 1,
        "how": "hooks",
    }  # fmt: skip
    # The list says the same, and the stored people are not changed (D115).
    listed = next(i for i in lab["admin"].get("/api/alerts").json()["items"] if i["item_id"] == iid)
    assert listed["device_people"] == got["device_people"] and listed["people"] == []


def test_a_shared_host_is_possible_never_one_name(lab: dict[str, Any]) -> None:  # noqa: F811
    LakeWriter(lab["app"].state.engine._lake).write(
        [_hook("erin@example.com", HOST, 40), _hook("frank@example.com", HOST, 20)]
    )
    (dp,) = _get(lab["admin"], _item(lab, "gemini", [HOST]))["device_people"]
    assert (dp["level"], dp["count"], dp["people"]) == (
        "possible", 2, ["erin@example.com", "frank@example.com"],
    )  # fmt: skip


def test_identities_links_two_forms_into_one_person(lab: dict[str, Any]) -> None:  # noqa: F811
    a, h = lab["admin"], lab["h"]
    assert a.put("/api/identities/domains", json={"domains": ["example.com"]}, headers=h).is_success
    LakeWriter(lab["app"].state.engine._lake).write(
        [_hook("erin@example.com", HOST, 40), _hook("EXAMPLE\\erin", HOST, 20)]
    )
    (dp,) = _get(a, _item(lab, "gemini", [HOST]))["device_people"]
    assert (dp["level"], dp["count"], dp["how"]) == ("attributed", 1, "hooks_identities")
    assert dp["people"] == ["erin@example.com"]


def test_a_viewer_without_the_hooks_source_gets_no_person(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    LakeWriter(lab["app"].state.engine._lake).write([_hook("erin@example.com", HOST, 40)])
    iid = _item(lab, "gemini", [HOST])
    # Ana reads the alert's own source (lin_auth) but not the hooks source (claude).
    got = _get(lab["ana"], iid)
    assert got["device_people"] == [] and got["devices"] == [HOST]
    assert _get(lab["admin"], iid)["device_people"][0]["people"] == ["erin@example.com"]


def test_records_outside_the_alert_range_or_host_do_not_count(
    lab: dict[str, Any],  # noqa: F811
) -> None:
    LakeWriter(lab["app"].state.engine._lake).write(
        [_hook("erin@example.com", HOST, 60 * 24 * 9), _hook("frank@example.com", "ws-0102", 5)]
    )
    assert _get(lab["admin"], _item(lab, "gemini", [HOST]))["device_people"] == []


def test_review_status_follows_the_catalog(lab: dict[str, Any]) -> None:  # noqa: F811
    cat = lab["app"].state.ai_catalog
    iid = _item(lab, "gemini", [])
    assert _get(lab["admin"], iid)["review_status"] == "unreviewed"
    cat.set_status("gemini", "approved", "", "admin")
    assert _get(lab["admin"], iid)["review_status"] == "approved"
    # A service the catalog does not list is Unknown, apart from Unreviewed.
    assert _get(lab["admin"], _item(lab, "no_such_service", []))["review_status"] == "unknown"
    # Items that are not about a service or MCP server have no status.
    other = lab["app"].state.alert_items.raise_item("gap", "dns", "dns stopped sending")
    assert _get(lab["admin"], other.item_id)["review_status"] is None
