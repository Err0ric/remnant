#!/usr/bin/env python3
"""Synthetic logs for the demo install (`make demo`): one fictional company, two weeks.

    python3 scripts/demo/generate.py <folder>

Writes one folder per source under <folder>, with times ending now. Everything is
synthetic: the company is Example Corp at example.com, people are the reserved fictional
names, internal hosts are under corp.internal, the office is 198.51.100.0/24, and outside
addresses are documentation ranges (RFC 5737). Stdlib only.

What a viewer should find in it:
- password spraying against Microsoft 365 and SSH from 203.0.113.0/25 (one country, set by
  the demo GeoIP file), ending in one successful sign-in for frank
- a mail rule frank's account creates from that address: invoice mail forwarded outside
  and hidden in RSS Feeds
- an app consent from that address, blocked by policy
- DNS lookups of AI services, one of them never reviewed (chat.deepseek.com)
Claude Code hook and telemetry records are not files: `load.py` sends them over OTLP.
"""

from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

SEED = 2026
DAYS = 15  # over two weeks, so the 7-day pages have a whole week before to compare with
DOMAIN = "example.com"
PEOPLE = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan", "judy"]
DISPLAY = {p: p.capitalize() for p in PEOPLE}
WORKSTATION = {p: f"ws-{40 + i:04d}" for i, p in enumerate(PEOPLE)}
LAN = {p: f"10.20.{1 + i // 4}.{10 + i}" for i, p in enumerate(PEOPLE)}
OFFICE = [f"198.51.100.{n}" for n in (7, 8, 9)]  # the office's public addresses (NAT)
HOME = {"carol": "192.0.2.44", "ivan": "192.0.2.61"}  # two people work from home
ATTACK = [f"203.0.113.{n}" for n in range(20, 60, 3)]  # all in 203.0.113.0/25
VICTIM = "frank"
OUTSIDE = "mallory@example.net"
APPS = [
    ("00000003-0000-0ff1-ce00-000000000000", "Office 365 SharePoint Online"),
    ("00000002-0000-0ff1-ce00-000000000000", "Office 365 Exchange Online"),
    ("1fec8e78-bce4-4aaf-ab1b-5451cc387264", "Microsoft Teams"),
    ("d3590ed6-52b3-4102-aeff-aad2292ab01c", "Microsoft Office"),
]
SERVERS = ["bastion", "web-01", "db-01", "build-01"]
SITES = ["192.0.2.80", "198.51.100.120", "203.0.113.200", "192.0.2.150"]  # outside web hosts
AI_DOMAINS = [
    ("claude.ai", 30),
    ("api.anthropic.com", 18),
    ("chatgpt.com", 22),
    ("copilot.microsoft.com", 14),
    ("gemini.google.com", 8),
    ("chat.deepseek.com", 6),  # left unreviewed by load.py
]
WORK_DOMAINS = [
    "mail.example.com", "intranet.corp.internal", "files.corp.internal", "wiki.corp.internal",
    "login.microsoftonline.com", "outlook.office.com", "github.com", "docs.example.org",
]  # fmt: skip


def iso(t: datetime, ms: bool = True) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z" if ms else t.strftime("%Y-%m-%dT%H:%M:%S")


def rfc5424(t: datetime, pri: int, host: str, app: str, pid: int, msg: str) -> str:
    return f"<{pri}>1 {t.strftime('%Y-%m-%dT%H:%M:%SZ')} {host} {app} {pid} - - {msg}"


def company_shift(end: datetime) -> timedelta:
    """Company time minus UTC. The demo company's clock is set so that the moment the demo
    is generated is 15:00 on a Wednesday there: pages then look like a working afternoon
    whenever the demo runs, with the weekend dip in the middle of the week shown. Only UTC
    times are ever written; this shapes when the company is busy."""
    days = (2 - end.weekday()) % 7
    return timedelta(days=days, hours=15 - end.hour, minutes=-end.minute, seconds=-end.second)


def work_times(
    rng: random.Random, end: datetime, per_day: int, hourly: bool = True
) -> list[datetime]:
    """Weekday-heavy times on the company's clock, mostly 08:00 to 18:00 there, some around
    the clock, and at least one an hour so no source looks silent."""
    shift = company_shift(end)
    start = end - timedelta(days=DAYS)
    out = [
        start + timedelta(hours=h, seconds=rng.randrange(3600))
        for h in range(DAYS * 24 if hourly else 0)
    ]
    first = (start + shift).replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(DAYS + 2):
        day = first + timedelta(days=d)  # midnight on the company's clock
        n = per_day if day.weekday() < 5 else per_day // 3
        for _ in range(n):
            hour = rng.choice(range(8, 18)) if rng.random() < 0.8 else rng.randrange(24)
            out.append(day + timedelta(hours=hour, seconds=rng.randrange(3600)) - shift)
    return sorted(t for t in out if start <= t < end)


