"""Generate the linux_sshd template fixtures (CLAUDE.md section 6).

    python scripts/fixtures/linux_sshd.py backend/tests/fixtures/logs/linux_sshd

Writes sample.log (real-shaped OpenSSH 9.x lines through rsyslog, RFC 3164 and 5424,
synthetic values), expected.jsonl (what the first 10 lines must parse to, written from the
generator's own knowledge of each line, not from the template), and pathological.log.
Deterministic: the same seed always gives the same files.
"""

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

HOSTS = ("bastion", "web-01", "db-01")
USERS = ("alice", "bob", "carol", "deploy")
INVALID = ("admin", "oracle", "test", "ubuntu")
INTERNAL = ("10.20.1.5", "10.20.1.6", "10.20.2.14")
EXTERNAL = ("203.0.113.9", "198.51.100.4", "203.0.113.77")


def main(out: Path, seed: int = 11) -> None:
    rng = random.Random(seed)  # noqa: S311  # deterministic test data
    t = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
    lines: list[str] = []
    expected: list[dict[str, object]] = []

    def emit(host: str, pid: int, msg: str, exp: dict[str, object], rfc5424: bool = False) -> None:
        nonlocal t
        t += timedelta(seconds=rng.randrange(1, 90))
        if rfc5424:
            lines.append(f"<86>1 {t:%Y-%m-%dT%H:%M:%SZ} {host} sshd {pid} - - {msg}")
        else:
            lines.append(f"<38>{t:%b} {t.day:>2} {t:%H:%M:%S} {host} sshd[{pid}]: {msg}")
        expected.append(
            {"time": t.isoformat(), "device_hostname": host, "actor_process_pid": pid, **exp}
        )

    for i in range(64):
        host = rng.choice(HOSTS)
        pid = rng.randrange(1000, 65000)
        kind = rng.choice(("ok", "ok", "fail", "invalid", "closed", "session", "disc"))
        port = rng.randrange(1024, 65535)
        if kind == "ok":
            user, ip = rng.choice(USERS), rng.choice(INTERNAL)
            emit(host, pid, f"Accepted publickey for {user} from {ip} port {port} ssh2: ED25519 SHA256:Zm9v",
                 {"actor_user_name": user, "src_endpoint_ip": ip, "src_endpoint_port": port,
                  "status_id": 1, "activity_id": 1, "parse_status": "ok"}, rfc5424=i % 9 == 0)
        elif kind == "fail":
            user, ip = rng.choice(USERS), rng.choice(EXTERNAL)
            emit(host, pid, f"Failed password for {user} from {ip} port {port} ssh2",
                 {"actor_user_name": user, "src_endpoint_ip": ip, "src_endpoint_port": port,
                  "status_id": 2, "activity_id": 1, "parse_status": "ok"})
        elif kind == "invalid":
            user, ip = rng.choice(INVALID), rng.choice(EXTERNAL)
            emit(host, pid, f"Invalid user {user} from {ip} port {port}",
                 {"actor_user_name": user, "src_endpoint_ip": ip, "src_endpoint_port": port,
                  "status_id": 2, "activity_id": 1, "parse_status": "ok"})
        elif kind == "closed":
            user, ip = rng.choice(INVALID), rng.choice(EXTERNAL)
            emit(host, pid, f"Connection closed by invalid user {user} {ip} port {port} [preauth]",
                 {"actor_user_name": user, "src_endpoint_ip": ip, "src_endpoint_port": port,
                  "status_id": 1, "activity_id": 2, "parse_status": "ok"})
        elif kind == "session":
            user = rng.choice(USERS)
            what = rng.choice(("opened", "closed"))
            suffix = " by (uid=0)" if what == "opened" else ""
            emit(host, pid, f"pam_unix(sshd:session): session {what} for user {user}{suffix}",
                 {"actor_user_name": user, "status_id": 1,
                  "activity_id": 1 if what == "opened" else 2, "parse_status": "ok"})
        else:
            user, ip = rng.choice(USERS), rng.choice(INTERNAL)
            emit(host, pid, f"Disconnected from user {user} {ip} port {port}",
                 {"actor_user_name": user, "src_endpoint_ip": ip, "src_endpoint_port": port,
                  "status_id": 1, "activity_id": 2, "parse_status": "ok"})
    # A few real lines the template does not model; they keep their envelope (<5%).
    emit("bastion", 811, "Timeout before authentication for 198.51.100.4 port 4022",
         {"parse_status": "envelope_only"})
    emit("bastion", 812, "Server listening on 0.0.0.0 port 22.",
         {"parse_status": "ok"})

    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.log").write_text("\n".join(lines) + "\n")
    with (out / "expected.jsonl").open("w") as fh:
        for exp in expected[:10]:
            fh.write(json.dumps(exp, sort_keys=True) + "\n")
    pathological = [
        "",
        " ",
        "<38>",
        "<999>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for x from 10.0.0.1 port 1",
        "<38>Oct  9 20:41:12 bastion sshd[1]: Accepted publickey for " + "a" * 9000 + " from 10.0.0.1 port 1",
        "<38>Oct  9 20:41:12 bastion sshd[1]: Failed password for user from 999.999.999.999 port 99999999999999999999",
        "<38>Oct  9 20:41:12 bastion sshd[1]: " + "Accepted " * 1200,
        "\x00\x01\x02\x1b[31m sshd[1]: Failed password for root from 10.0.0.1 port 22",
        "<38>Oct  9 20:41:12 bastion sshd[1]: pam_unix(sshd:session): session opened for user " + "(" * 5000,
        "x" * 10_240,
        "<38>Oct  9 20:41:12 relay1 <38>Oct  9 20:41:11 bastion sshd[2]: Accepted publickey for jordan from 10.0.0.1 port 2 ssh2",
        "  continuation of a multiline message without a header",
    ]
    (out / "pathological.log").write_text("\n".join(pathological) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
