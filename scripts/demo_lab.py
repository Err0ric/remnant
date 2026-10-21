#!/usr/bin/env python3
"""Load a demo lab into a running server: every starter template's synthetic fixture as a
file source, a few Sigma rules (imported, enabled, and run), and AI review settings.

Synthetic data only (the fixtures under backend/tests/fixtures/logs). For a fresh install
on loopback with no accounts (open mode); it talks HTTP like the CLI.

    python3 scripts/demo_lab.py --url http://127.0.0.1:8080 --logs /srv/logs/demo \
        --rules /srv/rules/demo

`--logs` must be under the server's allowed_roots and `--rules` under its rule_roots. Run it
once per install: sources that already exist are skipped.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "backend" / "tests" / "fixtures" / "logs"

# Sources: id -> (template, format). JSON fixtures are JSON lines; the rest syslog or CSV.
CSV = {"paloalto_traffic", "paloalto_threat", "paloalto_system", "paloalto_globalprotect",
       "paloalto_userid", "windows_snare"}  # fmt: skip
JSON = {"windows_nxlog_json", "windows_winlogbeat", "claude_code_otel", "mcp_inventory",
        "m365_management_activity", "m365_signin", "m365_directory_audit", "m365_alert",
        "anthropic_reports"}  # fmt: skip
SKIP = {"windows_evtx"}  # binary .evtx fixtures are not lines

RULES = {
    "ssh_failed.yml": """title: SSH failed password
id: 0a7e1c52-1111-4111-8111-000000000001
level: high
logsource: {product: linux}
detection:
  k: ['Failed password']
  condition: k
""",
    "ssh_invalid_user.yml": """title: SSH login attempt for an unknown user
id: 0a7e1c52-1111-4111-8111-000000000002
level: medium
logsource: {product: linux}
detection:
  k: ['Invalid user']
  condition: k
""",
    "sudo_root.yml": """title: Sudo to root
id: 0a7e1c52-1111-4111-8111-000000000003
level: low
logsource: {product: linux}
detection:
  k: ['USER=root']
  condition: k
""",
    "win_failed_logon.yml": """title: Windows failed logon
id: 0a7e1c52-1111-4111-8111-000000000004
level: medium
logsource: {product: windows, service: security}
detection:
  s: {EventID: 4625}
  condition: s
""",
    "win_group_change.yml": """title: Member added to a security-enabled group
id: 0a7e1c52-1111-4111-8111-000000000005
level: high
logsource: {product: windows, service: security}
detection:
  s: {EventID: [4728, 4732, 4756]}
  condition: s
""",
}


class Client:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.csrf: str | None = None
        state = self.call("GET", "/api/auth/state")
        if state.get("mode") != "open":
            sys.exit("This script is for a loopback install with no accounts (open mode).")
        self.csrf = state.get("csrf_token")

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)  # noqa: S310  # the URL the operator passed
        req.add_header("Content-Type", "application/json")
        if self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with urllib.request.urlopen(req, timeout=120) as res:  # noqa: S310  # same
                raw = res.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{method} {path}: HTTP {exc.code} {detail}") from None
        return json.loads(raw) if raw else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--logs", type=Path, required=True)
    ap.add_argument("--rules", type=Path, required=True)
    ap.add_argument("--days", type=int, default=30, help="range to run rules over")
    args = ap.parse_args()
    api = Client(args.url)

    have = {s["source_id"] for s in api.call("GET", "/api/sources")}
    for folder in sorted(p for p in FIX.iterdir() if p.is_dir()):
        tid = folder.name
        if tid in SKIP or tid in have or not (folder / "sample.log").is_file():
            continue
        dest = args.logs / tid
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(folder / "sample.log", dest / "sample.log")
        fmt = "json" if tid in JSON else "csv" if tid in CSV else "syslog"
        body = {
            "source_id": tid,
            "format": fmt,
            "path": str(dest),
            "glob": "*.log",
            "template_id": tid,
        }
        try:
            api.call("POST", "/api/sources", body)
            print(f"source {tid}")
        except RuntimeError as exc:
            print(f"skipped {tid}: {exc}")

    # DNS lookups of AI services from a few workstations, so AI usage and the AI flow have
    # something to show. Synthetic: RFC 5737 resolver, 10.20.x clients, example.com users.
    if "demo_ai_dns" not in have:
        dest = args.logs / "demo_ai_dns"
        dest.mkdir(parents=True, exist_ok=True)
        domains = ["chatgpt.com", "claude.ai", "gemini.google.com", "chat.deepseek.com",
                   "api.anthropic.com", "copilot.microsoft.com", "smithery.ai"]  # fmt: skip
        clients = ["10.20.1.5", "10.20.1.6", "10.20.2.14", "10.20.3.30"]
        now = time.time()
        lines = []
        for i in range(240):
            t = time.localtime(now - 3600 * 24 * 3 + i * 1080)
            stamp = time.strftime("%b %e %H:%M:%S", t)
            name = domains[(i * 7 + i // 5) % len(domains)]
            ip = clients[i % len(clients)]
            lines.append(
                f"<30>{stamp} ns1 named[900]: client {ip}#{40000 + i} ({name}): "
                f"query: {name} IN A +E(0)K (192.0.2.53)"
            )
        (dest / "ai.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        body = {"source_id": "demo_ai_dns", "format": "syslog", "path": str(dest),
                "glob": "*.log", "template_id": "dns_bind"}  # fmt: skip
        api.call("POST", "/api/sources", body)
        print("source demo_ai_dns")

    print("waiting for the first ingest pass ...")
    time.sleep(8)

    args.rules.mkdir(parents=True, exist_ok=True)
    for name, text in RULES.items():
        (args.rules / name).write_text(text, encoding="utf-8")
    api.call("POST", "/api/rules/import", {"path": str(args.rules)})
    ids = [
        line.split(": ", 1)[1]
        for t in RULES.values()
        for line in t.splitlines()
        if line.startswith("id: ")
    ]
    api.call("POST", "/api/rules/enabled", {"rule_ids": ids, "enabled": True})
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - args.days * 86400))
    for rid in ids:
        run = api.call("POST", f"/api/rules/{rid}/run", {"start": start, "end": end})
        print(f"rule {rid[-2:]}: {run['status']}, {run['match_count']} matches")

    for svc, status in (("deepseek", "not_approved"), ("claude", "approved")):
        try:
            api.call("PUT", f"/api/ai/services/{svc}/status", {"status": status})
        except RuntimeError as exc:
            print(f"AI service {svc}: {exc}")
    api.call("PUT", "/api/ai/mcp-rules", {"pattern": "paste-share", "status": "not_approved"})
    api.call("PUT", "/api/ai/mcp-rules", {"pattern": "github", "status": "approved"})
    print("done")


if __name__ == "__main__":
    main()