REASONS = {
    0: "Other.",
    50126: "Invalid username or password.",
    50053: "Account is locked.",
    50074: "Strong Authentication is required.",
    50140: "This error occurred due to 'Keep me signed in' interrupt when the user was signing in.",
    70043: "The refresh token has expired or is invalid due to sign-in frequency checks by conditional access.",
    50058: "Silent sign-in request was sent but no user is signed in.",
}
# Sign-ins an app makes in the background (token refreshes): not interactive.
BACKGROUND = (70043, 50058)
# The everyday noise of a tenant: MFA prompts and "stay signed in" interrupts, and expired
# sessions refreshed in the background, none of them real failures (D158).
NOISE = [(50074, 0.03), (50140, 0.03), (70043, 0.05), (50058, 0.04), (50126, 0.02)]


def signin(rng: random.Random, t: datetime, who: str, ip: str, code: int = 0, app: int | None = None, browser: str = "Edge 130.0") -> dict[str, object]:  # fmt: skip
    app_id, app_name = APPS[rng.randrange(len(APPS)) if app is None else app]
    reason = REASONS[code]
    return {
        "id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        "createdDateTime": iso(t),
        "userDisplayName": DISPLAY[who],
        "userPrincipalName": f"{who}@{DOMAIN}",
        "userId": str(uuid.UUID(int=PEOPLE.index(who) + 0xA000, version=4)),
        "appId": app_id,
        "appDisplayName": app_name,
        "ipAddress": ip,
        "clientAppUsed": "Browser",
        "correlationId": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
        "conditionalAccessStatus": "success" if code == 0 else "notApplied",
        "isInteractive": code not in BACKGROUND,
        "riskDetail": "none",
        "riskLevelAggregated": "none",
        "riskLevelDuringSignIn": "none",
        "riskState": "none",
        "status": {"errorCode": code, "failureReason": reason, "additionalDetails": None},
        "deviceDetail": {
            "deviceId": "",
            "displayName": WORKSTATION[who] if ip not in ATTACK else "",
            "operatingSystem": "Windows10" if ip not in ATTACK else "Linux",
            "browser": browser,
        },
        "location": {},  # the demo places addresses with its GeoIP file
    }


