"""Generate starter-template fixtures (CLAUDE.md section 6, Templates row).

    python scripts/fixtures/starter_pack.py backend/tests/fixtures/logs [template_id ...]

For each template: sample.log (50+ real-shaped lines with synthetic values),
expected.jsonl (what the first 10 lines must parse to, written from what the generator
put in each line, not from the template), and pathological.log. Deterministic per seed.
Values: invented hosts and users, RFC 1918 internal and RFC 5737 external addresses.
"""

import json
import random
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

INTERNAL = ("10.20.1.5", "10.20.1.6", "10.20.2.14", "10.20.3.30")
EXTERNAL = ("203.0.113.9", "198.51.100.4", "203.0.113.77", "192.0.2.10")
USERS = ("alice", "bob", "carol", "dave")
HOSTS = ("web-01", "db-01", "bastion")

COMMON_PATHOLOGICAL = [
    "",
    " ",
    "<13>",
    "x" * 10_240,
    "\x00\x01\x02\x1b[31mred\x1b[0m",
    "  continuation of a multiline message without a header",
    "<999>Oct  9 20:41:12 host app[1]: out of range priority",
]


class Sample:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311  # deterministic test data
        self.t = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
        self.lines: list[str] = []
        self.expected: list[dict[str, Any]] = []

    def tick(self) -> datetime:
        self.t += timedelta(seconds=self.rng.randrange(1, 90))
        return self.t

    def bsd(self, pri: int, host: str, tag: str, msg: str, exp: dict[str, Any]) -> None:
        t = self.tick()
        self.lines.append(f"<{pri}>{t:%b} {t.day:>2} {t:%H:%M:%S} {host} {tag}: {msg}")
        self.expected.append({"time": t.isoformat(), "device_hostname": host, **exp})

    def bsd_untagged(self, pri: int, host: str, msg: str, exp: dict[str, Any]) -> None:
        """Devices that put the payload right after the host, like `fw01 CEF:0|...`."""
        t = self.tick()
        self.lines.append(f"<{pri}>{t:%b} {t.day:>2} {t:%H:%M:%S} {host} {msg}")
        self.expected.append({"time": t.isoformat(), "device_hostname": host, **exp})

    def ietf(self, pri: int, host: str, app: str, msg: str, exp: dict[str, Any]) -> None:
        t = self.tick()
        self.lines.append(f"<{pri}>1 {t:%Y-%m-%dT%H:%M:%SZ} {host} {app} - - - {msg}")
        self.expected.append({"time": t.isoformat(), "device_hostname": host, **exp})

    def write(self, out: Path, pathological: list[str]) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "sample.log").write_text("\n".join(self.lines) + "\n")
        with (out / "expected.jsonl").open("w") as fh:
            for exp in self.expected[:10]:
                fh.write(json.dumps(exp, sort_keys=True) + "\n")
        (out / "pathological.log").write_text("\n".join(COMMON_PATHOLOGICAL + pathological) + "\n")


def linux_sudo(out: Path) -> None:
    s = Sample(21)
    commands = ("/usr/bin/systemctl restart nginx", "/usr/bin/apt update", "/bin/journalctl -u ssh")
    for i in range(60):
        host, user, pid = s.rng.choice(HOSTS), s.rng.choice(USERS), s.rng.randrange(1000, 60000)
        tag = f"sudo[{pid}]"
        kind = s.rng.choice(("run", "run", "run", "badpw", "nosudo", "session", "notty"))
        cmd = s.rng.choice(commands)
        if kind == "run":
            s.bsd(85, host, tag, f"{user:>8} : TTY=pts/{i % 4} ; PWD=/home/{user} ; USER=root ; COMMAND={cmd}",
                  {"actor_user_name": user, "class_uid": 1007, "status_id": 1, "parse_status": "ok"})
        elif kind == "notty":
            s.bsd(85, host, tag, f"{user} : PWD=/srv ; USER=postgres ; COMMAND={cmd}",
                  {"actor_user_name": user, "class_uid": 1007, "status_id": 1, "parse_status": "ok"})
        elif kind == "badpw":
            n = s.rng.randrange(1, 4)
            word = "attempt" if n == 1 else "attempts"
            s.bsd(85, host, tag, f"{user:>8} : {n} incorrect password {word} ; TTY=pts/1 ; PWD=/home/{user} ; USER=root ; COMMAND={cmd}",
                  {"actor_user_name": user, "class_uid": 3002, "status_id": 2, "parse_status": "ok"})
        elif kind == "nosudo":
            s.bsd(85, host, tag, f"{user:>8} : user NOT in sudoers ; TTY=pts/2 ; PWD=/tmp ; USER=root ; COMMAND=/bin/bash",
                  {"actor_user_name": user, "class_uid": 3002, "status_id": 2, "parse_status": "ok"})
        else:
            what = s.rng.choice(("opened", "closed"))
            by = f" by {user}(uid=1000)" if what == "opened" else ""
            s.bsd(86, host, tag, f"pam_unix(sudo:session): session {what} for user root(uid=0){by}" if what == "opened" else f"pam_unix(sudo:session): session closed for user root",
                  {"class_uid": 3002, "status_id": 1, "activity_id": 1 if what == "opened" else 2, "parse_status": "ok"})
    s.bsd(85, "web-01", "sudo[1]", "unable to resolve host web-01: Name or service not known", {"parse_status": "envelope_only"})
    s.write(out, [
        "<85>Oct  9 20:41:12 web-01 sudo[1]: " + "a" * 9000 + " : TTY=pts/0 ; PWD=/ ; USER=root ; COMMAND=/bin/true",
        "<85>Oct  9 20:41:12 web-01 sudo[1]: x : TTY=" + ";" * 5000,
        "<85>Oct  9 20:41:12 web-01 sudo[1]: x : 99999999999999999999 incorrect password attempts ; USER=root",
    ])


def linux_pam(out: Path) -> None:
    s = Sample(22)
    for i in range(60):
        host, user, pid = s.rng.choice(HOSTS), s.rng.choice(USERS), s.rng.randrange(1000, 60000)
        kind = s.rng.choice(("authfail", "session", "cron", "passwd", "faillock", "su_ok", "su_fail"))
        if kind == "authfail":
            s.bsd(85, host, f"su[{pid}]", f"pam_unix(su:auth): authentication failure; logname={user} uid=1001 euid=0 tty=pts/1 ruser={user} rhost=  user=root",
                  {"actor_user_name": "root", "status_id": 2, "class_uid": 3002, "parse_status": "ok"})
        elif kind == "session":
            what = s.rng.choice(("opened", "closed"))
            s.bsd(86, host, f"login[{pid}]", f"pam_unix(login:session): session {what} for user {user}" + ("(uid=1000) by LOGIN(uid=0)" if what == "opened" else ""),
                  {"status_id": 1, "activity_id": 1 if what == "opened" else 2, "class_uid": 3002, "parse_status": "ok"})
        elif kind == "cron":
            s.bsd(86, host, f"CRON[{pid}]", "pam_unix(cron:session): session opened for user root(uid=0) by (uid=0)",
                  {"status_id": 1, "activity_id": 1, "class_uid": 3002, "parse_status": "ok"})
        elif kind == "passwd":
            s.bsd(86, host, f"passwd[{pid}]", f"pam_unix(passwd:chauthtok): password changed for {user}",
                  {"actor_user_name": user, "class_uid": 3001, "activity_id": 3, "parse_status": "ok"})
        elif kind == "faillock":
            s.bsd(84, host, f"login[{pid}]", f"pam_faillock(login:auth): Consecutive login failures for user {user} account temporarily locked",
                  {"actor_user_name": user, "class_uid": 3001, "activity_id": 9, "parse_status": "ok"})
        elif kind == "su_ok":
            s.bsd(86, host, f"su[{pid}]", f"(to root) {user} on pts/{i % 4}",
                  {"actor_user_name": user, "status_id": 1, "class_uid": 3002, "parse_status": "ok"})
        else:
            s.bsd(85, host, f"su[{pid}]", f"FAILED SU (to root) {user} on pts/{i % 4}",
                  {"actor_user_name": user, "status_id": 2, "class_uid": 3002, "parse_status": "ok"})
    s.bsd(86, "web-01", "su[2]", "+ pts/1 alice:root", {"parse_status": "envelope_only"})
    s.write(out, [
        "<85>Oct  9 20:41:12 h su[1]: pam_unix(su:auth): authentication failure;" + " x=y" * 3000,
        "<85>Oct  9 20:41:12 h su[1]: pam_unix(" + "(" * 5000,
        "<85>Oct  9 20:41:12 h su[1]: FAILED SU (to " + "r" * 9000,
    ])


