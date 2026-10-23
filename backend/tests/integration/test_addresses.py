"""Who had an address at the time (ADR-0020 row 1): AI usage and the AI flow name the
person and machine behind DNS queries that carry only an address."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.search.addresses import OBS_SQL
from tests.integration.test_ai_usage import lab as ai_lab  # noqa: F401  # fixture

USERID = (
    "<14>Oct 10 10:30:00 pa-fw01 1,2026/10/10 10:30:00,012345678901,USERID,login,,"
    "2026/10/10 10:30:00,vsys1,10.20.1.5,example\\carol,dc01.example.internal,0,1,,,,ad-dc,"
    "syslog,,,,,,,,pa-fw01" + "," * 40
)
# Too old to count: more than 12 hours before the DNS queries.
USERID_OLD = (
    USERID.replace("Oct 10 10:30:00", "Oct  9 20:00:00")
    .replace("2026/10/10 10:30:00", "2026/10/09 20:00:00")
    .replace("10.20.1.5", "10.20.1.7")
    .replace("carol", "mallory")
)
LOGON = {
    "EventTime": "2026-10-10T10:45:00.000000+00:00",
    "Hostname": "DC01.corp.example",
    "EventType": "AUDIT_SUCCESS",
    "SeverityValue": 2,
    "Severity": "INFO",
    "EventID": 4624,
    "SourceName": "Microsoft-Windows-Security-Auditing",
    "Channel": "Security",
    "SubjectUserName": "DC01$",
    "TargetUserName": "bob",
    "LogonType": "3",
    "IpAddress": "10.20.1.6",
    "IpPort": "50000",
    "WorkstationName": "WS-0042",
}


@pytest.fixture
def lab(ai_lab: dict[str, Any], tmp_path: Path) -> dict[str, Any]:  # noqa: F811  # fixture
    a, h = ai_lab["admin"], ai_lab["h"]
    for sid, tid, fmt, lines in (
        ("userid", "paloalto_userid", "syslog", [USERID, USERID_OLD]),
        (
            "dc_logons",
            "windows_nxlog_json",
            "syslog",
            [
                "<14>Oct 10 10:45:00 DC01 Microsoft-Windows-Security-Auditing[4]: "
                + json.dumps(LOGON)
            ],
        ),
    ):
        folder = tmp_path / "logs" / sid
        folder.mkdir()
        (folder / "a.log").write_text("\n".join(lines) + "\n")
        body = {"source_id": sid, "format": fmt, "path": str(folder), "template_id": tid}
        assert a.post("/api/sources", json=body, headers=h).status_code == 201, sid
    ai_lab["app"].state.ingest.run_once()
    return ai_lab


def test_observations_come_from_logons_and_user_id(lab: dict[str, Any]) -> None:
    res = lab["admin"].post(
        "/api/query",
        json={"sql": f"WITH {OBS_SQL} SELECT ip, who, host FROM addr_ev ORDER BY ip"},
        headers=lab["h"],
    )
    assert res.status_code == 200, res.text
    rows = {tuple(r) for r in res.json()["rows"]}
    assert ("10.20.1.5", "example\\carol", None) in rows
    assert ("10.20.1.6", "bob", "WS-0042") in rows


def test_ai_usage_names_people_behind_addresses(lab: dict[str, Any]) -> None:
    services = lab["admin"].get("/api/ai/usage", params={"start": "2026-10-09T00:00:00Z"}).json()
    got = {u["service"]["id"]: u for u in services["services"]}
    assert got["chatgpt"]["top_people"] == ["example\\carol"]
    assert got["claude"]["top_people"] == ["bob"] and got["claude"]["top_machines"] == ["WS-0042"]
    # The 10.20.1.7 mapping is older than 12 hours, so DeepSeek stays an address.
    assert got["deepseek"]["top_people"] == [] and got["deepseek"]["top_machines"] == ["10.20.1.7"]


def test_ai_flow_and_one_person(lab: dict[str, Any]) -> None:
    rng = {"start": "2026-10-09T00:00:00Z"}
    g = lab["admin"].get("/api/entities/graph", params={"mode": "ai", **rng}).json()
    people = {c["label"] for c in g["cards"] if c["lane"] == 0}
    assert "bob" in people and "10.20.1.6" not in people
    one = (
        lab["admin"]
        .get("/api/entities/graph", params={"mode": "ai", "kind": "user", "value": "bob", **rng})
        .json()
    )
    dests = {c["label"] for c in one["cards"] if c["lane"] == 3}
    assert {"Claude", "OpenAI API"} <= dests


def test_lookup_endpoint_is_scoped_and_audited(lab: dict[str, Any]) -> None:
    res = lab["admin"].get("/api/addresses/10.20.1.6", params={"at": "2026-10-10T11:00:00Z"})
    assert res.status_code == 200, res.text
    holders = {(x["kind"], x["name"]) for x in res.json()["holders"]}
    assert holders == {("user", "bob"), ("host", "WS-0042")}
    assert lab["admin"].get("/api/addresses/not-an-ip").status_code == 400
    # ana reads only Linux sources: nothing to say about this address.
    assert lab["ana"].get("/api/addresses/10.20.1.6").json()["holders"] == []
    # A time without a zone is UTC: the same answer as with Z.
    naive = lab["admin"].get("/api/addresses/10.20.1.6", params={"at": "2026-10-10T11:00:00"})
    assert naive.json()["at"] == "2026-10-10T11:00:00+00:00"
    with lab["app"].state.meta.connect() as con:
        rows = con.execute(
            "SELECT outcome FROM audit_log WHERE action = 'address.lookup' ORDER BY rowid"
        ).fetchall()
    assert [r[0] for r in rows] == ["success", "failure", "success", "success"]  # failures too


def test_ip_entity_names_who_had_it(lab: dict[str, Any]) -> None:
    g = (
        lab["admin"]
        .get(
            "/api/entities/graph",
            params={
                "mode": "entity",
                "kind": "ip",
                "value": "10.20.1.6",
                "start": "2026-10-09T00:00:00Z",
                "end": "2026-10-10T12:00:00Z",
            },
        )
        .json()
    )
    root = next(c for c in g["cards"] if c["lane"] == 0)
    assert root["sublabel"] == "IP address · bob, WS-0042"
