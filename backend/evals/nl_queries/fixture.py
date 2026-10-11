"""Deterministic synthetic lake for the Ask accuracy suite (SPEC 5.7).

Synthetic values only: RFC 5737 public addresses, RFC 1918 internal ones, invented host
and user names. The same seed always produces the same events, so expected answers are
stable. Every OCSF column the questions rely on is populated directly; this tests the
model's SQL, not the parsers.
"""

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.schema import COLUMN_NAMES
from app.ingest.writer import LakeWriter

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 10, 8, tzinfo=UTC)
SOURCES = ("linux_auth", "fw_edge", "dns", "edr")

USERS = ("alice", "bob", "carol", "dave", "erin", "svc_backup")
SERVERS = ("bastion", "web-01", "web-02", "db-01")
WORKSTATIONS = ("ws-01", "ws-02", "ws-03", "ws-04", "ws-05")
INTERNAL = tuple(f"10.0.{a}.{b}" for a in (1, 2) for b in (11, 12, 13, 14, 15))
# Brute force sources with distinct volumes, so rankings have no ties.
ATTACKERS = {"203.0.113.9": 120, "198.51.100.23": 60, "203.0.113.77": 25}
OTHER_EXTERNAL = ("198.51.100.4", "198.51.100.88", "203.0.113.140", "203.0.113.201")
INVALID_USERS = ("oracle", "admin", "test", "ubuntu", "root")


class _Gen:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)  # noqa: S311  # deterministic test data, not security
        self.rows: list[dict[str, Any]] = []
        self.ids = random.Random(seed + 1)  # noqa: S311  # deterministic test data, not security

    def when(self) -> datetime:
        seconds = self.rng.randrange(int((END - START).total_seconds()))
        return START + timedelta(seconds=seconds)

    def add(self, source_id: str, when: datetime, raw: str, **fields: Any) -> None:
        row: dict[str, Any] = dict.fromkeys(COLUMN_NAMES)
        row.update(
            event_id=str(uuid.UUID(int=self.ids.getrandbits(128), version=4)),
            source_id=source_id,
            template_id=f"eval_{source_id}",
            template_version="1",
            time=when,
            time_observed=when + timedelta(seconds=2),
            raw=raw,
            raw_bytes_invalid=False,
            parse_status="ok",
            classification="cloud_allowed",
            owner_id="local",
        )
        row.update(fields)
        self.rows.append(row)


def _auth(g: _Gen) -> None:
    for ip, n in ATTACKERS.items():
        for _ in range(n):
            user = g.rng.choice(INVALID_USERS)
            t = g.when()
            g.add(
                "linux_auth",
                t,
                f"{t:%b %d %H:%M:%S} bastion sshd[{g.rng.randrange(1000, 9999)}]: "
                f"Failed password for invalid user {user} from {ip} port 22 ssh2",
                class_uid=3002,
                category_uid=3,
                activity_id=1,
                status_id=2,
                severity_id=3,
                actor_user_name=user,
                actor_process_name="sshd",
                src_endpoint_ip=ip,
                device_hostname="bastion",
                message=f"Failed password for invalid user {user}",
            )
    for ip in OTHER_EXTERNAL:
        for _ in range(g.rng.randrange(2, 6)):
            t = g.when()
            g.add(
                "linux_auth",
                t,
                f"{t:%b %d %H:%M:%S} bastion sshd[1]: Failed password for root from {ip}",
                class_uid=3002,
                category_uid=3,
                activity_id=1,
                status_id=2,
                severity_id=3,
                actor_user_name="root",
                actor_process_name="sshd",
                src_endpoint_ip=ip,
                device_hostname="bastion",
                message="Failed password for root",
            )
    for _ in range(240):
        user = g.rng.choice(USERS[:5])
        host = g.rng.choice(SERVERS)
        ip = g.rng.choice(INTERNAL)
        t = g.when()
        ok = g.rng.random() > 0.08
        g.add(
            "linux_auth",
            t,
            f"{t:%b %d %H:%M:%S} {host} sshd[2]: "
            f"{'Accepted publickey' if ok else 'Failed password'} for {user} from {ip}",
            class_uid=3002,
            category_uid=3,
            activity_id=1,
            status_id=1 if ok else 2,
            severity_id=1 if ok else 3,
            actor_user_name=user,
            actor_process_name="sshd",
            src_endpoint_ip=ip,
            device_hostname=host,
            message=("Accepted publickey" if ok else "Failed password") + f" for {user}",
        )
        if ok:
            g.add(
                "linux_auth",
                t + timedelta(minutes=g.rng.randrange(5, 120)),
                f"{t:%b %d %H:%M:%S} {host} sshd[2]: session closed for user {user}",
                class_uid=3002,
                category_uid=3,
                activity_id=2,
                status_id=1,
                severity_id=1,
                actor_user_name=user,
                actor_process_name="sshd",
                device_hostname=host,
                message=f"session closed for user {user}",
            )
    for _ in range(90):
        user = g.rng.choice(("alice", "bob", "carol"))
        host = g.rng.choice(SERVERS)
        t = g.when()
        denied = user == "carol" and g.rng.random() < 0.5
        cmd = g.rng.choice(
            ("/usr/bin/systemctl restart nginx", "/usr/bin/apt update", "/bin/cat /etc/shadow")
        )
        g.add(
            "linux_auth",
            t,
            f"{t:%b %d %H:%M:%S} {host} sudo: {user} : "
            f"{'command not allowed' if denied else 'COMMAND=' + cmd}",
            class_uid=3003,
            category_uid=3,
            activity_id=1,
            status_id=2 if denied else 1,
            severity_id=3 if denied else 1,
            actor_user_name=user,
            actor_process_name="sudo",
            device_hostname=host,
            message=("command not allowed" if denied else f"COMMAND={cmd}"),
            unmapped=json.dumps({"command": cmd}),
        )
    for _ in range(15):
        t = g.when()
        g.add(
            "linux_auth",
            t,
            f"kernel: [{g.rng.randrange(10**6)}.123] eth0: link up",
            parse_status="envelope_only",
            parse_errors="no_syslog_header",
            message=None,
        )