def cef_generic(out: Path) -> None:
    s = Sample(23)
    products = (("ExampleCorp", "EdgeWall", "5.2"), ("ExampleCorp", "Sensor|IDS", "1.0"), ("ExampleSec", "Proxy", "7.1"))
    for i in range(60):
        vendor, product, version = s.rng.choice(products)
        src, dst = s.rng.choice(EXTERNAL), s.rng.choice(INTERNAL)
        spt, dpt = s.rng.randrange(1024, 65535), s.rng.choice((22, 80, 443, 3389))
        sev = s.rng.randrange(0, 11)
        name = s.rng.choice(("Connection denied", "Port scan | sweep", "Malware blocked", "Policy allowed"))
        esc = lambda v: v.replace("\\", "\\\\").replace("|", "\\|")  # noqa: E731
        ext = f"src={src} spt={spt} dst={dst} dpt={dpt} suser={s.rng.choice(USERS)} msg=Rule {i} matched for host\\=edge"
        line = f"CEF:0|{esc(vendor)}|{esc(product)}|{version}|sig-{i % 7}|{esc(name)}|{sev}|{ext}"
        exp = {"src_endpoint_ip": src, "src_endpoint_port": spt, "dst_endpoint_port": dpt,
               "message": f"Rule {i} matched for host=edge", "parse_status": "ok",
               "severity_id": {0: 1, 1: 2, 2: 2, 3: 2, 4: 3, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5}[sev]}
        if i % 5 == 0:
            s.ietf(132, "fw01", "edgewall", line, exp)
        else:
            s.bsd_untagged(132, "fw01", line, exp)
    s.write(out, [
        "<132>Oct  9 20:41:12 fw01 CEF:0|" + "\\|" * 4000,
        "<132>Oct  9 20:41:12 fw01 CEF:0|V|P|1|s|n|5|" + "a=" * 4000,
        "<132>Oct  9 20:41:12 fw01 CEF:0|V|P|1|s|n|5|spt=99999999999999999999999 dpt=-1",
        "<132>Oct  9 20:41:12 fw01 CEF:0|V|P",
    ])


def leef_generic(out: Path) -> None:
    s = Sample(24)
    for i in range(60):
        src, dst = s.rng.choice(INTERNAL), s.rng.choice(EXTERNAL)
        sp, dp, sev = s.rng.randrange(1024, 65535), s.rng.choice((53, 443, 25)), s.rng.randrange(1, 11)
        user = s.rng.choice(USERS)
        exp = {"src_endpoint_ip": src, "dst_endpoint_port": dp, "actor_user_name": user, "parse_status": "ok",
               "severity_id": {1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 3, 7: 4, 8: 4, 9: 5, 10: 5}[sev]}
        if i % 3 == 0:
            body = f"1.0|ExampleCorp|MailGuard|3.1|MAIL_{i % 4}|src={src}\tdst={dst}\tsrcPort={sp}\tdstPort={dp}\tusrName={user}\tsev={sev}"
        elif i % 3 == 1:
            body = f"2.0|ExampleCorp|FlowWatch|2.0|{40 + i % 3}|^|src={src}^dst={dst}^srcPort={sp}^dstPort={dp}^usrName={user}^sev={sev}"
        else:
            body = f"2.0|ExampleCorp|FlowWatch|2.0|{40 + i % 3}|x09|src={src}\tdst={dst}\tsrcPort={sp}\tdstPort={dp}\tusrName={user}\tsev={sev}"
        s.bsd_untagged(13, s.rng.choice(("mail01", "nta01")), "LEEF:" + body, exp)
    s.write(out, [
        "<13>Oct  9 20:41:12 nta01 LEEF:2.0|V|P|1|E|^|" + "^" * 9000,
        "<13>Oct  9 20:41:12 nta01 LEEF:1.0|V|P|1|E|" + "k=v\t" * 2500,
        "<13>Oct  9 20:41:12 nta01 LEEF:7.0|V|P|1|E|a=b",
    ])


def json_over_syslog(out: Path) -> None:
    s = Sample(25)
    levels = {"debug": 1, "info": 1, "warning": 3, "error": 4, "critical": 5}
    for i in range(60):
        level = s.rng.choice(list(levels))
        user = s.rng.choice(USERS)
        src = s.rng.choice(INTERNAL)
        doc = {"msg": s.rng.choice(("login", "payment failed", "export started", "cache miss")),
               "level": level, "user": user, "src_ip": src, "src_port": str(s.rng.randrange(1024, 65535)),
               "request": {"id": f"r-{i}", "path": "/api/v1/orders", "ms": s.rng.randrange(1, 900)}}
        exp = {"message": doc["msg"], "actor_user_name": user, "src_endpoint_ip": src,
               "src_endpoint_port": int(doc["src_port"]), "severity_id": levels[level], "parse_status": "ok"}
        text = json.dumps(doc)
        if i % 4 == 0:
            s.ietf(134, "app01", "api", text, exp)
        elif i % 4 == 1:
            s.bsd(134, "app01", f"billing[{300 + i}]", "@cee: " + text, exp)
        else:
            s.bsd(134, "app02", f"api[{400 + i}]", text, exp)
    s.bsd(134, "app01", "api[1]", "starting worker pool", {"parse_status": "envelope_only"})
    s.write(out, [
        "<134>Oct  9 20:41:12 app01 api[1]: " + "{" * 9000,
        '<134>Oct  9 20:41:12 app01 api[1]: {"msg": "\\ud800", "n": NaN, "big": 1e999}',
        '<134>Oct  9 20:41:12 app01 api[1]: {"src_port": "99999999999999999999999999"}',
        "<134>Oct  9 20:41:12 app01 api[1]: @cee: not json",
    ])


def _epoch_ns(t: datetime) -> int:
    return int(t.timestamp()) * 10**9


