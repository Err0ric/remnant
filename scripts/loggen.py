#!/usr/bin/env python3
"""Synthetic log generator for demos and homelab testing.

Writes realistic, entirely made-up logs in the layouts real collectors produce:

    <out>/syslog/<host-ip>/<program>.log   RFC 5424 lines, as rsyslog writes them
    <out>/apps/web.jsonl                   JSON lines from a web app
    <out>/vpn/sessions.csv                 CSV with a header row

Only RFC 5737 documentation addresses and generic names are used. Standard
library only, so it runs anywhere Python 3.10+ does.

    python3 scripts/loggen.py --out ./logs --backfill 2000 --rate 3
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

HOSTS = {
    "bastion": "192.0.2.10",
    "web-01": "192.0.2.21",
    "db-01": "192.0.2.31",
    "fw-edge": "192.0.2.1",
}
USERS = ["alice", "bob", "carol", "dave", "svc_backup", "svc_deploy"]
BAD_USERS = ["admin", "oracle", "test", "ubuntu", "root", "postgres"]
ATTACKERS = ["203.0.113.9", "203.0.113.77", "198.51.100.200"]
CLIENTS = [f"198.51.100.{n}" for n in range(10, 60)]
INTERNAL = [f"192.0.2.{n}" for n in range(100, 140)]
PATHS = ["/", "/login", "/api/orders", "/api/cart", "/static/app.js", "/admin", "/healthz"]

# Facility codes: auth=4, authpriv=10, daemon=3, kern=0, local0=16
FACILITY = {"sshd": 4, "sudo": 10, "systemd": 3, "kernel": 0, "filterlog": 16, "postgres": 16}


@dataclass
class Event:
    when: datetime
    kind: str  # "syslog", "web", or "vpn"
    host: str = ""
    program: str = ""
    severity: int = 6
    message: str = ""
    record: dict[str, object] | None = None


class Generator:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.pid = 4000

    def _pid(self) -> int:
        self.pid += self.rng.randint(1, 40)
        return self.pid

    def sshd(self, when: datetime) -> list[Event]:
        r = self.rng.random()
        if r < 0.15:  # brute-force burst from one address
            src = self.rng.choice(ATTACKERS)
            return [
                Event(
                    when + timedelta(seconds=i * 2),
                    "syslog",
                    "bastion",
                    "sshd",
                    5,
                    f"Failed password for invalid user {self.rng.choice(BAD_USERS)} "
                    f"from {src} port {self.rng.randint(30000, 65000)} ssh2",
                )
                for i in range(self.rng.randint(4, 12))
            ]
        user = self.rng.choice(USERS)
        src = self.rng.choice(INTERNAL)
        if r < 0.3:
            msg = f"Failed password for {user} from {src} port {self.rng.randint(30000, 65000)} ssh2"
            return [Event(when, "syslog", "bastion", "sshd", 5, msg)]
        method = self.rng.choice(["publickey", "publickey", "password"])
        msg = f"Accepted {method} for {user} from {src} port {self.rng.randint(30000, 65000)} ssh2"
        return [Event(when, "syslog", "bastion", "sshd", 6, msg)]

    def sudo(self, when: datetime) -> list[Event]:
        user = self.rng.choice(USERS)
        cmd = self.rng.choice(
            ["/usr/bin/apt update", "/usr/bin/systemctl restart nginx", "/usr/bin/journalctl -u ssh"]
        )
        host = self.rng.choice(["bastion", "web-01", "db-01"])
        msg = f"{user} : TTY=pts/{self.rng.randint(0, 3)} ; PWD=/home/{user} ; USER=root ; COMMAND={cmd}"
        return [Event(when, "syslog", host, "sudo", 5, msg)]

    def systemd(self, when: datetime) -> list[Event]:
        host = self.rng.choice(list(HOSTS)[:3])
        unit = self.rng.choice(["nginx.service", "postgresql.service", "cron.service"])
        if self.rng.random() < 0.1:
            return [Event(when, "syslog", host, "systemd", 3, f"{unit}: Failed with result 'exit-code'.")]
        return [Event(when, "syslog", host, "systemd", 6, f"Started {unit}.")]

    def firewall(self, when: datetime) -> list[Event]:
        action = "block" if self.rng.random() < 0.4 else "pass"
        src = self.rng.choice(ATTACKERS + CLIENTS)
        port = self.rng.choice([22, 443, 443, 443, 3389, 445, 8080])
        msg = (
            f"action={action} proto=tcp src={src} dst=192.0.2.21 sport={self.rng.randint(1024, 65000)} "
            f"dport={port} rule={'default-deny' if action == 'block' else 'allow-web'} bytes={self.rng.randint(60, 90000)}"
        )
        return [Event(when, "syslog", "fw-edge", "filterlog", 4 if action == "block" else 6, msg)]

    def web(self, when: datetime) -> list[Event]:
        status = self.rng.choices([200, 200, 200, 301, 404, 401, 500], k=1)[0]
        record: dict[str, object] = {
            "timestamp": when.isoformat().replace("+00:00", "Z"),
            "level": "error" if status >= 500 else "warn" if status >= 400 else "info",
            "client_ip": self.rng.choice(CLIENTS),
            "method": self.rng.choice(["GET", "GET", "GET", "POST"]),
            "path": self.rng.choice(PATHS),
            "status": status,
            "duration_ms": self.rng.randint(2, 900),
            "user": self.rng.choice(USERS + [None, None]),
            "message": f"HTTP {status}",
        }
        return [Event(when, "web", record=record)]

    def vpn(self, when: datetime) -> list[Event]:
        user = self.rng.choice(USERS[:4])
        ok = self.rng.random() > 0.15
        record: dict[str, object] = {
            "time": when.isoformat().replace("+00:00", "Z"),
            "user": user,
            "client_ip": self.rng.choice(CLIENTS + ATTACKERS[:1]),
            "result": "success" if ok else "failure",
            "reason": "" if ok else self.rng.choice(["bad password", "mfa timeout", "account locked"]),
            "gateway": "vpn-gw-01",
        }
        return [Event(when, "vpn", record=record)]

    def next(self, when: datetime) -> list[Event]:
        pick = self.rng.choices(
            [self.sshd, self.sudo, self.systemd, self.firewall, self.web, self.vpn],
            weights=[3, 1, 1, 3, 4, 1],
        )[0]
        return pick(when)


def rfc5424(ev: Event, pid: int) -> str:
    pri = FACILITY.get(ev.program, 1) * 8 + ev.severity
    ts = ev.when.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return f"<{pri}>1 {ts} {ev.host} {ev.program} {pid} - - {ev.message}\n"


class Writer:
    def __init__(self, out: Path) -> None:
        self.out = out

    def write(self, events: list[Event], gen: Generator) -> None:
        for ev in events:
            if ev.kind == "syslog":
                path = self.out / "syslog" / HOSTS[ev.host] / f"{ev.program}.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(rfc5424(ev, gen._pid()))
            elif ev.kind == "web":
                path = self.out / "apps" / "web.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(ev.record) + "\n")
            else:
                path = self.out / "vpn" / "sessions.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                new = not path.exists()
                assert ev.record is not None
                with path.open("a", encoding="utf-8", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(ev.record), lineterminator="\n")
                    if new:
                        w.writeheader()
                    w.writerow(ev.record)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("logs"), help="Folder to write into")
    p.add_argument("--backfill", type=int, default=0, help="Events to spread over the last 24 hours first")
    p.add_argument("--rate", type=float, default=2.0, help="Live events per second (0 = no live phase)")
    p.add_argument("--duration", type=float, default=0, help="Seconds of live output (0 = until stopped)")
    p.add_argument("--seed", type=int, default=None, help="Seed for repeatable output")
    args = p.parse_args(argv)

    rng = random.Random(args.seed)
    gen, writer = Generator(rng), Writer(args.out)
    now = datetime.now(UTC)
    if args.backfill:
        times = sorted(now - timedelta(seconds=rng.uniform(0, 86400)) for _ in range(args.backfill))
        written = 0
        for when in times:
            events = gen.next(when)
            writer.write(events, gen)
            written += len(events)
        print(f"Backfilled {written} events into {args.out}", flush=True)
    if args.rate <= 0:
        return 0
    print(f"Writing about {args.rate:g} events per second. Ctrl+C to stop.", flush=True)
    started = time.monotonic()
    try:
        while not args.duration or time.monotonic() - started < args.duration:
            writer.write(gen.next(datetime.now(UTC)), gen)
            time.sleep(rng.expovariate(args.rate))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