def m365(rng: random.Random, end: datetime, attack_at: datetime) -> dict[str, list[str]]:
    signins: list[dict[str, object]] = []
    for t in work_times(rng, end, 160):
        who = rng.choice(PEOPLE)
        ip = HOME.get(who, rng.choice(OFFICE)) if rng.random() < 0.95 else rng.choice(OFFICE)
        roll, code = rng.random(), 0
        for c, share in NOISE:  # MFA prompts, expired sessions, and a typo now and then
            if roll < share:
                code = c
                break
            roll -= share
        signins.append(signin(rng, t, who, ip, code))
    # Password spraying: every account, a few tries each, from rotating addresses, over
    # two hours; frank's password works on the last round.
    t = attack_at
    for rnd in range(6):
        for who in PEOPLE:
            t += timedelta(seconds=rng.randint(4, 30))
            ok = who == VICTIM and rnd == 5
            ip = ATTACK[-1] if ok else rng.choice(ATTACK)
            signins.append(signin(rng, t, who, ip, 0 if ok else 50126, 1, "Python Requests 2.32"))
        t += timedelta(minutes=rng.randint(12, 20))
    takeover = t
    signins.sort(key=lambda r: str(r["createdDateTime"]))

    audit: list[dict[str, object]] = []
    for i, t in enumerate(work_times(rng, end, 6, hourly=False)):
        actor, target = rng.choice(["alice", "bob"]), rng.choice(PEOPLE)
        act = rng.choice([("UserManagement", "Update user", "Update"), ("GroupManagement", "Add member to group", "Assign")])  # fmt: skip
        audit.append({
            "id": f"Directory_{rng.getrandbits(32):08x}", "category": act[0],
            "correlationId": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "result": "success", "resultReason": "", "activityDisplayName": act[1],
            "activityDateTime": iso(t), "loggedByService": "Core Directory", "operationType": act[2],
            "initiatedBy": {"user": {"id": f"u-{actor}", "userPrincipalName": f"{actor}@{DOMAIN}", "ipAddress": OFFICE[0]}},
            "targetResources": [{"id": f"t-{i}", "displayName": DISPLAY[target], "type": "User", "userPrincipalName": f"{target}@{DOMAIN}"}],
            "additionalDetails": [],
        })  # fmt: skip
    consent_at = takeover + timedelta(minutes=9)
    audit.append({
        "id": "Directory_c0000001", "category": "ApplicationManagement",
        "correlationId": "7f1c2e4a-0000-4000-8000-00000000c001", "result": "failure",
        "resultReason": "Microsoft.Online.Security.AuthorizationException",
        "activityDisplayName": "Consent to application", "activityDateTime": iso(consent_at),
        "loggedByService": "Core Directory", "operationType": "Assign",
        "initiatedBy": {"user": {"id": f"u-{VICTIM}", "userPrincipalName": f"{VICTIM}@{DOMAIN}", "ipAddress": ATTACK[-1]}},
        "targetResources": [{
            "id": "5b1e0000-0000-4000-8000-00000000a001", "displayName": "Mail Sync Pro", "type": "ServicePrincipal",
            "modifiedProperties": [
                {"displayName": "ConsentContext.IsAdminConsent", "oldValue": None, "newValue": '"False"'},
                {"displayName": "ConsentAction.Permissions", "oldValue": None, "newValue": '"[] => [[Scope: Mail.ReadWrite Mail.Send offline_access User.Read]]; "'},
            ],
        }],
        "additionalDetails": [{"key": "User-Agent", "value": "python-requests/2.32"}, {"key": "AppId", "value": "0a1b2c3d-0000-4000-8000-0000000000a1"}],
    })  # fmt: skip

    def change(t: datetime, cat: str, act: str, optype: str, actor: str | None, target: dict[str, object], props: dict[str, str] | None = None, app: str | None = None) -> None:  # fmt: skip
        if actor:
            by: dict[str, object] = {"user": {"id": f"u-{actor}", "userPrincipalName": f"{actor}@{DOMAIN}", "ipAddress": OFFICE[0]}}  # fmt: skip
        else:
            by = {"app": {"appId": None, "displayName": app, "servicePrincipalId": "9c1a0000-0000-4000-8000-0000000000e1", "servicePrincipalName": None}}  # fmt: skip
        mods = [{"displayName": k, "oldValue": None, "newValue": json.dumps(v)} for k, v in (props or {}).items()]  # fmt: skip
        audit.append({
            "id": f"Directory_{rng.getrandbits(32):08x}", "category": cat,
            "correlationId": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "result": "success", "resultReason": "", "activityDisplayName": act,
            "activityDateTime": iso(t), "loggedByService": "Core Directory", "operationType": optype,
            "initiatedBy": by, "targetResources": [{**target, "modifiedProperties": mods}], "additionalDetails": [],
        })  # fmt: skip

    def user(who: str) -> dict[str, object]:
        return {"id": f"t-{who}", "displayName": DISPLAY[who], "type": "User", "userPrincipalName": f"{who}@{DOMAIN}"}  # fmt: skip

    # Admin work: a role grant, a policy change, a new hire synced from Active Directory,
    # and the response to frank's account (password reset, sign-in blocked).
    change(end - timedelta(days=5, hours=3), "RoleManagement", "Add member to role", "Assign", "alice", user("heidi"), {"Role.DisplayName": "Exchange Administrator"})  # fmt: skip
    change(end - timedelta(days=4, hours=6), "Policy", "Update conditional access policy", "Update", "alice", {"id": "ca-01", "displayName": "Block legacy authentication", "type": "Policy"}, {"ConditionalAccessPolicy": "enabled"})  # fmt: skip
    change(end - timedelta(days=3, hours=2), "UserManagement", "Add user", "Add", None, user("judy"), {"AccountEnabled": "true", "DirSyncEnabled": "true", "OnPremisesObjectIdentifier": "3f2a0000-0000-4000-8000-00000000d001"}, "Microsoft Entra Connect sync")  # fmt: skip
    for h in range(0, DAYS * 24, 3):
        change(end - timedelta(hours=h, minutes=7), "Synchronization", "Export", "Update", None, {"id": "sync-01", "displayName": "corp.internal", "type": "Directory"}, None, "Microsoft Entra Connect sync")  # fmt: skip
    response = takeover + timedelta(hours=6)
    change(response, "UserManagement", "Reset user password", "Update", "bob", user(VICTIM))
    change(response + timedelta(minutes=2), "UserManagement", "Disable account", "Update", "bob", user(VICTIM), {"AccountEnabled": "false"})  # fmt: skip
    change(response + timedelta(minutes=3), "UserManagement", "Update user", "Update", "bob", user(VICTIM), {"StsRefreshTokensValidFrom": "now"})  # fmt: skip
    audit = [a for a in audit if str(a["activityDateTime"]) < iso(end)]
    audit.sort(key=lambda r: str(r["activityDateTime"]))

    ops: list[dict[str, object]] = []
    for t in work_times(rng, end, 120):
        who = rng.choice(PEOPLE)
        op, wl, rt = rng.choice([("FileAccessed", "SharePoint", 6), ("FileModified", "SharePoint", 6), ("MailItemsAccessed", "Exchange", 2), ("FileDownloaded", "SharePoint", 6)])  # fmt: skip
        rec: dict[str, object] = {"CreationTime": iso(t, ms=False), "Id": str(uuid.UUID(int=rng.getrandbits(128), version=4)), "Operation": op, "OrganizationId": "00000000-0000-4000-8000-0000000000aa", "RecordType": rt, "UserKey": f"k-{who}", "UserType": 0, "Version": 1, "Workload": wl, "UserId": f"{who}@{DOMAIN}", "ClientIP": HOME.get(who, OFFICE[0])}  # fmt: skip
        if wl == "SharePoint":
            rec["ObjectId"] = f"https://intranet.example.com/sites/team/doc{rng.randrange(40)}.docx"
        ops.append(rec)
    for i, (who, name, folder) in enumerate(
        [("carol", "Newsletters", "Newsletters"), ("ivan", "Build mail", "CI")]
    ):
        t = end - timedelta(days=3 + i, hours=4)
        ops.append({"CreationTime": iso(t, ms=False), "Id": str(uuid.UUID(int=rng.getrandbits(128), version=4)), "Operation": "New-InboxRule", "OrganizationId": "00000000-0000-4000-8000-0000000000aa", "RecordType": 1, "UserKey": f"k-{who}", "UserType": 0, "Version": 1, "Workload": "Exchange", "UserId": f"{who}@{DOMAIN}", "ResultStatus": "True", "ClientIP": HOME.get(who, OFFICE[0]), "Parameters": [{"Name": "Name", "Value": name}, {"Name": "MoveToFolder", "Value": folder}]})  # fmt: skip
    rule_at = takeover + timedelta(minutes=4)
    ops.append({
        "CreationTime": iso(rule_at, ms=False), "Id": "6b2f3a10-0000-4000-8000-00000000be01",
        "Operation": "New-InboxRule", "OrganizationId": "00000000-0000-4000-8000-0000000000aa",
        "RecordType": 1, "UserKey": f"k-{VICTIM}", "UserType": 0, "Version": 1, "Workload": "Exchange",
        "UserId": f"{VICTIM}@{DOMAIN}", "ResultStatus": "True", "ClientIP": ATTACK[-1],
        "Parameters": [
            {"Name": "Name", "Value": "."},
            {"Name": "SubjectOrBodyContainsWords", "Value": "invoice;wire transfer;payment"},
            {"Name": "ForwardTo", "Value": OUTSIDE},
            {"Name": "MoveToFolder", "Value": "RSS Feeds"},
            {"Name": "MarkAsRead", "Value": "True"},
            {"Name": "StopProcessingRules", "Value": "True"},
        ],
    })  # fmt: skip
    ops.sort(key=lambda r: str(r["CreationTime"]))
    dump = lambda rows: [json.dumps(r, separators=(",", ":")) for r in rows]  # noqa: E731
    return {"m365_signin": dump(signins), "m365_directory_audit": dump(audit), "m365_management_activity": dump(ops)}  # fmt: skip