def fortinet_fortigate(out: Path) -> None:
    s = Sample(26)
    sev = {"emergency": 5, "alert": 5, "critical": 5, "error": 4, "warning": 3, "notice": 2, "information": 1}
    for i in range(60):
        t = s.tick()
        kind = s.rng.choice(("fwd", "fwd", "fwd", "local_deny", "vpn_fail", "user_ok"))
        unit = (i % 3)  # eventtime in s, ms, ns across FortiOS releases
        et = int(t.timestamp()) * (1, 10**3, 10**9)[unit]
        head = f'date={t:%Y-%m-%d} time={t:%H:%M:%S} devname="FGT60F-HQ" devid="FGT60F0000000001" eventtime={et} tz="+0000"'
        if kind == "fwd":
            src, dst = s.rng.choice(INTERNAL), s.rng.choice(EXTERNAL)
            sp, dp = s.rng.randrange(1024, 65535), s.rng.choice((443, 80, 53))
            action = s.rng.choice(("close", "accept", "timeout"))
            body = (f'{head} logid="0000000013" type="traffic" subtype="forward" level="notice" vd="root" srcip={src} srcport={sp} '
                    f'srcintf="internal" dstip={dst} dstport={dp} dstintf="wan1" sessionid={1000 + i} proto=6 action="{action}" '
                    f'policyid=1 service="HTTPS" sentbyte={s.rng.randrange(100, 9000)} rcvdbyte={s.rng.randrange(100, 90000)}')
            exp = {"class_uid": 4001, "src_endpoint_ip": src, "dst_endpoint_port": dp, "status_id": 1, "severity_id": 2}
        elif kind == "local_deny":
            src = s.rng.choice(EXTERNAL)
            body = (f'{head} logid="0001000014" type="traffic" subtype="local" level="warning" srcip={src} '
                    f'srcport={s.rng.randrange(1024, 65535)} dstip=192.0.2.1 dstport=22 action="deny" policyid=0')
            exp = {"class_uid": 4001, "src_endpoint_ip": src, "status_id": 2, "severity_id": 3}
        elif kind == "vpn_fail":
            user = s.rng.choice(USERS)
            body = (f'{head} logid="0101039426" type="event" subtype="vpn" level="alert" logdesc="SSL VPN login fail" '
                    f'action="ssl-login-fail" tunneltype="ssl-web" remip={s.rng.choice(EXTERNAL)} user="{user}" '
                    f'reason="sslvpn_login_permission_denied" msg="SSL user failed to logged in"')
            exp = {"class_uid": 3002, "actor_user_name": user, "status_id": 2, "severity_id": 5}
        else:
            user = s.rng.choice(USERS)
            body = (f'{head} logid="0102043039" type="event" subtype="user" level="information" logdesc="Authentication success" '
                    f'srcip={s.rng.choice(INTERNAL)} user="{user}" action="authentication" status="success" '
                    f'msg="User {user} succeeded in authentication"')
            exp = {"class_uid": 3002, "actor_user_name": user, "status_id": 1, "severity_id": 1}
        pri = 184 + {"notice": 5, "warning": 4, "alert": 1, "information": 6}[body.split('level="')[1].split('"')[0]]
        s.lines.append(f"<{pri}>{body}")
        s.expected.append({"time": t.isoformat(), "device_hostname": "FGT60F-HQ", "parse_status": "ok", **exp})
    s.write(out, [
        '<189>date=2026-10-09 time=20:41:12 devname="' + '\\"' * 3000,
        "<189>" + "a=1 " * 2400,
        '<189>logid="0000000013" type="traffic" subtype="forward" eventtime=99999999999999999999999 srcport=99999999999999999999',
        '<189>msg="never closed ' + "x" * 9000,
    ])


def unifi(out: Path) -> None:
    s = Sample(27)
    for i in range(60):
        kind = s.rng.choice(("wan_in", "wan_local", "lan_in", "icmp"))
        mac = "00:00:5e:00:53:01:00:00:5e:00:53:02:08:00"
        if kind == "icmp":
            src = s.rng.choice(EXTERNAL)
            msg = f"[WAN_LOCAL-default-D]IN=eth2 OUT= MAC={mac} SRC={src} DST=192.0.2.1 LEN=84 TOS=0x00 PREC=0x00 TTL=55 ID=0 PROTO=ICMP TYPE=8 CODE=0 ID=1 SEQ={i}"
            exp = {"src_endpoint_ip": src, "status_id": 2, "dst_endpoint_port": None}
            s.bsd(4, "USG-Pro", "kernel", msg, {**exp, "parse_status": "ok"})
            continue
        sp, dp = s.rng.randrange(1024, 65535), s.rng.choice((22, 443, 445, 3389))
        if kind == "lan_in":
            src, dst, rule, letter = s.rng.choice(INTERNAL), "10.20.1.9", f"LAN_IN-A-{4000 + i % 3}", "A"
            msg = f'[{rule}] DESCR="Allow IoT to NAS" IN=br20 OUT=br10 MAC={mac} SRC={src} DST={dst} LEN=52 TOS=00 PREC=0x00 TTL=63 ID=0 DF PROTO=TCP SPT={sp} DPT={dp} SEQ=1 ACK=0 WINDOW=64240 SYN URGP=0'
            exp = {"src_endpoint_ip": src, "dst_endpoint_port": dp, "status_id": 1, "parse_status": "ok"}
            s.bsd_untagged(4, "UDM-SE", msg, exp)
        else:
            src, dst = s.rng.choice(EXTERNAL), s.rng.choice(INTERNAL)
            rule = "WAN_IN-2000-D" if kind == "wan_in" else "WAN_LOCAL-default-D"
            msg = f"[{rule}]IN=eth2 OUT=eth0 MAC={mac} SRC={src} DST={dst} LEN=60 TOS=0x00 PREC=0x00 TTL=52 ID={i} DF PROTO=TCP SPT={sp} DPT={dp} WINDOW=64240 RES=0x00 SYN URGP=0"
            s.bsd(4, "USG-Pro", "kernel", msg, {"src_endpoint_ip": src, "dst_endpoint_port": dp, "status_id": 2, "parse_status": "ok"})
    s.write(out, [
        "<4>Oct  9 20:41:12 USG kernel: [" + "A" * 9000 + "]IN=",
        "<4>Oct  9 20:41:12 USG kernel: [WAN_IN-2000-D]IN=eth2 OUT= " + "X=1 " * 2400,
        "<4>Oct  9 20:41:12 USG kernel: [WAN_IN-2000-D]IN=eth2 OUT= SRC=203.0.113.4 DST=198.51.100.8 PROTO=TCP SPT=99999999999999999999 DPT=1",
    ])


def dns_bind(out: Path) -> None:
    s = Sample(28)
    names = ("www.example.com", "mail.example.com", "intranet.example.internal", "xj3k9q2v.example.org")
    for i in range(60):
        src, name = s.rng.choice(INTERNAL), s.rng.choice(names)
        port = s.rng.randrange(1024, 65535)
        qtype = s.rng.choice(("A", "AAAA", "MX", "TXT"))
        obj = f"@0x7f2a1c0a{i:04x} " if i % 3 else ""
        view = "view internal: " if i % 4 == 0 else ""
        msg = f"client {obj}{src}#{port} ({name}): {view}query: {name} IN {qtype} +E(0)K (10.20.0.53)"
        s.bsd(30, "ns1", f"named[{800 + i % 5}]", msg,
              {"src_endpoint_ip": src, "src_endpoint_port": port, "dst_endpoint_ip": "10.20.0.53",
               "message": name, "class_uid": 4003, "parse_status": "ok"})
    s.bsd(30, "ns1", "named[812]", "zone example.internal/IN: loaded serial 2026100901", {"parse_status": "envelope_only"})
    s.write(out, [
        "<30>Oct  9 20:41:12 ns1 named[1]: client " + "@" * 9000,
        "<30>Oct  9 20:41:12 ns1 named[1]: client 10.0.0.1#99999999999999999999 (x): query: x IN A + (10.0.0.53)",
        "<30>Oct  9 20:41:12 ns1 named[1]: client 10.0.0.1#53 (" + "(" * 5000,
    ])


def dns_unbound(out: Path) -> None:
    s = Sample(29)
    names = ("www.example.com.", "mail.example.com.", "intranet.example.internal.", "xj3k9q2v.example.org.")
    for i in range(60):
        src, name = s.rng.choice(INTERNAL), s.rng.choice(names)
        qtype = s.rng.choice(("A", "AAAA", "MX"))
        if i % 2 == 0:
            msg = f"[812:0] info: {src} {name} {qtype} IN"
            exp = {"src_endpoint_ip": src, "message": name.rstrip("."), "activity_id": 1, "status_id": None}
        else:
            rcode = "NXDOMAIN" if name.startswith("xj3k") else "NOERROR"
            msg = f"[812:0] reply: {src} {name} {qtype} IN {rcode} 0.{s.rng.randrange(10**5, 10**6)} {i % 2} {s.rng.randrange(40, 400)}"
            exp = {"src_endpoint_ip": src, "message": name.rstrip("."), "activity_id": 2,
                   "status_id": 1 if rcode == "NOERROR" else 2}
        s.bsd(30, "ns2", "unbound", msg, {**exp, "class_uid": 4003, "parse_status": "ok"})
    s.bsd(30, "ns2", "unbound", "[812:0] notice: init module 0: validator", {"parse_status": "envelope_only"})
    s.write(out, [
        "<30>Oct  9 20:41:12 ns2 unbound: [1:0] info: " + "a." * 4500 + " A IN",
        "<30>Oct  9 20:41:12 ns2 unbound: [1:0] reply: 10.0.0.1 x. A IN NOERROR " + "9" * 5000 + " 0 1",
        "<30>Oct  9 20:41:12 ns2 unbound: [1:0] info: " + " " * 9000,
    ])


