"""Microsoft 365 > Admin (owner, 2026-11-01): sync and provisioning cycles apart from
changes, apps named instead of ServicePrincipal_<id>, a readable status, an event count,
the properties changed, and real admin changes ranked above routine ones. All names here
are synthetic."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.engine.duckdb import QueryScope
from app.ingest.writer import LakeWriter
from app.search import drill
from app.search.admin_changes import ADMIN_SQL
from tests.integration.test_m365_consents import _row
from tests.integration.test_schedules import make_lab

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
SYNC_SP = "11111111-1111-4111-8111-111111111111"
HR_SP = "22222222-2222-4222-8222-222222222222"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dir(at: datetime, op: str, result: str = "success", **more: Any) -> dict[str, Any]:
    return _row(
        "m365_directory_audit", "change by an app", "m365_graph",
        activityDisplayName=op, activityDateTime=_iso(at), result=result, **more,
    )  # fmt: skip


def _records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sync = {"app": {"displayName": "Example Directory Sync", "servicePrincipalId": SYNC_SP}}
    scim = {"app": {"displayName": "Example SCIM Connector"}}
    t = NOW - timedelta(hours=30)
    while t < NOW:  # a cycle every 10 minutes: an import and an execution each
        for op in ("Import", "Execution"):
            out.append(_dir(t, op, initiatedBy=sync, loggedByService="Account Provisioning"))
        out.append(_dir(t, "Export", initiatedBy=scim, loggedByService="Account Provisioning"))
        t += timedelta(minutes=10)
    out.append(_dir(NOW - timedelta(hours=2), "Execution", "failure", initiatedBy=sync))
    # The directory names the HR connector when it is the target of a change.
    out.append(
        _dir(
            NOW - timedelta(hours=20), "Update service principal",
            initiatedBy={"user": {"userPrincipalName": "admin@example.com"}},
            targetResources=[{"id": HR_SP, "displayName": "Example HR Connector",
                              "type": "ServicePrincipal"}],
        )
    )  # fmt: skip
    # The one real change by an app, from the Management API, as ServicePrincipal_<id>.
    out.append(
        _row(
            "m365_management_activity", "failed Entra logon", "m365_mgmt",
            CreationTime=_iso(NOW - timedelta(hours=5))[:-1], Operation="Update user.",
            ResultStatus="Success", UserId=f"ServicePrincipal_{HR_SP}", ObjectId="pat@example.com",
            Id="6b2f3a10-0000-4000-8000-0000000000aa",
            ModifiedProperties=[{"Name": "Department", "NewValue": "Finance"},
                                {"Name": "JobTitle", "NewValue": "Analyst"}],
        )
    )  # fmt: skip
    out.append(
        _dir(
            NOW - timedelta(hours=3), "Add member to role",
            initiatedBy={"user": {"userPrincipalName": "admin@example.com"}},
            targetResources=[{"displayName": "Helpdesk Administrator", "type": "Role"}],
        )
    )  # fmt: skip
    out.append(
        _dir(
            NOW - timedelta(hours=1), "Update user",
            initiatedBy={"user": {"userPrincipalName": "admin@example.com"}},
            targetResources=[{"userPrincipalName": "sam@example.com", "type": "User",
                              "modifiedProperties": [{"displayName": "MobilePhone"}]}],
        )
    )  # fmt: skip
    return out


def _rows(tmp_path: Path) -> list[dict[str, Any]]:
    engine = make_lab(tmp_path)["app"].state.engine
    LakeWriter(engine._lake).write(_records())
    start = NOW - timedelta(days=7)
    sql = ADMIN_SQL.replace("{from}", start.isoformat()).replace("{to}", NOW.isoformat())
    res = engine.run(sql, QueryScope(None, start, NOW), row_cap=10_000)
    return [dict(zip(res.columns, r, strict=True)) for r in res.rows]


def test_cycles_are_provisioning_and_changes_are_apart(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    cycles = [r for r in rows if r["provisioning"]]
    changes = [r for r in rows if not r["provisioning"]]
    assert {r["service"] for r in cycles} == {"Example Directory Sync", "Example SCIM Connector"}
    assert [r["status"] for r in cycles].count("Failure") == 1
    assert {r["operation"] for r in changes} == {
        "add member to role", "update service principal", "update user",
    }  # fmt: skip
    assert len(changes) == 4


def test_an_app_is_named_and_its_change_says_what_changed(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    hr = next(r for r in rows if r["actor_kind"] == "app" and not r["provisioning"])
    assert hr["actor"] == "Example HR Connector" and hr["app_id"] == HR_SP
    assert hr["operation"] == "update user" and hr["target"] == "pat@example.com"
    assert hr["changed"] == "Department, JobTitle" and hr["status"] == "Success"
    assert hr["events"] == 1 and len(hr["event_ids"]) == 1
    person = next(r for r in rows if r["actor"] == "admin@example.com" and r["changed"])
    assert person["changed"] == "MobilePhone" and person["actor_kind"] == "person"


def test_real_admin_changes_rank_above_routine(tmp_path: Path) -> None:
    changes = [r for r in _rows(tmp_path) if not r["provisioning"]]
    assert changes[0]["operation"] == "add member to role" and changes[0]["rank"] > 0
    routine = sorted(r["operation"] for r in changes if r["rank"] == 0)
    assert routine == ["update service principal", "update user", "update user"]


def test_the_events_open_in_search(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    ids = rows[0]["event_ids"]
    sql = drill.events(f"list_contains({drill.lits([str(i) for i in ids])}, event_id)")
    assert "event_id" in sql