def sshd(rng: random.Random, end: datetime, attack_at: datetime) -> list[str]:
    lines: list[tuple[datetime, str]] = []
    for t in work_times(rng, end, 40):
        who = rng.choice(["alice", "bob", "dave", "deploy"])
        src = LAN.get(who, "10.20.9.5")
        host = rng.choice(SERVERS)
        pid = rng.randint(2000, 60000)
        lines.append((t, rfc5424(t, 38, host, "sshd", pid, f"Accepted publickey for {who} from {src} port {rng.randint(40000, 65000)} ssh2: ED25519 SHA256:Zm9vYmFyZXhhbXBsZQ")))  # fmt: skip
        lines.append((t + timedelta(minutes=rng.randint(5, 90)), rfc5424(t, 38, host, "sshd", pid, f"Disconnected from user {who} {src} port {rng.randint(40000, 65000)}")))  # fmt: skip
    # SSH brute force against the bastion, the night before the Microsoft 365 spraying.
    t = attack_at - timedelta(hours=7)
    names = ["root", "admin", "ubuntu", "oracle", "test", "postgres", "git", "deploy", "frank"]
    for i in range(420):
        t += timedelta(seconds=rng.randint(2, 12))
        ip, name, port = rng.choice(ATTACK), rng.choice(names), rng.randint(20000, 65000)
        pid = rng.randint(2000, 60000)
        if name in ("root", "deploy", "frank"):
            msg = f"Failed password for {name} from {ip} port {port} ssh2"
        else:
            msg = f"Failed password for invalid user {name} from {ip} port {port} ssh2"
        lines.append((t, rfc5424(t, 38, "bastion", "sshd", pid, msg)))
        if i % 6 == 0 and name not in ("root", "deploy", "frank"):
            lines.append(
                (
                    t,
                    rfc5424(
                        t, 38, "bastion", "sshd", pid, f"Invalid user {name} from {ip} port {port}"
                    ),
                )
            )
    lines.sort()
    return [line for _, line in lines]