def linux_systemd(out: Path) -> None:
    s = Sample(30)
    units = ("nginx.service", "postgresql@16-main.service", "apt-daily.timer", "backup.service")
    for i in range(60):
        host, unit = s.rng.choice(HOSTS), s.rng.choice(units)
        kind = s.rng.choice(("started", "stopped", "exit_fail", "exit_ok", "failed", "session", "target", "deact"))
        if kind == "started":
            s.bsd(30, host, "systemd[1]", f"Started {unit} - Example service {i}.",
                  {"class_uid": 1007, "activity_id": 1, "status_id": 1, "parse_status": "ok"})
        elif kind == "stopped":
            s.bsd(30, host, "systemd[1]", f"Stopped {unit} - Example service {i}.",
                  {"class_uid": 1007, "activity_id": 2, "status_id": 1, "parse_status": "ok"})
        elif kind == "exit_fail":
            s.bsd(27, host, "systemd[1]", f"{unit}: Main process exited, code=exited, status=1/FAILURE",
                  {"class_uid": 1007, "activity_id": 2, "status_id": 2, "severity_id": 3, "parse_status": "ok"})
        elif kind == "exit_ok":
            s.bsd(30, host, "systemd[1]", f"{unit}: Main process exited, code=exited, status=0/SUCCESS",
                  {"class_uid": 1007, "activity_id": 2, "status_id": 1, "parse_status": "ok"})
        elif kind == "failed":
            s.bsd(27, host, "systemd[1]", f"{unit}: Failed with result 'exit-code'.",
                  {"class_uid": 1007, "status_id": 2, "parse_status": "ok"})
        elif kind == "session":
            user = s.rng.choice(USERS)
            s.bsd(30, host, "systemd[1]", f"Started Session {i} of User {user}.",
                  {"class_uid": 1007, "actor_user_name": user, "activity_id": 1, "parse_status": "ok"})
        elif kind == "deact":
            s.bsd(30, host, "systemd[1]", f"{unit}: Deactivated successfully.",
                  {"class_uid": 1007, "activity_id": 2, "status_id": 1, "parse_status": "ok"})
        else:
            s.bsd(30, host, "systemd[1]", "Reached target Multi-User System.", {"class_uid": 0, "parse_status": "ok"})
    s.write(out, [
        "<30>Oct  9 20:41:12 h systemd[1]: Started " + "x" * 9000,
        "<30>Oct  9 20:41:12 h systemd[1]: a.service: Main process exited, code=exited, status=" + "/" * 5000,
        "<30>Oct  9 20:41:12 h systemd[1]: " + "Started " * 1200,
    ])


def _asa_sev(n: int) -> int:
    return {0: 5, 1: 5, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1, 7: 1}[n]


def cisco_asa(out: Path) -> None:
    s = Sample(31)
    for i in range(60):
        kind = s.rng.choice(("built", "teardown", "deny", "aaa_ok", "aaa_rej", "login", "other"))
        t = s.tick()
        header = (f"<{160 + 6}>{t:%b %d %Y %H:%M:%S}: ", None) if i % 3 == 0 else (
            f"<{160 + 6}>{t:%b} {t.day:>2} {t:%H:%M:%S} asa01 ", "asa01")
        prefix, host = header
        src, dst = s.rng.choice(EXTERNAL), s.rng.choice(INTERNAL)
        sp, dp = s.rng.randrange(1024, 65535), s.rng.choice((22, 443, 3389))
        if kind == "built":
            msg = f"%ASA-6-302013: Built inbound TCP connection {9000 + i} for outside:{src}/{sp} ({src}/{sp}) to inside:{dst}/{dp} ({dst}/{dp})"
            exp = {"class_uid": 4001, "src_endpoint_ip": src, "dst_endpoint_port": dp, "activity_id": 1, "status_id": 1, "severity_id": 1}
        elif kind == "teardown":
            msg = f"%ASA-6-302014: Teardown TCP connection {9000 + i} for outside:{src}/{sp} to inside:{dst}/{dp} duration 0:00:{i % 60:02d} bytes {s.rng.randrange(100, 9000)} TCP FINs"
            exp = {"class_uid": 4001, "src_endpoint_ip": src, "activity_id": 2, "status_id": 1, "severity_id": 1}
        elif kind == "deny":
            msg = f'%ASA-4-106023: Deny tcp src outside:{src}/{sp} dst inside:{dst}/{dp} by access-group "outside_access_in" [0x0, 0x0]'
            exp = {"class_uid": 4001, "src_endpoint_ip": src, "dst_endpoint_port": dp, "status_id": 2, "activity_id": 5, "severity_id": 3}
        elif kind == "aaa_ok":
            user = s.rng.choice(USERS)
            msg = f"%ASA-6-113004: AAA user authentication Successful : server =  10.20.0.10 : user = {user}"
            exp = {"class_uid": 3002, "actor_user_name": user, "status_id": 1, "severity_id": 1}
        elif kind == "aaa_rej":
            user = s.rng.choice(USERS)
            msg = f"%ASA-6-113005: AAA user authentication Rejected : reason = AAA failure : server = 10.20.0.10 : user = {user} : user IP = {src}"
            exp = {"class_uid": 3002, "actor_user_name": user, "src_endpoint_ip": src, "status_id": 2, "severity_id": 1}
        elif kind == "login":
            user = s.rng.choice(USERS)
            msg = f'%ASA-6-605005: Login permitted from {dst}/{sp} to inside:10.20.0.1/ssh for user "{user}"'
            exp = {"class_uid": 3002, "actor_user_name": user, "status_id": 1, "severity_id": 1}
        else:
            msg = "%ASA-5-199999: Example message the template does not model"
            exp = {"class_uid": 0, "severity_id": 2}
        s.lines.append(prefix + msg)
        s.expected.append({"time": t.isoformat(), "device_hostname": host, "parse_status": "ok", **exp})
    s.write(out, [
        "<166>%ASA-6-302013: Built inbound TCP connection 1 for " + "a:" * 4000,
        "<166>%ASA-6-302013: Built inbound TCP connection 1 for outside:203.0.113.4/99999999999999999999 to inside:198.51.100.8/1",
        '<164>%ASA-4-106023: Deny tcp src outside:203.0.113.9/1 dst inside:10.0.0.1/2 by access-group "' + "x" * 9000,
        "<166>%ASA-6-113005: AAA user authentication Rejected : " + ": " * 4000,
    ])


def cisco_ios(out: Path) -> None:
    s = Sample(32)
    for i in range(60):
        kind = s.rng.choice(("ok", "fail", "acl", "config", "link", "ssh"))
        t = s.tick()
        ms = s.rng.randrange(0, 1000)
        svc = f"{t:%b} {t.day:>2} {t:%H:%M:%S}.{ms:03d} UTC"
        host = s.rng.choice(("rtr01", "sw01"))
        user, src = s.rng.choice(USERS), s.rng.choice(INTERNAL + EXTERNAL)
        if kind == "ok":
            msg, sev, exp = f"%SEC_LOGIN-5-LOGIN_SUCCESS: Login Success [user: {user}] [Source: {src}] [localport: 22] at {t:%H:%M:%S} UTC Thu Oct 9 2026", 5, {"class_uid": 3002, "actor_user_name": user, "status_id": 1}
        elif kind == "fail":
            msg, sev, exp = f"%SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: {user}] [Source: {src}] [localport: 22] [Reason: Login Authentication Failed] at {t:%H:%M:%S} UTC Thu Oct 9 2026", 4, {"class_uid": 3002, "actor_user_name": user, "status_id": 2}
        elif kind == "acl":
            sp, dp = s.rng.randrange(1024, 65535), s.rng.choice((22, 23, 161))
            msg, sev, exp = f"%SEC-6-IPACCESSLOGP: list 101 denied tcp {src}({sp}) -> 10.20.0.1({dp}), 1 packet", 6, {"class_uid": 4001, "src_endpoint_ip": src, "dst_endpoint_port": dp}
        elif kind == "config":
            msg, sev, exp = f"%SYS-5-CONFIG_I: Configured from console by {user} on vty0 ({src})", 5, {"class_uid": 0, "actor_user_name": user}
        elif kind == "ssh":
            msg, sev, exp = f"%SSH-5-SSH2_USERAUTH: User '{user}' authentication for SSH2 Session from {src} (tty = 0) using crypto cipher 'aes256-ctr', hmac 'hmac-sha2-256' Succeeded", 5, {"class_uid": 3002, "actor_user_name": user}
        else:
            msg, sev, exp = f"%LINK-3-UPDOWN: Interface GigabitEthernet0/{i % 4}, changed state to down", 3, {"class_uid": 0}
        seq = 100 + i
        if i % 2 == 0:
            s.lines.append(f"<{184 + sev}>{seq}: {host}: *{svc}: {msg}")
            dev = None
        else:
            s.lines.append(f"<{184 + sev}>{t:%b} {t.day:>2} {t:%H:%M:%S} {host} {seq}: {svc}: {msg}")
            dev = host
        s.expected.append({"time": t.replace(microsecond=ms * 1000).isoformat(), "device_hostname": dev,
                           "severity_id": _asa_sev(sev), "parse_status": "ok", **exp})
    s.write(out, [
        "<189>1: r: *Oct  9 20:41:12.123: %" + "A" * 9000,
        "<189>1: r: *Oct  9 20:41:12.123: %SEC-6-IPACCESSLOGP: list 1 denied tcp 203.0.113.4(99999999999999999999) -> 198.51.100.8(1), 1 packet",
        "<189>" + "1: " * 3000,
        "<189>1: r: *Feb 31 25:61:61.123: %SYS-5-CONFIG_I: Configured from console by x",
    ])


