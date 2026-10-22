#!/usr/bin/env python3
"""Fixtures for the API connector templates: Microsoft 365 (ADR-0002) and Anthropic
(ADR-0015 row 10).

Microsoft records follow the documented shapes of the Management Activity API common
schema and the Graph signIn, directoryAudit, and alerts_v2 resources; they are stored as
the connector stores them (Microsoft's JSON, compact). Anthropic lines are made with the
connector's own record function, so they match what ingest receives.

    cd backend && uv run python ../scripts/fixtures/connectors.py

Synthetic only: example.com and .example names, invented ids, RFC 5737 and 2001:db8::/32
addresses.
"""

from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.ingest.connectors.anthropic import _rec  # noqa: E402

FIX = ROOT / "backend" / "tests" / "fixtures" / "logs"
START = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
USERS = ["alice@example.com", "bob@example.com", "carol@example.com", "dave@example.com"]
IPS = ["203.0.113.10", "198.51.100.7", "203.0.113.44", "2001:db8::17"]
HOSTS = ["WS-0042", "LT-0107", "WS-0311"]
ORG = "00000000-0000-4000-8000-0000000000aa"
rng = random.Random(42)


def compact(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def gid() -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def iso_z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_out(t: datetime) -> str:
    return t.isoformat()


# --- Management Activity API ---------------------------------------------------------

def management() -> tuple[list[str], list[dict[str, Any]]]:
    kinds = [
        ("SharePoint", 6, "FileDownloaded", None),
        ("SharePoint", 6, "FileAccessed", None),
        ("Exchange", 2, "MailItemsAccessed", "Succeeded"),
        ("Exchange", 1, "New-InboxRule", "True"),
        ("AzureActiveDirectory", 15, "UserLoggedIn", "Success"),
        # Microsoft writes "Success" on failed logons (the audit write succeeded); the
        # failure is in Operation and LogonError (install finding F42).
        ("AzureActiveDirectory", 15, "UserLoginFailed", "Success"),
        ("Copilot", 261, "CopilotInteraction", None),
        ("Exchange", 13, "DlpRuleMatch", None),
        ("MicrosoftTeams", 25, "MessageSent", None),
    ]
    out, exp = [], []
    t = START
    for i in range(60):
        workload, rt, op, result = kinds[i % len(kinds)]
        t += timedelta(seconds=rng.randint(5, 90))
        user = USERS[i % len(USERS)]
        rec: dict[str, Any] = {
            "CreationTime": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "Id": gid(),
            "Operation": op,
            "OrganizationId": ORG,
            "RecordType": rt,
            "UserKey": gid(),
            "UserType": 0,
            "Version": 1,
            "Workload": workload,
            "UserId": user,
        }
        ip = IPS[i % len(IPS)]
        if result:
            rec["ResultStatus"] = result
        if op == "UserLoginFailed":
            rec["LogonError"] = "InvalidUserNameOrPassword"
        if op != "DlpRuleMatch":
            rec["ClientIP"] = f"{ip}:{rng.randint(1024, 65535)}" if i % 5 == 0 and ":" not in ip else ip
        if workload == "SharePoint":
            rec["ObjectId"] = f"https://contoso.example/sites/finance/doc{i}.xlsx"
        if op == "CopilotInteraction":
            rec["CopilotEventData"] = {
                "AppHost": rng.choice(["Word", "Teams", "Outlook"]),
                "Contexts": [{"Id": f"https://contoso.example/sites/hr/policy{i}.docx", "Type": "docx"}],
            }
        if op == "DlpRuleMatch":
            rec["PolicyDetails"] = [{"PolicyName": "PII", "Rules": [{"RuleName": "SSN", "Severity": "High"}]}]
        out.append(compact(rec))
        row: dict[str, Any] = {
            "parse_status": "ok",
            "class_uid": 6003,
            "actor_user_name": user,
            "message": op,
            "time": iso_out(t),
        }
        if "ClientIP" in rec:
            row["src_endpoint_ip"] = ip
        if op == "UserLoginFailed":
            row["status_id"] = 2
        elif result:
            row["status_id"] = 2 if result == "Failed" else 1
        if op == "DlpRuleMatch":
            row["severity_id"] = 3
        exp.append(row)
    return out, exp


# --- Graph sign-ins ------------------------------------------------------------------

APPS = ["Office 365 SharePoint Online", "Microsoft Teams", "Azure Portal", "Office 365 Exchange Online"]
FAIL = [(50126, "Invalid username or password."), (53003, "Access has been blocked by Conditional Access policies.")]


def signins() -> tuple[list[str], list[dict[str, Any]]]:
    out, exp = [], []
    t = START
    for i in range(60):
        t += timedelta(seconds=rng.randint(10, 120), microseconds=rng.randint(0, 999_999))
        user = USERS[i % len(USERS)]
        failed = i % 7 == 3
        code, reason = FAIL[i % 2] if failed else (0, "Other.")
        risk = ["none", "low", "medium", "high"][i % 4] if i % 3 == 0 else "none"
        host = HOSTS[i % len(HOSTS)]
        rec = {
            "id": gid(),
            "createdDateTime": t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "userDisplayName": user.split("@")[0].title(),
            "userPrincipalName": user,
            "userId": gid(),
            "appId": gid(),
            "appDisplayName": APPS[i % len(APPS)],
            "ipAddress": IPS[i % len(IPS)],
            "clientAppUsed": "Browser" if i % 2 else "Mobile Apps and Desktop clients",
            "correlationId": gid(),
            "conditionalAccessStatus": "failure" if code == 53003 else "success",
            "isInteractive": i % 2 == 0,
            "riskDetail": "none",
            "riskLevelAggregated": "none",
            "riskLevelDuringSignIn": risk,
            "riskState": "none",
            "status": {"errorCode": code, "failureReason": reason, "additionalDetails": None},
            "deviceDetail": {"deviceId": "", "displayName": host, "operatingSystem": "Windows10", "browser": "Edge 130.0"},
            "location": {"city": "Springfield", "state": "Illinois", "countryOrRegion": "US"},
        }
        out.append(compact(rec))
        row: dict[str, Any] = {
            "parse_status": "ok",
            "class_uid": 3002,
            "activity_id": 1,
            "actor_user_name": user,
            "src_endpoint_ip": rec["ipAddress"],
            "device_hostname": host,
            "message": rec["appDisplayName"],
            "status_id": 2 if failed else 1,
        }
        if risk in ("low", "medium", "high"):
            row["severity_id"] = {"low": 2, "medium": 3, "high": 4}[risk]
        exp.append(row)
    return out, exp


# --- Graph directory audits ----------------------------------------------------------

ACTIVITIES = [
    ("UserManagement", "Update user", "Update", None),
    ("GroupManagement", "Add member to group", "Assign", None),
    ("RoleManagement", "Add member to role", "Assign", 3),
    ("ApplicationManagement", "Add service principal credentials", "Update", 3),
    ("Policy", "Update conditional access policy", "Update", 3),
    ("UserManagement", "Reset user password", "Update", None),
]


def audits() -> tuple[list[str], list[dict[str, Any]]]:
    out, exp = [], []
    t = START
    for i in range(55):
        t += timedelta(seconds=rng.randint(30, 300))
        cat, act, optype, sev = ACTIVITIES[i % len(ACTIVITIES)]
        by_app = i % 5 == 4
        actor = "Provisioning Sync" if by_app else USERS[i % len(USERS)]
        initiated: dict[str, Any] = (
            {"app": {"appId": gid(), "displayName": actor, "servicePrincipalId": gid()}}
            if by_app
            else {"user": {"id": gid(), "userPrincipalName": actor, "ipAddress": IPS[i % 3]}}
        )
        result = "failure" if i % 9 == 8 else "success"
        rec = {
            "id": f"Directory_{gid()[:8]}",
            "category": cat,
            "correlationId": gid(),
            "result": result,
            "resultReason": "",
            "activityDisplayName": act,
            "activityDateTime": t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "loggedByService": "Conditional Access" if cat == "Policy" else "Core Directory",
            "operationType": optype,
            "initiatedBy": initiated,
            "targetResources": [{"id": gid(), "displayName": f"target-{i}", "type": "User", "userPrincipalName": USERS[(i + 1) % 4]}],
            "additionalDetails": [],
        }
        out.append(compact(rec))
        row: dict[str, Any] = {
            "parse_status": "ok",
            "class_uid": 3004,
            "actor_user_name": actor,
            "message": act,
            "status_id": 2 if result == "failure" else 1,
        }
        if not by_app:
            row["src_endpoint_ip"] = IPS[i % 3]
        if sev:
            row["severity_id"] = sev
        exp.append(row)
    return out, exp


# --- Graph alerts_v2 -----------------------------------------------------------------

ALERTS = [
    ("Suspicious inbox forwarding rule", "high", "microsoftDefenderForOffice365", "user"),
    ("Suspicious PowerShell command line", "medium", "microsoftDefenderForEndpoint", "device"),
    ("Atypical travel", "medium", "azureAdIdentityProtection", "user"),
    ("DLP policy match: credit card numbers", "low", "microsoftDataLossPrevention", "user"),
    ("Mass download by a single user", "informational", "microsoftDefenderForCloudApps", "none"),
]


def alerts() -> tuple[list[str], list[dict[str, Any]]]:
    out, exp = [], []
    t = START
    for i in range(52):
        t += timedelta(minutes=rng.randint(1, 30))
        title, sev, svc, kind = ALERTS[i % len(ALERTS)]
        user = USERS[i % len(USERS)]
        host = f"{HOSTS[i % 3].lower()}.corp.example"
        evidence: list[dict[str, Any]] = []
        if kind == "user":
            evidence = [{"@odata.type": "#microsoft.graph.security.userEvidence", "userAccount": {"userPrincipalName": user, "accountName": user.split("@")[0]}}]
        elif kind == "device":
            evidence = [{"@odata.type": "#microsoft.graph.security.deviceEvidence", "deviceDnsName": host}]
        rec = {
            "id": f"da{rng.getrandbits(64):016x}_{i}",
            "providerAlertId": gid(),
            "incidentId": str(1000 + i),
            "status": rng.choice(["new", "inProgress", "resolved"]),
            "severity": sev,
            "classification": None,
            "determination": None,
            "serviceSource": svc,
            "detectionSource": svc,
            "title": title,
            "description": f"{title} (synthetic)",
            "category": "SuspiciousActivity",
            "createdDateTime": iso_z(t),
            "lastUpdateDateTime": iso_z(t + timedelta(minutes=5)),
            "assignedTo": None,
            "evidence": evidence,
        }
        out.append(compact(rec))
        row: dict[str, Any] = {
            "parse_status": "ok",
            "class_uid": 2004,
            "message": title,
            "severity_id": {"informational": 1, "low": 2, "medium": 3, "high": 4}[sev],
            "time": iso_out(t),
        }
        if kind == "user":
            row["actor_user_name"] = user
        if kind == "device":
            row["device_hostname"] = host
        exp.append(row)
    return out, exp


# --- Anthropic -----------------------------------------------------------------------

MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
ACTS = ["api_key_created", "api_key_deleted", "user_invited", "workspace_created", "org_settings_updated"]


def anthropic() -> tuple[list[str], list[dict[str, Any]]]:
    out, exp = [], []
    for i in range(60):
        kind = ["usage", "cost", "claude_code", "analytics_users", "compliance_activities"][i % 5]
        hour = START - timedelta(hours=i // 5 + 1)
        day = (START - timedelta(days=i // 5 + 1)).replace(hour=0)
        user = USERS[i % len(USERS)]
        row: dict[str, Any] = {"parse_status": "ok", "class_uid": 6003, "message": f"anthropic.{kind}"}
        if kind == "usage":
            obj: dict[str, Any] = {
                "starting_at": iso_z(hour), "ending_at": iso_z(hour + timedelta(hours=1)),
                "model": MODELS[i % 3], "workspace_id": "wrkspc_01", "api_key_id": f"apikey_0{i % 3}",
                "service_tier": "standard", "uncached_input_tokens": rng.randint(100, 90000),
                "cache_read_input_tokens": rng.randint(0, 50000), "output_tokens": rng.randint(50, 20000),
                "server_tool_use": {"web_search_requests": rng.randint(0, 5)},
            }
            row |= {"actor_user_name": obj["api_key_id"], "time": iso_out(hour)}
        elif kind == "cost":
            obj = {
                "starting_at": iso_z(day), "ending_at": iso_z(day + timedelta(days=1)),
                "workspace_id": "wrkspc_01", "description": f"{MODELS[i % 3]} usage",
                "cost_type": "tokens", "currency": "USD", "amount": f"{rng.uniform(1, 400):.2f}",
            }
            row |= {"time": iso_out(day)}
        elif kind == "claude_code":
            obj = {
                "date": iso_z(day), "actor": {"type": "user_actor", "email_address": user},
                "organization_id": "org_01", "customer_type": "subscription", "terminal_type": rng.choice(["vscode", "iTerm.app", "WindowsTerminal"]),
                "core_metrics": {"num_sessions": rng.randint(1, 12), "lines_of_code": {"added": rng.randint(0, 900), "removed": rng.randint(0, 300)}, "commits_by_claude_code": rng.randint(0, 6), "pull_requests_by_claude_code": rng.randint(0, 2)},
                "model_breakdown": [{"model": MODELS[i % 3], "tokens": {"input": rng.randint(1000, 90000), "output": rng.randint(500, 20000)}, "estimated_cost": {"currency": "USD", "amount": rng.randint(5, 900)}}],
            }
            row |= {"actor_user_name": user, "time": iso_out(day)}
        elif kind == "analytics_users":
            obj = {
                "date": iso_z(day), "user": {"id": f"user_0{i % 4}", "email_address": user},
                "chat_metrics": {"distinct_conversation_count": rng.randint(0, 30), "message_count": rng.randint(0, 200)},
                "claude_code_metrics": {"core_metrics": {"distinct_session_count": rng.randint(0, 8)}},
            }
            row |= {"actor_user_name": user, "time": iso_out(day)}
        else:
            t = START + timedelta(minutes=i)
            obj = {
                "id": f"activity_{i:03d}", "created_at": iso_z(t), "organization_id": "org_01",
                "type": ACTS[i % len(ACTS)],
                "actor": {"type": "user_actor", "email_address": "admin@example.com", "ip_address": IPS[i % 3], "user_agent": "Mozilla/5.0"},
            }
            row |= {"actor_user_name": "admin@example.com", "src_endpoint_ip": IPS[i % 3], "message": obj["type"], "time": iso_out(t)}
        out.append(_rec(kind, obj, None).text)
        exp.append(row)
    return out, exp


# --- pathological lines --------------------------------------------------------------

def pathological(prefix: str) -> list[str]:
    return [
        "",
        "{",
        "not json at all",
        prefix + '"truncated',
        prefix + '"' + "A" * 10_000 + '"}',
        '{"CreationTime":12,"RecordType":"x","Workload":null,"UserId":["a"]}',
        '{"createdDateTime":"not a time","userPrincipalName":{},"conditionalAccessStatus":1,"status":"bad"}',
        '{"activityDateTime":"2026-13-45T99:00:00Z","activityDisplayName":null,"loggedByService":"x","initiatedBy":[]}',
        '{"detectionSource":"x","serviceSource":"y","createdDateTime":"","evidence":"none","severity":7}',
        '{"feed":"anthropic.usage","starting_at":null,"actor":"text"}',
        "[1,2,3]",
        "\x00\x01 binary \x1b[31m red",
        "  continued line of a multiline fragment",
    ]


README = """# {tid} fixtures

| | |
|---|---|
| Source product | {product} |
| Collector shape | {shape} |
| Generator | `scripts/fixtures/connectors.py` (seed 42) |
| Values | example.com users, invented ids, RFC 5737 and 2001:db8::/32 addresses |

Pathological lines cover empty and truncated JSON, wrong types, a 10 KB value, non-object
JSON, control characters, and a multiline fragment.
"""


def write(tid: str, sample: list[str], expected: list[dict[str, Any]], prefix: str, product: str, shape: str) -> None:
    folder = FIX / tid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sample.log").write_text("\n".join(sample) + "\n", encoding="utf-8")
    (folder / "expected.jsonl").write_text("\n".join(json.dumps(e, sort_keys=True) for e in expected[:10]) + "\n", encoding="utf-8")
    (folder / "pathological.log").write_text("\n".join(pathological(prefix)) + "\n", encoding="utf-8")
    (folder / "README.md").write_text(README.format(tid=tid, product=product, shape=shape), encoding="utf-8")


def main() -> None:
    graph = "One Graph resource per line, as the Microsoft 365 connector stores it"
    write("m365_management_activity", *management(), '{"CreationTime":"2026-10-14T17:00:00","RecordType":6,"Workload":"SharePoint","Operation":',
          "Office 365 Management Activity API (common schema), content types Audit.* and DLP.All", "One audit record per line, as the Microsoft 365 connector stores it")
    write("m365_signin", *signins(), '{"createdDateTime":"2026-10-14T17:00:00Z","userPrincipalName":"a@example.com","conditionalAccessStatus":"success","appDisplayName":',
          "Microsoft Graph v1.0 auditLogs/signIns", graph)
    write("m365_directory_audit", *audits(), '{"activityDateTime":"2026-10-14T17:00:00Z","loggedByService":"Core Directory","activityDisplayName":',
          "Microsoft Graph v1.0 auditLogs/directoryAudits", graph)
    write("m365_alert", *alerts(), '{"createdDateTime":"2026-10-14T17:00:00Z","detectionSource":"x","serviceSource":"y","title":',
          "Microsoft Graph v1.0 security/alerts_v2", graph)
    write("anthropic_reports", *anthropic(), '{"feed":"anthropic.compliance_activities","created_at":"2026-10-14T17:00:00Z","type":',
          "Anthropic Admin API usage and cost reports, Claude Code analytics, Enterprise analytics, Compliance activities",
          "One {\"feed\": \"anthropic.<feed>\", ...} JSON line per record, made by the connector record function")


if __name__ == "__main__":
    main()