def palo(rng: random.Random, end: datetime, attack_at: datetime) -> list[str]:
    def row(t: datetime, src: str, dst: str, user: str, app: str, port: int, action: str, rule: str, kind: str) -> str:  # fmt: skip
        stamp = t.strftime("%Y/%m/%d %H:%M:%S")
        return (
            f"<14>1 {t.strftime('%Y-%m-%dT%H:%M:%SZ')} pa-fw01 - - - - 1,{stamp},012345678901,TRAFFIC,{kind},,{stamp},"
            f"{src},{dst},,,{rule},{user},,{app},vsys1,trust,untrust,,,,,{rng.randint(1000, 99999)},1,"
            f"{rng.randint(40000, 65000)},{port},,,,tcp,{action},{rng.randint(400, 90000)},,,,,,,,,,,"
            '"United States, US",,,,n/a,,,,,,pa-fw01'
        )

    out: list[tuple[datetime, str]] = []
    for t in work_times(rng, end, 260):
        who = rng.choice(PEOPLE)
        app, port = rng.choice(
            [("ssl", 443), ("web-browsing", 80), ("ssl", 443), ("ms-office365", 443)]
        )
        out.append((t, row(t, LAN[who], rng.choice(SITES), f"corp\\{who}", app, port, "allow", "allow-web", "end")))  # fmt: skip
    t = attack_at - timedelta(hours=7)
    for _ in range(60):  # the same addresses probing the edge
        t += timedelta(seconds=rng.randint(20, 120))
        port = rng.choice([3389, 445, 22, 8443])
        out.append((t, row(t, rng.choice(ATTACK), "198.51.100.7", "", "incomplete", port, "deny", "block-inbound", "deny")))  # fmt: skip
    out.sort()
    return [line for _, line in out]


def dns(rng: random.Random, end: datetime) -> list[str]:
    out: list[tuple[datetime, str]] = []
    weights = [w for _, w in AI_DOMAINS]
    for t in work_times(rng, end, 220):
        who = rng.choice(PEOPLE)
        name = rng.choices([d for d, _ in AI_DOMAINS], weights)[0] if rng.random() < 0.3 else rng.choice(WORK_DOMAINS)  # fmt: skip
        if name == "chat.deepseek.com" and who not in ("heidi", "judy"):
            name = "claude.ai"  # two people use the unreviewed service
        qtype = rng.choice(["A", "A", "AAAA"])
        out.append((t, rfc5424(t, 30, "ns1", "named", 800, f"client @0x7f2a1c0a00{rng.randrange(99):02d} {LAN[who]}#{rng.randint(1024, 65000)} ({name}): query: {name} IN {qtype} +E(0)K (10.20.0.53)")))  # fmt: skip
    out.sort()
    return [line for _, line in out]


def generate(folder: Path, end: datetime | None = None) -> dict[str, int]:
    rng = random.Random(SEED)
    end = (end or datetime.now(UTC)).replace(microsecond=0)
    # The spraying starts at 02:10 two days ago on the company's clock, outside office hours.
    shift = company_shift(end)
    attack_at = ((end + shift - timedelta(days=2)).replace(hour=2, minute=10, second=0)) - shift
    files = m365(rng, end, attack_at)
    files["linux_sshd"] = sshd(rng, end, attack_at)
    files["paloalto_traffic"] = palo(rng, end, attack_at)
    files["dns_bind"] = dns(rng, end)
    counts = {}
    for tid, lines in files.items():
        d = folder / tid
        d.mkdir(parents=True, exist_ok=True)
        (d / "demo.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        counts[tid] = len(lines)
    return counts


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for tid, n in generate(Path(sys.argv[1])).items():
        print(f"{tid}: {n} lines")


if __name__ == "__main__":
    main()