def _pan_columns(template_id: str) -> list[str]:
    import yaml  # run with the backend environment: uv run python scripts/...

    path = Path(__file__).resolve().parents[2] / "templates" / "starter" / f"{template_id}.yaml"
    doc = yaml.safe_load(path.read_text())
    return [str(c) for c in doc["payload"]["csv"]["columns"]]


def _pan_line(columns: list[str], values: dict[str, str], extra: int, hires: str = "") -> str:
    cells = [values.get(c, "") if c != "_" else "" for c in columns]
    cells[0] = "1"
    tail = [""] * extra
    if hires and "high_resolution_timestamp" not in columns:
        # After Device Name, newer releases send two more fields, then the high-resolution
        # timestamp with its UTC offset (PAN-OS syslog field descriptions).
        tail = (tail + ["", "", ""])[: max(extra, 3)]
        tail[2] = hires
    cells += tail
    return ",".join(f'"{c}"' if ("," in c or '"' in c) else c for c in cells)


# Firewalls in three zones (UTC, Pacific, and a half-hour zone): Generated Time is the
# firewall's local time with no zone, so only the high-resolution field says when it was.
PAN_ZONES = (None, ZoneInfo("America/Los_Angeles"), ZoneInfo("Asia/Kolkata"))


def _pan_sample(out: Path, template_id: str, seed: int, build: Callable[[Sample, int], tuple[dict[str, str], dict[str, Any]]]) -> None:
    s = Sample(seed)
    columns = _pan_columns(template_id)
    for i in range(60):
        t = s.tick()
        values, exp = build(s, i)
        zone = PAN_ZONES[i % 3]
        local = t.astimezone(zone) if zone else t
        hires = local.isoformat(timespec="milliseconds") if zone else ""
        values.update(receive_time=f"{local:%Y/%m/%d %H:%M:%S}", generated_time=f"{local:%Y/%m/%d %H:%M:%S}",
                      serial_number="012345678901", device_name="pa-fw01", virtual_system="vsys1")
        if "high_resolution_timestamp" in columns:
            values["high_resolution_timestamp"] = hires
        line = _pan_line(columns, values, extra=i % 3 * 20, hires=hires)  # newer releases append columns
        if i % 4 == 0:
            s.lines.append(f"<14>1 {t:%Y-%m-%dT%H:%M:%SZ} pa-fw01 - - - - {line}")
        else:
            s.lines.append(f"<14>{t:%b} {t.day:>2} {t:%H:%M:%S} pa-fw01 {line}")
        s.expected.append({"time": t.isoformat(), "device_hostname": "pa-fw01", "parse_status": "ok", **exp})
    s.write(out, [
        "<14>Oct  9 20:41:12 pa-fw01 1," + "," * 9000,
        '<14>Oct  9 20:41:12 pa-fw01 1,2026/10/09 20:41:12,0,TRAFFIC,end,0,2026/10/09 20:41:12,"' + "x" * 9000,
        "<14>Oct  9 20:41:12 pa-fw01 1,2026/13/45 99:99:99,0,TRAFFIC,end,0,2026/13/45 99:99:99,a,b,,,r,,,,,,,,,,,0,1,99999999999999999999,-1",
        "<14>Oct  9 20:41:12 pa-fw01 1,2026/10/09",
    ])


def paloalto_traffic(out: Path) -> None:
    def build(s: Sample, i: int) -> tuple[dict[str, str], dict[str, Any]]:
        src, dst = s.rng.choice(INTERNAL), s.rng.choice(EXTERNAL)
        sp, dp = s.rng.randrange(1024, 65535), s.rng.choice((443, 80, 53, 3389))
        sub = "deny" if dp == 3389 else s.rng.choice(("end", "start"))
        action = "deny" if sub == "deny" else "allow"
        user = s.rng.choice(USERS)
        values = {"type": "TRAFFIC", "subtype": sub, "source_address": src, "destination_address": dst,
                  "rule_name": "allow-web" if action == "allow" else "block-rdp", "source_user": user,
                  "application": "ssl" if dp == 443 else "web-browsing", "source_zone": "trust",
                  "destination_zone": "untrust", "session_id": str(5000 + i), "repeat_count": "1",
                  "source_port": str(sp), "destination_port": str(dp), "protocol": "tcp", "action": action,
                  "bytes": "6578", "session_end_reason": "tcp-fin" if sub == "end" else "n/a",
                  "destination_country": "United States, US"}
        exp = {"class_uid": 4001, "src_endpoint_ip": src, "dst_endpoint_port": dp, "actor_user_name": user,
               "status_id": 1 if action == "allow" else 2, "activity_id": {"start": 1, "end": 2, "deny": 5}[sub]}
        return values, exp
    _pan_sample(out, "paloalto_traffic", 33, build)


def paloalto_threat(out: Path) -> None:
    sev = {"informational": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}
    def build(s: Sample, i: int) -> tuple[dict[str, str], dict[str, Any]]:
        src, dst = s.rng.choice(INTERNAL), s.rng.choice(EXTERNAL)
        level = s.rng.choice(list(sev))
        sub, threat = s.rng.choice((("spyware", "Suspicious Beacon Traffic(13040)"), ("virus", "Eicar Test File(39040)"),
                                    ("vulnerability", "Example RCE Attempt(99001)"), ("url", "(9999)")))
        action = s.rng.choice(("alert", "reset-both", "drop", "block-url"))
        values = {"type": "THREAT", "subtype": sub, "source_address": src, "destination_address": dst,
                  "source_port": str(s.rng.randrange(1024, 65535)), "destination_port": "443",
                  "ip_protocol": "tcp", "action": action, "url_filename": "bad.example.org/x, y",
                  "threat_id": threat, "category": "any", "severity": level, "direction": "client-to-server"}
        exp = {"class_uid": 4001, "src_endpoint_ip": src, "message": threat, "severity_id": sev[level],
               "status_id": 1 if action == "alert" else 2}
        return values, exp
    _pan_sample(out, "paloalto_threat", 34, build)