def _firewall(g: _Gen) -> None:
    services = {22: 0.15, 80: 0.25, 443: 0.45, 53: 0.1, 3389: 0.05}
    ports = list(services)
    weights = list(services.values())
    for _ in range(600):
        src = g.rng.choice(INTERNAL)
        dst = g.rng.choice(("192.0.2.30", "192.0.2.10", "192.0.2.20", "198.51.100.200"))
        port = g.rng.choices(ports, weights)[0]
        blocked = port == 3389 or g.rng.random() < 0.05
        t = g.when()
        g.add(
            "fw_edge",
            t,
            f"{t.isoformat()} fw-edge-01 action={'deny' if blocked else 'allow'} "
            f"src={src} dst={dst} dport={port}",
            class_uid=4001,
            category_uid=4,
            activity_id=6,
            status_id=2 if blocked else 1,
            severity_id=2 if blocked else 1,
            src_endpoint_ip=src,
            dst_endpoint_ip=dst,
            dst_endpoint_port=port,
            src_endpoint_port=g.rng.randrange(1024, 65535),
            device_hostname="fw-edge-01",
            message="deny" if blocked else "allow",
        )
    # One scanner probing many ports, all denied.
    for port in range(1000, 1080):
        t = g.when()
        g.add(
            "fw_edge",
            t,
            f"{t.isoformat()} fw-edge-01 action=deny src=198.51.100.23 dst=192.0.2.10 dport={port}",
            class_uid=4001,
            category_uid=4,
            activity_id=6,
            status_id=2,
            severity_id=2,
            src_endpoint_ip="198.51.100.23",
            dst_endpoint_ip="192.0.2.10",
            dst_endpoint_port=port,
            device_hostname="fw-edge-01",
            message="deny",
        )


def _dns(g: _Gen) -> None:
    domains = {
        "intranet.example.internal": 120,
        "updates.example.com": 80,
        "mail.example.com": 60,
        "cdn.example.net": 40,
        "xj3k9q2v.example.org": 9,  # random-looking, NXDOMAIN
    }
    for domain, n in domains.items():
        for _ in range(n):
            src = g.rng.choice(INTERNAL)
            rcode = "NXDOMAIN" if domain.startswith("xj3k") else "NOERROR"
            t = g.when()
            g.add(
                "dns",
                t,
                f"{t.isoformat()} dns-01 query {domain} A from {src} rcode={rcode}",
                class_uid=4003,
                category_uid=4,
                activity_id=1,
                status_id=2 if rcode == "NXDOMAIN" else 1,
                severity_id=1,
                src_endpoint_ip=src,
                device_hostname="dns-01",
                message=f"query {domain} A",
                unmapped=json.dumps({"query": domain, "qtype": "A", "rcode": rcode}),
            )


def _edr(g: _Gen) -> None:
    common = ("chrome.exe", "outlook.exe", "teams.exe", "explorer.exe")
    for _ in range(300):
        host = g.rng.choice(WORKSTATIONS)
        user = g.rng.choice(USERS[:5])
        t = g.when()
        proc = g.rng.choice(common)
        g.add(
            "edr",
            t,
            f"{t.isoformat()} {host} process_start user={user} image={proc}",
            class_uid=1007,
            category_uid=1,
            activity_id=1,
            status_id=1,
            severity_id=1,
            actor_user_name=user,
            actor_process_name=proc,
            device_hostname=host,
            message=f"Process started: {proc}",
        )
    for _ in range(12):
        t = g.when()
        g.add(
            "edr",
            t,
            f"{t.isoformat()} ws-03 process_start user=dave image=powershell.exe -enc SQBFAFgA",
            class_uid=1007,
            category_uid=1,
            activity_id=1,
            status_id=1,
            severity_id=4,
            actor_user_name="dave",
            actor_process_name="powershell.exe",
            device_hostname="ws-03",
            message="Process started: powershell.exe -enc (encoded command)",
        )
    t = datetime(2026, 10, 6, 2, 14, 7, tzinfo=UTC)
    g.add(
        "edr",
        t,
        f"{t.isoformat()} ws-03 process_start user=dave image=mimikatz.exe",
        class_uid=1007,
        category_uid=1,
        activity_id=1,
        status_id=1,
        severity_id=5,
        actor_user_name="dave",
        actor_process_name="mimikatz.exe",
        device_hostname="ws-03",
        message="Process started: mimikatz.exe",
    )


def build_rows(seed: int = 7) -> list[dict[str, Any]]:
    g = _Gen(seed)
    _auth(g)
    _firewall(g)
    _dns(g)
    _edr(g)
    return g.rows


def write_lake(lake_dir: Path, seed: int = 7) -> int:
    rows = build_rows(seed)
    LakeWriter(lake_dir).write(rows)
    return len(rows)
