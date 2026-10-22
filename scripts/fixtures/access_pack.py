"""Generate fixtures for the access and identity starter templates (CLAUDE.md section 6).

    python scripts/fixtures/access_pack.py backend/tests/fixtures/logs [template_id ...]

Authelia, tac_plus, Vault (audit and server), OpenVPN, PowerDNS, and OpenLDAP slapd. Same
conventions as starter_pack.py: 50+ real-shaped lines, expected.jsonl written from what the
generator put in each line, and pathological.log. Line shapes come from the vendors'
public documentation, not from captured logs; values are invented.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from starter_pack import EXTERNAL, INTERNAL, USERS, Sample  # noqa: E402

DEVICES = ("10.20.0.1", "10.20.0.2", "10.20.0.3")


def authelia(out: Path) -> None:
    s = Sample(41)
    urls = ("https://grafana.example.com/admin", "https://wiki.example.com/", "https://git.example.com/settings")
    for _ in range(60):
        user, ip = s.rng.choice(USERS), s.rng.choice(EXTERNAL + INTERNAL)
        kind = s.rng.choice(("fail1", "fail1", "ok1", "fail2", "ok2", "ban", "denied", "json"))
        if kind == "json":
            t = s.tick()
            ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            body = json.dumps({"level": "debug", "method": "POST",
                               "msg": f"Successful TOTP authentication attempt made by user '{user}'",
                               "path": "/api/secondfactor/totp", "remote_ip": ip, "time": ts}, separators=(",", ":"))
            s.lines.append(f"<30>{t:%b} {t.day:>2} {t:%H:%M:%S} auth-01 authelia[1]: {body}")
            s.expected.append({"time": t.isoformat(), "device_hostname": "auth-01", "actor_user_name": user,
                               "src_endpoint_ip": ip, "class_uid": 3002, "status_id": 1, "parse_status": "ok"})
            continue
        t = s.tick()
        ts = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        if kind == "fail1":
            msg, level, path, cls, status = f"Unsuccessful 1FA authentication attempt by user '{user}': authentication failed", "error", "/api/firstfactor", 3002, 2
        elif kind == "ok1":
            msg, level, path, cls, status = f"Successful 1FA authentication attempt made by user '{user}'", "debug", "/api/firstfactor", 3002, 1
        elif kind == "fail2":
            factor = s.rng.choice(("TOTP", "WebAuthn", "Duo"))
            msg, level, path, cls, status = f"Unsuccessful {factor} authentication attempt by user '{user}'", "error", "/api/secondfactor/totp", 3002, 2
        elif kind == "ok2":
            msg, level, path, cls, status = f"Successful WebAuthn authentication attempt made by user '{user}'", "debug", "/api/secondfactor/webauthn", 3002, 1
        elif kind == "ban":
            msg, level, path, cls, status = f"Unsuccessful 1FA authentication attempt by user '{user}' and they are banned until 2026-10-09 21:00:00 +0000 UTC", "error", "/api/firstfactor", 3002, 2
        else:
            msg, level, path, cls, status = f"Access to {s.rng.choice(urls)} (method GET) is forbidden to user '{user}'", "info", "/api/authz/forward-auth", 3003, 2
        pri = 27 if level == "error" else 30
        s.lines.append(f'<{pri}>{t:%b} {t.day:>2} {t:%H:%M:%S} auth-01 authelia[1]: time="{ts}" level={level} msg="{msg}" method=POST path={path} remote_ip={ip}')
        s.expected.append({"time": t.isoformat(), "device_hostname": "auth-01", "actor_user_name": user,
                           "src_endpoint_ip": ip, "class_uid": cls, "status_id": status, "parse_status": "ok"})
    s.bsd(30, "auth-01", "authelia[1]", 'time="2026-10-09T21:30:00Z" level=info msg="Startup complete"', {"class_uid": 0, "parse_status": "ok"})
    s.write(out, [
        '<27>Oct  9 20:41:12 auth-01 authelia[1]: time="x" level=error msg="' + '\\"' * 4000 + '"',
        "<27>Oct  9 20:41:12 auth-01 authelia[1]: msg=\"Unsuccessful 1FA authentication attempt by user '" + "a" * 9000 + "'\"",
        '<27>Oct  9 20:41:12 auth-01 authelia[1]: {"msg":"' + "{" * 5000,
    ])


def tacacs_tac_plus(out: Path) -> None:
    s = Sample(42)
    commands = ("show running-config <cr>", "configure terminal <cr>", "interface GigabitEthernet0/1 <cr>", "write memory <cr>")
    task = 10
    for i in range(60):
        user, nas, client = s.rng.choice(USERS), s.rng.choice(DEVICES), s.rng.choice(INTERNAL)
        tag = f"tac_plus[{2200 + i % 7}]"
        kind = s.rng.choice(("login", "login", "reject", "enable", "start", "cmd", "cmd", "stop"))
        task += 1
        if kind in ("login", "reject", "enable"):
            what = "enable" if kind == "enable" else "login"
            result = "rejected" if kind == "reject" else "accepted"
            s.bsd(86, "tacacs-01", tag, f"{what} query for '{user}' tty{i % 4} from {nas} {result}",
                  {"actor_user_name": user, "device_ip": nas, "class_uid": 3002,
                   "status_id": 2 if result == "rejected" else 1, "parse_status": "ok"})
        elif kind == "start":
            s.bsd(86, "tacacs-01", tag, f"{nas}\t{user}\ttty{i % 4}\t{client}\tstart\ttask_id={task}\tservice=shell",
                  {"actor_user_name": user, "device_ip": nas, "src_endpoint_ip": client, "class_uid": 3002,
                   "activity_id": 1, "parse_status": "ok"})
        elif kind == "stop":
            s.bsd(86, "tacacs-01", tag, f"{nas}\t{user}\ttty{i % 4}\t{client}\tstop\ttask_id={task}\tservice=shell\telapsed_time={s.rng.randrange(5, 4000)}",
                  {"actor_user_name": user, "device_ip": nas, "class_uid": 3002, "activity_id": 2, "parse_status": "ok"})
        else:
            cmd = s.rng.choice(commands)
            s.bsd(86, "tacacs-01", tag, f"{nas}\t{user}\ttty{i % 4}\t{client}\tstop\ttask_id={task}\tservice=shell\tpriv-lvl=15\tcmd={cmd}",
                  {"actor_user_name": user, "device_ip": nas, "class_uid": 1007, "message": cmd, "parse_status": "ok"})
    s.bsd(86, "tacacs-01", "tac_plus[2200]", "connect from 10.20.0.1", {"device_ip": "10.20.0.1", "class_uid": 0, "parse_status": "ok"})
    s.bsd(86, "tacacs-01", "tac_plus[2200]", "Reading config", {"parse_status": "envelope_only"})
    s.write(out, [
        "<86>Oct  9 20:41:12 tacacs-01 tac_plus[1]: login query for '" + "'" * 9000 + " tty0 from 10.0.0.1 accepted",
        "<86>Oct  9 20:41:12 tacacs-01 tac_plus[1]: 10.0.0.1" + "\t" * 5000 + "start",
        "<86>Oct  9 20:41:12 tacacs-01 tac_plus[1]: 10.0.0.1\talice\ttty1\t10.0.0.5\tstop" + "\tcmd=" * 3000,
    ])


def vault_audit(out: Path) -> None:
    s = Sample(43)
    paths = (("secret/data/app/db", "read"), ("secret/metadata/app", "list"), ("auth/token/lookup-self", "read"),
             ("sys/policies/acl/app", "update"), ("pki/issue/web", "update"), ("secret/data/old", "delete"))
    for i in range(60):
        t = s.tick()
        who = s.rng.choice(("userpass-alice", "userpass-bob", "approle-ci", "token"))
        ip = s.rng.choice(INTERNAL)
        path, op = s.rng.choice(paths)
        typ = "request" if i % 2 == 0 else "response"
        denied = path.startswith("sys/") and s.rng.random() < 0.6
        entry = {"time": t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "type": typ,
                 "auth": {"display_name": who, "policies": ["default"], "token_type": "service"},
                 "request": {"id": f"6d6b1c2e-0000-4000-8000-{i:012d}", "operation": op, "path": path,
                             "remote_address": ip, "remote_port": 50000 + i, "mount_type": path.split("/")[0]}}
        if denied:
            entry["error"] = "1 error occurred:\n\t* permission denied\n\n"
        if typ == "response":
            entry["response"] = {"mount_type": path.split("/")[0]}
        body = json.dumps(entry, separators=(",", ":"))
        s.lines.append(f"<134>{t:%b} {t.day:>2} {t:%H:%M:%S} vault-01 vault[900]: {body}")
        s.expected.append({"time": t.isoformat(), "device_hostname": "vault-01",
                           "actor_user_name": who, "src_endpoint_ip": ip, "message": path, "class_uid": 6003,
                           "status_id": 2 if denied else 1, "parse_status": "ok"})
    s.write(out, [
        '<134>Oct  9 20:41:12 vault-01 vault[900]: {"time":"2026-10-09T20:41:12Z","type":"request",' + '"a":[' * 3000,
        '<134>Oct  9 20:41:12 vault-01 vault[900]: {"time":"2026-10-09T20:41:12Z","type":"response","auth":{"display_name":"' + "x" * 9000 + '"}}',
        '<134>Oct  9 20:41:12 vault-01 vault[900]: {"time":"not a time","type":"request","request":{"operation":42}}',
    ])


def vault_server(out: Path) -> None:
    s = Sample(44)
    msgs = (("INFO", "core", "vault is unsealed", 1), ("INFO", "core", "acquired lock, enabling active operation", 1),
            ("INFO", "expiration", "revoked lease", 1), ("WARN", "expiration", "lease count exceeds warning lease count threshold", 3),
            ("ERROR", "storage.raft", "failed to heartbeat to: peer=10.20.0.12:8201 error=\"i/o timeout\"", 4),
            ("INFO", "identity", "entities restored", 1), ("WARN", "core", "skipping new leader cleanup", 3))
    for _ in range(60):
        t = s.tick()
        level, comp, msg, sev = s.rng.choice(msgs)
        pri = {"INFO": 30, "WARN": 28, "ERROR": 27}[level]
        pad = "  " if len(level) == 4 else " "
        s.lines.append(f"<{pri}>{t:%b} {t.day:>2} {t:%H:%M:%S} vault-01 vault[900]: {t:%Y-%m-%dT%H:%M:%S}.000Z [{level}]{pad}{comp}: {msg}")
        s.expected.append({"time": t.isoformat(), "device_hostname": "vault-01", "message": msg, "severity_id": sev, "parse_status": "ok"})
    s.bsd(30, "vault-01", "vault[900]", "==> Vault server configuration:", {"parse_status": "envelope_only"})
    s.write(out, [
        "<30>Oct  9 20:41:12 vault-01 vault[900]: 2026-10-09T20:41:12.000Z [INFO]  " + "c" * 9000 + ": x",
        "<30>Oct  9 20:41:12 vault-01 vault[900]: 2026-13-45T99:99:99.000Z [INFO]  core: impossible time",
        "<30>Oct  9 20:41:12 vault-01 vault[900]: 2026-10-09T20:41:12.000Z [" + "[" * 5000,
    ])


def openvpn_server(out: Path) -> None:
    s = Sample(45)
    pool = iter(f"172.27.232.{n}" for n in range(2, 250))
    for i in range(60):
        user, ip, port = s.rng.choice(USERS), s.rng.choice(EXTERNAL), s.rng.randrange(1024, 65535)
        kind = s.rng.choice(("connect", "pool", "exit", "fail", "connect_ce"))
        t = s.tick()
        stamp = f"{t:%Y-%m-%d %H:%M:%S}"
        wrap = f"{t:%Y-%m-%dT%H:%M:%S}+0000 [stdout#info] [OVPN 0] OUT: '{stamp} "
        if kind == "connect":
            body, tag, exp = f"{wrap}{ip}:{port} [{user}] Peer Connection Initiated with [AF_INET]{ip}:{port} (via [AF_INET]10.20.0.4%eth0)'", "openvpnas", {"actor_user_name": user, "status_id": 1, "activity_id": 1}
        elif kind == "pool":
            body, tag, exp = f"{wrap}{user}/{ip}:{port} MULTI_sva: pool returned IPv4={next(pool)}, IPv6=(Not enabled)'", "openvpnas", {"actor_user_name": user, "status_id": 1}
        elif kind == "exit":
            body, tag, exp = f"{user}/{ip}:{port} SIGTERM[soft,remote-exit] received, client-instance exiting", f"openvpn[{1200 + i % 3}]", {"actor_user_name": user, "activity_id": 2}
        elif kind == "fail":
            body, tag, exp = f"{ip}:{port} TLS Auth Error: Auth Username/Password verification failed for peer", f"openvpn[{1200 + i % 3}]", {"status_id": 2}
        else:
            body, tag, exp = f"{ip}:{port} [{user}] Peer Connection Initiated with [AF_INET]{ip}:{port}", f"openvpn[{1200 + i % 3}]", {"actor_user_name": user, "status_id": 1}
        host = "vpn-01" if tag == "openvpnas" else "vpn-02"
        s.lines.append(f"<134>{t:%b} {t.day:>2} {t:%H:%M:%S} {host} {tag}: {body}")
        s.expected.append({"time": t.isoformat(), "device_hostname": host, "src_endpoint_ip": ip, "src_endpoint_port": port,
                           "class_uid": 3002, "parse_status": "ok", **exp})
    s.bsd(134, "vpn-02", "openvpn[1200]", "Initialization Sequence Completed", {"parse_status": "envelope_only"})
    s.write(out, [
        "<134>Oct  9 20:41:12 vpn-01 openvpnas: " + "'" * 9000 + "OUT: '",
        "<134>Oct  9 20:41:12 vpn-02 openvpn[1]: " + "a/" * 4000 + "192.0.2.1:1 SIGTERM[x] received, client-instance exiting",
        "<134>Oct  9 20:41:12 vpn-02 openvpn[1]: 192.0.2.1:99999999 [x] Peer Connection Initiated with",
    ])


def dns_powerdns(out: Path) -> None:
    s = Sample(46)
    names = ("www.example.com", "chatgpt.com", "api.anthropic.com", "mail.example.com", "intranet.example.internal")
    for i in range(60):
        src, name, qtype = s.rng.choice(INTERNAL), s.rng.choice(names), s.rng.choice(("A", "AAAA", "MX", "TXT"))
        form = s.rng.choice(("auth", "rec_text", "rec_struct"))
        if form == "auth":
            cache = s.rng.choice(("HIT", "MISS"))
            msg, tag = f"Remote {src} wants '{name}|{qtype}', do = 0, bufsize = 1232 (4096): packetcache {cache}", f"pdns_server[{700 + i % 3}]"
            exp = {"src_endpoint_ip": src}
        elif form == "rec_text":
            port = s.rng.randrange(1024, 65535)
            msg, tag = f"{i} [1/1] question for '{name}|{qtype}' from {src}:{port}", f"pdns_recursor[{710 + i % 3}]"
            exp = {"src_endpoint_ip": src, "src_endpoint_port": port}
        else:
            msg = (f'msg="Question" subsystem="syncres" level="0" prio="Info" tid="1" ts="1791578580.{i:03d}" '
                   f'ecs="" ip="{src}" proto="udp" qname="{name}" qtype="{qtype}"')
            tag, exp = f"pdns-recursor[{710 + i % 3}]", {"src_endpoint_ip": src}
        s.bsd(30, "ns2", tag, msg, {"class_uid": 4003, "message": name, "parse_status": "ok", **exp})
    s.bsd(30, "ns2", "pdns_server[700]", "Done launching threads, ready to distribute questions", {"parse_status": "envelope_only"})
    s.write(out, [
        "<30>Oct  9 20:41:12 ns2 pdns_server[1]: Remote 10.0.0.1 wants '" + "|" * 9000 + "', do = 0, bufsize = 512: packetcache MISS",
        '<30>Oct  9 20:41:12 ns2 pdns-recursor[1]: msg="Question" ' + 'qname="' * 3000,
        "<30>Oct  9 20:41:12 ns2 pdns_recursor[1]: question for 'x|A' from 10.0.0.1:99999999999",
    ])


def openldap_slapd(out: Path) -> None:
    s = Sample(47)
    conn = 1000
    while len(s.lines) < 60:
        conn += 1
        user, ip, port = s.rng.choice(USERS), s.rng.choice(INTERNAL), s.rng.randrange(1024, 65535)
        tag = "slapd[1100]"
        dn = f"uid={user},ou=people,dc=example,dc=com"
        bad = s.rng.random() < 0.35
        s.bsd(166, "ldap-01", tag, f"conn={conn} fd={12 + conn % 20} ACCEPT from IP={ip}:{port} (IP=0.0.0.0:389)",
              {"class_uid": 4001, "src_endpoint_ip": ip, "src_endpoint_port": port, "parse_status": "ok"})
        s.bsd(166, "ldap-01", tag, f'conn={conn} op=0 BIND dn="{dn}" method=128',
              {"class_uid": 3002, "actor_user_name": user, "message": dn, "parse_status": "ok"})
        if not bad:
            s.bsd(166, "ldap-01", tag, f'conn={conn} op=0 BIND dn="{dn}" mech=SIMPLE bind_ssf=0 ssf=0',
                  {"class_uid": 3002, "actor_user_name": user, "parse_status": "ok"})
        err = 49 if bad else 0
        s.bsd(166, "ldap-01", tag, f"conn={conn} op=0 RESULT tag=97 err={err} qtime=0.000012 etime=0.000210 text=",
              {"class_uid": 3002, "status_id": 2 if bad else 1, "parse_status": "ok"})
        if not bad:
            s.bsd(166, "ldap-01", tag, f'conn={conn} op=1 SRCH base="dc=example,dc=com" scope=2 deref=0 filter="(uid={user})"',
                  {"class_uid": 0, "parse_status": "ok"})
        s.bsd(166, "ldap-01", tag, f"conn={conn} fd={12 + conn % 20} closed" + (" (connection lost)" if bad else ""),
              {"class_uid": 4001, "activity_id": 2, "parse_status": "ok"})
    s.bsd(166, "ldap-01", "slapd[1100]", "slapd starting", {"parse_status": "envelope_only"})
    s.write(out, [
        '<166>Oct  9 20:41:12 ldap-01 slapd[1]: conn=1 op=0 BIND dn="' + '"' * 9000 + ' method=128',
        "<166>Oct  9 20:41:12 ldap-01 slapd[1]: conn=99999999999999999999999 op=0 RESULT tag=97 err=49 text=",
        "<166>Oct  9 20:41:12 ldap-01 slapd[1]: conn=1 fd=1 ACCEPT from IP=" + ":" * 5000,
    ])


GENERATORS = {
    "authelia": authelia,
    "tacacs_tac_plus": tacacs_tac_plus,
    "vault_audit": vault_audit,
    "vault_server": vault_server,
    "openvpn_server": openvpn_server,
    "dns_powerdns": dns_powerdns,
    "openldap_slapd": openldap_slapd,
}

if __name__ == "__main__":
    root = Path(sys.argv[1])
    for name in sys.argv[2:] or list(GENERATORS):
        GENERATORS[name](root / name)