def paloalto_system(out: Path) -> None:
    sev = {"informational": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}
    def build(s: Sample, i: int) -> tuple[dict[str, str], dict[str, Any]]:
        kind = s.rng.choice(("ok", "fail", "ha", "general"))
        user, ip = s.rng.choice(USERS), s.rng.choice(INTERNAL)
        if kind == "ok":
            values = {"event_id": "auth-success", "subtype": "general", "severity": "informational",
                      "description": f"User '{user}' logged in via Web from {ip} using https"}
            exp = {"class_uid": 3002, "actor_user_name": user, "src_endpoint_ip": ip, "status_id": 1, "severity_id": 1}
        elif kind == "fail":
            values = {"event_id": "auth-fail", "subtype": "auth", "severity": "medium",
                      "description": f"failed authentication for user '{user}'. Reason: Invalid username/password. From: {ip}."}
            exp = {"class_uid": 3002, "status_id": 2, "severity_id": 3}
        elif kind == "ha":
            values = {"event_id": "state-change", "subtype": "ha", "severity": "high",
                      "description": "HA Group 1: Moved from state Active to state Passive"}
            exp = {"class_uid": 0, "severity_id": 4}
        else:
            values = {"event_id": "general", "subtype": "general", "severity": "informational",
                      "description": "Commit job succeeded, user admin"}
            exp = {"class_uid": 0, "severity_id": 1}
        values.update(type="SYSTEM", module="general")
        return values, exp
    _pan_sample(out, "paloalto_system", 35, build)


def paloalto_globalprotect(out: Path) -> None:
    def build(s: Sample, i: int) -> tuple[dict[str, str], dict[str, Any]]:
        user, pub = s.rng.choice(USERS), s.rng.choice(EXTERNAL)
        event = s.rng.choice(("gateway-auth", "portal-auth", "gateway-logout", "gateway-connected"))
        status = "failure" if event == "portal-auth" and i % 3 == 0 else "success"
        values = {"type": "GLOBALPROTECT", "subtype": "0", "event_id": event, "stage": "login",
                  "authentication_method": "LDAP", "tunnel_type": "SSL", "source_user": user,
                  "machine_name": f"LAPTOP-{user.upper()}", "public_ip": pub, "private_ip": "10.30.0.5",
                  "status": status, "portal": "gp-portal"}
        exp = {"class_uid": 3002, "actor_user_name": user, "src_endpoint_ip": pub,
               "status_id": 1 if status == "success" else 2, "activity_id": 2 if event == "gateway-logout" else 1}
        return values, exp
    _pan_sample(out, "paloalto_globalprotect", 36, build)


def paloalto_userid(out: Path) -> None:
    def build(s: Sample, i: int) -> tuple[dict[str, str], dict[str, Any]]:
        user, ip = f"example\\{s.rng.choice(USERS)}", s.rng.choice(INTERNAL)
        sub = s.rng.choice(("login", "login", "logout", "register-tag"))
        values = {"type": "USERID", "subtype": sub, "source_ip": ip, "user": user,
                  "data_source_name": "dc01.example.internal", "event_id": "0", "repeat_count": "1",
                  "data_source": "ad-dc", "data_source_type": "syslog"}
        exp = {"class_uid": 3002 if sub in ("login", "logout") else 0, "actor_user_name": user}
        if sub in ("login", "logout"):
            exp["activity_id"] = 1 if sub == "login" else 2
        return values, exp
    _pan_sample(out, "paloalto_userid", 37, build)


# --- Windows: one synthetic event stream rendered per transport ----------------------------

WIN_HOSTS = ("DC01.corp.example", "WS-0042.corp.example", "FS01.corp.example")
NEW_USERS = ("erin", "frank", "grace")


def _win_events(rng: random.Random, n: int) -> list[dict[str, Any]]:
    """Canonical events: what happened, plus the OCSF values every transport must produce."""
    events: list[dict[str, Any]] = []
    for _ in range(n):
        kind = rng.choice(("4624", "4624", "4625", "4634", "4688", "4720", "4732", "4740",
                           "4768", "4776", "5156", "5157", "7036"))
        user, admin = rng.choice(USERS), rng.choice(("alice", "carol"))
        host = rng.choice(WIN_HOSTS)
        e: dict[str, Any] = {"eid": int(kind), "channel": "Security", "host": host, "data": {},
                             "keyword": "Audit Success", "exp": {}}
        d = e["data"]
        if kind in ("4624", "4625"):
            ip = rng.choice(INTERNAL + EXTERNAL)
            port = rng.randrange(1024, 65535)
            d.update(SubjectUserName="DC01$" if kind == "4624" else "-", TargetUserName=user,
                     LogonType=rng.choice(("2", "3", "10")), IpAddress=ip, IpPort=str(port),
                     WorkstationName=rng.choice(("KIOSK-07", "WS-0042", "LAPTOP-19")))
            ok = kind == "4624"
            e["keyword"] = "Audit Success" if ok else "Audit Failure"
            e["title"] = "An account was successfully logged on." if ok else "An account failed to log on."
            e["exp"] = {"class_uid": 3002, "activity_id": 1, "status_id": 1 if ok else 2,
                        "actor_user_name": user, "src_endpoint_ip": ip, "src_endpoint_port": port,
                        "src_endpoint_hostname": d["WorkstationName"]}
        elif kind == "4634":
            d.update(TargetUserName=user, LogonType="3")
            e["title"] = "An account was logged off."
            e["exp"] = {"class_uid": 3002, "activity_id": 2, "status_id": 1, "actor_user_name": user}
        elif kind == "4688":
            d.update(SubjectUserName=user, TargetUserName="-",
                     NewProcessName=rng.choice(("C:\\Windows\\System32\\cmd.exe",
                                                "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")),
                     ParentProcessName="C:\\Windows\\explorer.exe")
            e["title"] = "A new process has been created."
            e["exp"] = {"class_uid": 1007, "activity_id": 1, "actor_user_name": user,
                        "actor_process_name": "C:\\Windows\\explorer.exe"}
        elif kind == "4720":
            d.update(SubjectUserName=admin, TargetUserName=rng.choice(NEW_USERS))
            e["title"] = "A user account was created."
            e["exp"] = {"class_uid": 3001, "activity_id": 1, "actor_user_name": admin}
        elif kind == "4732":
            d.update(SubjectUserName=admin, TargetUserName="Administrators",
                     MemberName=f"CN={user},OU=Staff,DC=corp,DC=example")
            e["title"] = "A member was added to a security-enabled local group."
            e["exp"] = {"class_uid": 3006, "activity_id": 3, "actor_user_name": admin}
        elif kind == "4740":
            d.update(SubjectUserName="DC01$", TargetUserName=user, TargetDomainName="KIOSK-07")
            e["title"] = "A user account was locked out."
            e["exp"] = {"class_uid": 3001, "activity_id": 9, "actor_user_name": "DC01$"}
        elif kind == "4768":
            ok = rng.random() < 0.8
            d.update(TargetUserName=user, IpAddress="::ffff:" + rng.choice(INTERNAL), IpPort="0",
                     Status="0x0" if ok else "0x6")
            e["keyword"] = "Audit Success" if ok else "Audit Failure"
            e["title"] = "A Kerberos authentication ticket (TGT) was requested."
            e["exp"] = {"class_uid": 3002, "activity_id": 3, "status_id": 1 if ok else 2,
                        "actor_user_name": user, "src_endpoint_ip": d["IpAddress"]}
        elif kind == "4776":
            ok = rng.random() < 0.8
            d.update(PackageName="MICROSOFT_AUTHENTICATION_PACKAGE_V1_0", TargetUserName=user,
                     Workstation=rng.choice(("KIOSK-07", "WS-0042")),
                     Status="0x0" if ok else "0xc000006a")
            e["keyword"] = "Audit Success" if ok else "Audit Failure"
            e["title"] = "The computer attempted to validate the credentials for an account."
            e["exp"] = {"class_uid": 3002, "activity_id": 1, "status_id": 1 if ok else 2,
                        "actor_user_name": user}
        elif kind in ("5156", "5157"):
            # Source* is the local side in both directions; the initiator is the remote
            # side for inbound traffic.
            local, remote = rng.choice(INTERNAL), rng.choice(EXTERNAL)
            inbound = rng.random() < 0.5
            service, ephemeral = rng.choice((443, 445, 3389)), rng.randrange(49152, 65535)
            lport, rport = (service, ephemeral) if inbound else (ephemeral, service)
            d.update(Application="\\device\\harddiskvolume3\\windows\\system32\\svchost.exe",
                     Direction="%%14592" if inbound else "%%14593", SourceAddress=local,
                     SourcePort=str(lport), DestAddress=remote, DestPort=str(rport), Protocol="6")
            e["direction"] = "Inbound" if inbound else "Outbound"
            ok = kind == "5156"
            e["keyword"] = "Audit Success" if ok else "Audit Failure"
            e["title"] = ("The Windows Filtering Platform has permitted a connection." if ok
                          else "The Windows Filtering Platform has blocked a connection.")
            src, sport, dst, dport = ((remote, rport, local, lport) if inbound
                                      else (local, lport, remote, rport))
            e["exp"] = {"class_uid": 4001, "activity_id": 1 if ok else 5, "status_id": 1 if ok else 2,
                        "src_endpoint_ip": src, "src_endpoint_port": sport,
                        "dst_endpoint_ip": dst, "dst_endpoint_port": dport}
        else:  # not in the map: Base Event, Windows level only
            e.update(channel="System", keyword=None, provider="Service Control Manager")
            d.update(param1="Print Spooler", param2="running")
            e["title"] = "The Print Spooler service entered the running state."
            e["exp"] = {"class_uid": 0, "status_id": None}
        e.setdefault("provider", "Microsoft-Windows-Security-Auditing")
        e["exp"].update(severity_id=1, device_hostname=host, message=e["title"], parse_status="ok")
        events.append(e)
    return events


def _win_message(e: dict[str, Any]) -> str:
    """The rendered Windows message, multi-line, as Event Viewer shows it."""
    d = e["data"]
    out = [e["title"], ""]
    if "SubjectUserName" in d:
        out += ["Subject:", "\tSecurity ID:\t\tS-1-5-21-1000", f"\tAccount Name:\t\t{d['SubjectUserName']}",
                "\tAccount Domain:\t\tCORP", ""]
    if e["eid"] in (4624, 4625):
        label = "New Logon:" if e["eid"] == 4624 else "Account For Which Logon Failed:"
        out += [label, f"\tAccount Name:\t\t{d['TargetUserName']}", "\tAccount Domain:\t\tCORP"]
        if e["eid"] == 4624:
            out += ["\tNetwork Account Name:\t-", "\tNetwork Account Domain:\t-"]
        out += ["", "Network Information:", f"\tWorkstation Name:\t{d['WorkstationName']}",
                f"\tSource Network Address:\t{d['IpAddress']}", f"\tSource Port:\t\t{d['IpPort']}"]
    elif e["eid"] in (4634, 4720, 4740, 4768):
        out += ["Account Information:" if e["eid"] == 4768 else "Target Account:",
                f"\tAccount Name:\t\t{d['TargetUserName']}"]
        if e["eid"] == 4768:
            out += ["", "Network Information:", f"\tClient Address:\t\t{d['IpAddress']}"]
    elif e["eid"] == 4732:
        out += ["Member:", f"\tAccount Name:\t\t{d['MemberName']}", "", "Group:",
                f"\tGroup Name:\t\t{d['TargetUserName']}"]
    elif e["eid"] == 4688:
        out += ["Process Information:", f"\tNew Process Name:\t{d['NewProcessName']}",
                f"\tCreator Process Name:\t{d['ParentProcessName']}"]
    elif e["eid"] == 4776:
        out += [f"Authentication Package:\t{d['PackageName']}", f"Logon Account:\t{d['TargetUserName']}",
                f"Source Workstation:\t{d['Workstation']}", f"Error Code:\t{d['Status']}"]
    elif e["eid"] in (5156, 5157):
        out += ["Application Information:", f"\tApplication Name:\t{d['Application']}", "",
                "Network Information:", f"\tDirection:\t\t{e['direction']}",
                f"\tSource Address:\t\t{d['SourceAddress']}", f"\tSource Port:\t\t{d['SourcePort']}",
                f"\tDestination Address:\t{d['DestAddress']}", f"\tDestination Port:\t\t{d['DestPort']}"]
    return "\r\n".join(out)


WIN_PATHOLOGICAL_JSON = [
    "{" * 9000,
    '{"EventID": "4624", "Channel": "Security"}',
    '{"EventID": 4624, "Channel": {"nested": ["Security"]}, "TargetUserName": ["a", "b"]}',
    '{"EventID": 1e999, "Channel": "Security", "EventTime": "not a time", "IpPort": "99999999999999999999999"}',
    '{"EventID": 4625, "Channel": "Security", "TargetUserName": "\\ud800", "Message": "' + "Account Name: x " * 2000 + '"}',
]


def windows_nxlog_json(out: Path) -> None:
    s = Sample(41)
    for i, e in enumerate(_win_events(s.rng, 60)):
        t = s.tick()
        d = e["data"]
        doc: dict[str, Any] = {
            "EventTime": f"{t:%Y-%m-%d %H:%M:%S}" if i % 2 else t.isoformat(timespec="microseconds"),
            "Hostname": e["host"], "Keywords": -9214364837600034816,
            "EventType": {"Audit Success": "AUDIT_SUCCESS", "Audit Failure": "AUDIT_FAILURE"}.get(e["keyword"], "INFO"),
            "SeverityValue": 2, "Severity": "INFO", "EventID": e["eid"], "SourceName": e["provider"],
            "Task": 12544, "RecordNumber": 100000 + i, "ProcessID": 4, "ThreadID": 512 + i,
            "Channel": e["channel"], "Message": _win_message(e), **d,
            "EventReceivedTime": f"{t:%Y-%m-%d %H:%M:%S}", "SourceModuleName": "eventlog",
            "SourceModuleType": "im_msvistalog",
        }
        text = json.dumps(doc)
        exp = {"time": t.isoformat(), **e["exp"]}
        if i % 3 == 0:  # forwarded with om_tcp and a BSD header
            text = f"<14>{t:%b} {t.day:>2} {t:%H:%M:%S} {e['host'].split('.')[0]} {e['provider']}[4]: {text}"
        s.lines.append(text)
        s.expected.append(exp)
    s.write(out, WIN_PATHOLOGICAL_JSON + [
        "<14>Oct  9 20:41:12 DC01 Microsoft-Windows-Security-Auditing[4]: not json at all",
    ])


def windows_winlogbeat(out: Path) -> None:
    s = Sample(42)
    levels = {"Audit Success": "information", "Audit Failure": "information", None: "information"}
    for i, e in enumerate(_win_events(s.rng, 60)):
        t = s.tick()
        doc: dict[str, Any] = {
            "@timestamp": t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{s.rng.randrange(1000):03d}Z",
            "agent": {"type": "winlogbeat", "version": "8.15.0" if i % 2 else "7.17.24"},
            "ecs": {"version": "8.0.0"},
            "host": {"name": e["host"].split(".")[0].lower()},
            "log": {"level": levels[e["keyword"]]},
            "event": {"code": str(e["eid"]), "provider": e["provider"], "kind": "event"},
            "message": _win_message(e),
            "winlog": {"channel": e["channel"], "event_id": str(e["eid"]) if i % 2 else e["eid"],
                       "computer_name": e["host"], "provider_name": e["provider"],
                       "record_id": 200000 + i, "event_data": e["data"]},
        }
        doc["winlog"]["keywords"] = [e["keyword"] or "Classic"]
        if e["keyword"]:
            if i % 2:  # 8.x sets event.outcome; 7.x leaves it to the ingest pipeline
                doc["event"]["outcome"] = "success" if e["keyword"] == "Audit Success" else "failure"
        frac = int(doc["@timestamp"][20:23])
        s.lines.append(json.dumps(doc))
        s.expected.append({"time": t.replace(microsecond=frac * 1000).isoformat(), **e["exp"]})
    s.write(out, WIN_PATHOLOGICAL_JSON + [
        '{"winlog": {"channel": "Security", "event_id": "4624", "event_data": "not an object"}}',
        '{"winlog": {"keywords": [], "event_id": null}, "@timestamp": 17}',
    ])


def _snare_flatten(text: str) -> str:
    # Snare replaces tabs and line breaks in the message so the record stays one line.
    return text.replace("\r\n", "  ").replace("\n", "  ").replace("\t", " ")


def windows_snare(out: Path) -> None:
    s = Sample(43)
    log_type = {"Audit Success": "Success Audit", "Audit Failure": "Failure Audit", None: "Information"}
    for i, e in enumerate(_win_events(s.rng, 60)):
        t = s.tick()
        fields = [
            "MSWinEventLog", "1", e["channel"], str(5000 + i), f"{t:%a %b %d %H:%M:%S %Y}", str(e["eid"]),
            e["provider"], "N/A", "N/A", log_type[e["keyword"]], e["host"],
            "Logon" if e["eid"] in (4624, 4625, 4634) else "None", "", _snare_flatten(_win_message(e)),
            str(900 + i),
        ]
        body = "\t".join(fields)
        if i % 3 == 0:  # file output: hostname first, no syslog header
            text = e["host"] + "\t" + body
        else:
            text = f"<13>{t:%b} {t.day:>2} {t:%H:%M:%S} {e['host']} {body}"
        exp = dict(e["exp"])
        s.lines.append(text)
        s.expected.append({"time": t.isoformat(), **exp})
    s.write(out, [
        "MSWinEventLog\t1\tSecurity",
        "<13>Oct  9 20:41:12 DC01 MSWinEventLog\t1\tSecurity\tx\tFri Oct 09 20:41:12 2026\t4625\t" + "\t" * 3000,
        "DC01\tMSWinEventLog\t1\tSecurity\t1\tnot a date\t4625\tp\tN/A\tN/A\tFailure Audit\tDC01\tLogon\t\t"
        + "Account Name: " * 3000 + "\t1",
        "DC01\tMSWinEventLog\t1\tSecurity\t1\tFri Oct 09 20:41:12 2026\t4624\tp\tN/A\tN/A\tSuccess Audit\tDC01\tLogon\t\t"
        + "Source Port: 99999999999999999999999999 Account Name: \t1",
    ])


def _dns_time(t: datetime, iso: bool) -> str:
    if iso:
        return f"{t:%Y-%m-%d %H:%M:%S}"
    hour = t.hour % 12 or 12
    return f"{t.month}/{t.day}/{t.year} {hour}:{t:%M:%S} {'AM' if t.hour < 12 else 'PM'}"


def _dns_name(name: str) -> str:
    return "".join(f"({len(label)}){label}" for label in name.split(".")) + "(0)"


def dns_windows(out: Path) -> None:
    s = Sample(44)
    names = ("www.example.com", "mail.example.org", "updates.example.net", "xj3k9q2v.example.org")
    for i in range(60):
        t = s.tick()
        client = s.rng.choice(INTERNAL)
        name = s.rng.choice(names)
        qtype = s.rng.choice(("A", "AAAA", "MX", "TXT"))
        xid = f"{s.rng.randrange(65536):04x}"
        reply = i % 2 == 1
        rcode = "NXDOMAIN" if reply and name.startswith("xj3k") else "NOERROR"
        direction = "Snd" if reply else "Rcv"
        qr = "R" if reply else " "
        flags = ("8183" if rcode == "NXDOMAIN" else "8180") if reply else "0001"
        chars = "DR" if reply else "D"
        text = (f"{_dns_time(t, i % 5 == 0)} 0E5C PACKET  000001D3A1B2{i:04X} UDP {direction} "
                f"{client:<15} {xid} {qr} Q [{flags}   {chars:<3}{rcode}] {qtype:<6} {_dns_name(name)}")
        exp: dict[str, Any] = {"time": t.isoformat(), "class_uid": 4003, "message": name,
                               "activity_id": 2 if reply else 1, "parse_status": "ok"}
        if reply:
            exp.update(dst_endpoint_ip=client, status_id=1 if rcode == "NOERROR" else 2)
        else:
            exp.update(src_endpoint_ip=client, status_id=None)
        s.lines.append(text)
        s.expected.append(exp)
    s.write(out, [
        "DNS Server log file creation at 10/9/2026 8:00:00 PM",
        "Message logging key (for packets - other items use a subset of these fields):",
        "\tField #  Information         Values",
        "10/9/2026 8:41:12 PM 0E5C EVENT   The DNS server has started.",
        "13/45/2026 8:41:12 PM 0E5C PACKET  000001D3A1B2C3D0 UDP Rcv 10.20.1.5 9f3a   Q [0001   D   NOERROR] A (3)www(0)",
        "10/9/2026 8:41:12 PM 0E5C PACKET  000001D3A1B2C3D0 UDP Rcv 10.20.1.5 9f3a   Q [0001   D   NOERROR] A "
        + "(63)" + "a" * 63 * 150,
        "10/9/2026 8:41:12 PM 0E5C PACKET  " + "0" * 9000,
    ])


SECURITY_GUID = "{54849625-5478-4994-a5ba-3e3b0328c30d}"  # the public provider id
KEYWORDS = {"Audit Success": 0x8020000000000000, "Audit Failure": 0x8010000000000000,
            None: 0x8080000000000000}


def windows_evtx(out: Path) -> None:
    """sample.evtx is the fixture; sample.log is what the reader frames from it."""
    import io

    import evtx_writer as w

    from app.ingest.evtx import EvtxReader

    s = Sample(45)
    records = []
    for i, e in enumerate(_win_events(s.rng, 60), start=1):
        t = s.tick().replace(microsecond=s.rng.randrange(1_000_000))
        system = e["channel"] == "System"
        records.append((i, t, w.event(
            provider=e["provider"], provider_guid=None if system else SECURITY_GUID,
            event_id=e["eid"], qualifiers=16384 if system else None, level=4 if system else 0,
            task=0 if system else 12544, keywords=KEYWORDS[e["keyword"]], created=t,
            record_id=i, channel=e["channel"], computer=e["host"], data=e["data"],
            thread_id=500 + i,
        )))
        exp = dict(e["exp"])
        exp["message"] = None if system else e["title"].rstrip(".")
        s.expected.append({"time": t.isoformat(), **exp})
    data = w.write_evtx(records)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.evtx").write_bytes(data)
    batch = EvtxReader().read(io.BytesIO(data), 0)
    assert [r for r, _ in batch.frames] == list(range(1, 61)) and batch.errors == 0
    s.lines = [frame.data.decode("utf-8") for _, frame in batch.frames]
    # A copy with one record's bytes overwritten: the reader must skip it and keep the rest.
    damaged = bytearray(data)
    damaged[4096 + 512 + 40 : 4096 + 512 + 140] = b"\xff" * 100
    (out / "pathological.evtx").write_bytes(bytes(damaged))
    s.write(out, WIN_PATHOLOGICAL_JSON + [
        '{"Event": {"System": {"EventID": {"#text": {"deep": 1}}, "Channel": "Security"}}}',
        '{"Event": {"System": {"EventID": 4624, "Channel": "Security", "Level": "x",'
        ' "TimeCreated": {"#attributes": {"SystemTime": "2026-13-45T99:00:00Z"}}}}}',
        '{"Event": null}',
    ])


GENERATORS: dict[str, Callable[[Path], None]] = {
    "linux_sudo": linux_sudo,
    "linux_pam": linux_pam,
    "cef_generic": cef_generic,
    "leef_generic": leef_generic,
    "json_over_syslog": json_over_syslog,
    "fortinet_fortigate": fortinet_fortigate,
    "unifi": unifi,
    "dns_bind": dns_bind,
    "dns_unbound": dns_unbound,
    "linux_systemd": linux_systemd,
    "cisco_asa": cisco_asa,
    "cisco_ios": cisco_ios,
    "paloalto_traffic": paloalto_traffic,
    "paloalto_threat": paloalto_threat,
    "paloalto_system": paloalto_system,
    "paloalto_globalprotect": paloalto_globalprotect,
    "paloalto_userid": paloalto_userid,
    "windows_nxlog_json": windows_nxlog_json,
    "windows_winlogbeat": windows_winlogbeat,
    "windows_snare": windows_snare,
    "dns_windows": dns_windows,
    "windows_evtx": windows_evtx,
}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    root = Path(sys.argv[1])
    for name in sys.argv[2:] or list(GENERATORS):
        GENERATORS[name](root / name)
