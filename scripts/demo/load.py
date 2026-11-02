#!/usr/bin/env python3
"""Load the demo data into a running demo server (`make demo` runs this for you).

    cd backend && uv run python ../scripts/demo/load.py --url http://127.0.0.1:8090 --logs <folder>

The server must be on loopback with no accounts (open mode), with the logs folder under
`paths.allowed_roots` and `enrichment.place_documentation_ranges` on. This script:

1. installs a synthetic GeoIP country and ASN file (documentation ranges only, invented
   networks and organizations), and sets the approved country and the internal networks
2. adds one file source per folder that `generate.py` wrote
3. adds an OTLP source and sends Claude Code hook and telemetry records for a few people
4. marks some AI services approved or not approved, leaving DeepSeek unreviewed, and
   approves two MCP servers and marks one (paste-share) not approved

Synthetic only: example.com people, corp.internal hosts, documentation addresses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

FORMATS = {
    "m365_signin": "json",
    "m365_directory_audit": "json",
    "m365_management_activity": "json",
    "linux_sshd": "syslog",
    "paloalto_traffic": "syslog",
    "dns_bind": "syslog",
}
# Who uses Claude Code, and on which machine. Hook records for some, telemetry for others.
CODERS = [("alice", "ws-0040", "hooks"), ("bob", "ws-0041", "telemetry"), ("dave", "ws-0043", "hooks"), ("grace", "ws-0046", "telemetry")]  # fmt: skip
MCP = [("github", "search_issues"), ("jira", "get_issue"), ("paste-share", "upload")]
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


class Client:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.csrf: str | None = None
        state = self.call("GET", "/api/auth/state")
        if state.get("mode") != "open":
            sys.exit("The demo loads into a loopback install with no accounts (open mode).")
        self.csrf = state.get("csrf_token")

    def call(self, method: str, path: str, body: Any = None, raw: bytes | None = None, token: str | None = None) -> Any:  # fmt: skip
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)  # noqa: S310  # the URL the operator passed
        req.add_header(
            "Content-Type", "application/octet-stream" if raw is not None else "application/json"
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        elif self.csrf:
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with urllib.request.urlopen(req, timeout=120) as res:  # noqa: S310  # same
                out = res.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{method} {path}: HTTP {exc.code} {detail}") from None
        return json.loads(out) if out else None


def wait_for(url: str, seconds: float = 90) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/auth/state", timeout=3):  # noqa: S310  # same
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(1)
    sys.exit(f"no server at {url} after {seconds:.0f} s")


def geoip_files(folder: Path) -> tuple[bytes, bytes]:
    """Country and ASN files for documentation ranges only. The attacking addresses are in
    one country that is not approved; everything else is in the approved one."""
    from mmdb_writer import MMDBWriter
    from netaddr import IPSet

    places = [
        ("203.0.113.0/25", "NL", "Netherlands", 64500, "Example Hosting B.V."),
        ("203.0.113.128/25", "DE", "Germany", 64502, "Example Cloud GmbH"),
        ("198.51.100.0/24", "US", "United States", 64501, "Example Fiber"),
        ("192.0.2.0/24", "US", "United States", 64503, "Example Cable"),
    ]
    country = MMDBWriter(6, "DBIP-Country-Lite", ["en"], "Remnant demo (synthetic)", ipv4_compatible=True)  # fmt: skip
    asn = MMDBWriter(6, "DBIP-ASN-Lite (compat=GeoLite2-ASN)", ["en"], "Remnant demo (synthetic)", ipv4_compatible=True)  # fmt: skip
    for net, iso, name, num, org in places:
        country.insert_network(IPSet([net]), {"country": {"iso_code": iso, "names": {"en": name}}})
        asn.insert_network(IPSet([net]), {"autonomous_system_number": num, "autonomous_system_organization": org})  # fmt: skip
    out = []
    for kind, w in (("country", country), ("asn", asn)):
        path = folder / f"{kind}.mmdb"
        w.to_db_file(str(path))
        out.append(path.read_bytes())
    return out[0], out[1]


def value(v: object) -> dict[str, object]:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def otlp(service: str, scope: str, host: str, records: list[tuple[datetime, str, dict[str, object]]]) -> dict[str, object]:  # fmt: skip
    resource = {"service.name": service, "host.name": host}
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [{"key": k, "value": value(v)} for k, v in resource.items()]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": scope},
                        "logRecords": [
                            {
                                "timeUnixNano": str(int(t.timestamp()) * 1_000_000_000),
                                "body": {"stringValue": body},
                                "attributes": [
                                    {"key": k, "value": value(v)}
                                    for k, v in a.items()
                                    if v not in (None, "")
                                ],  # fmt: skip
                            }
                            for t, body, a in records
                        ],
                    }
                ],
            }
        ]
    }


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def coding_sessions(now: datetime) -> list[dict[str, object]]:
    """OTLP bodies: a few sessions a day for each person over the last two weeks."""
    rng = random.Random(7)
    bodies: list[dict[str, object]] = []
    for user, host, kind in CODERS:
        email = f"{user}@example.com"
        seq = 0
        for d in range(14, -1, -1):
            for n in range(rng.randint(1, 3)):
                t = (now - timedelta(days=d)).replace(hour=rng.randint(9, 16), minute=rng.randint(0, 59), second=0)  # fmt: skip
                if t > now:
                    continue
                session = f"sess-{user}-{d}-{n}"
                recs: list[tuple[datetime, str, dict[str, object]]] = []
                tools = rng.sample(["Read", "Edit", "Bash", "Grep", "WebFetch"], 3)
                if rng.random() < 0.5:
                    server, tool = rng.choice(MCP[:2] if user != "dave" else MCP)
                    tools.append(f"mcp__{server}__{tool}")
                if kind == "hooks":
                    events: list[tuple[str, str, dict[str, object]]] = [("session_start", "session", {"session_source": "startup"})]  # fmt: skip
                    prompt = f"fix the failing test in module {n}"
                    events.append(("user_prompt_submit", "user", {"prompt_sha256": sha(prompt), "prompt_chars": len(prompt)}))  # fmt: skip
                    for tool in tools:
                        extra: dict[str, object] = {"tool_name": tool}
                        if tool.startswith("mcp__"):
                            _, server, name = tool.split("__")
                            extra |= {"mcp_server_name": server, "mcp_tool_name": name}
                        elif tool == "WebFetch":
                            extra["web_host"] = "docs.example.com"
                        elif tool == "Bash":
                            extra["program"] = rng.choice(["pytest", "git", "make"])
                        else:
                            extra["path"] = (
                                f"/home/{user}/app/src/{rng.choice(['main', 'auth', 'api'])}.py"
                            )
                        events.append(("pre_tool_use", "tool_call", extra))
                        if tool == "Bash" and rng.random() < 0.2:
                            events.append(("post_tool_use_failure", "tool_result", {**extra, "error_chars": rng.randint(40, 400)}))  # fmt: skip
                        else:
                            events.append(("post_tool_use", "tool_result", {**extra, "tool_response_chars": rng.randint(10, 20000)}))  # fmt: skip
                    events.append(("stop", "session", {}))
                    events.append(("session_end", "session", {"reason": "prompt_input_exit"}))
                    for name, role, extra in events:
                        t += timedelta(seconds=rng.randint(2, 40))
                        seq += 1
                        attrs = {"event_name": f"claude_hooks.{name}", "role": role, "session_id": session, "user": email, "os_user": user, "cwd": f"/home/{user}/app", "install_id": f"demo-{user}", "seq": str(seq), "plugin_variant": "posix", **extra}  # fmt: skip
                        recs.append((t, f"claude_hooks.{name}", attrs))
                    bodies.append(otlp("claude-hooks", "claude-hooks", host, recs))
                else:
                    base = {"user.email": email, "user.account_uuid": f"acct-{user}", "organization.id": "org-0001", "session.id": session, "terminal.type": "vscode"}  # fmt: skip
                    model = rng.choice(MODELS)
                    t += timedelta(seconds=5)
                    recs.append((t, "claude_code.user_prompt", {**base, "event.name": "user_prompt", "prompt_length": rng.randint(20, 900)}))  # fmt: skip
                    for tool in tools:
                        t += timedelta(seconds=rng.randint(3, 30))
                        recs.append((t, "claude_code.api_request", {**base, "event.name": "api_request", "model": model, "cost_usd": round(rng.uniform(0.002, 0.2), 4), "duration_ms": rng.randint(800, 9000), "input_tokens": rng.randint(500, 40000), "output_tokens": rng.randint(50, 4000), "cache_read_tokens": rng.randint(0, 30000), "cache_creation_tokens": 0}))  # fmt: skip
                        if tool.startswith("mcp__"):
                            _, server, name = tool.split("__")
                            params = json.dumps({"mcp_server_name": server, "mcp_tool_name": name})
                            recs.append((t, "claude_code.tool_decision", {**base, "event.name": "tool_decision", "tool_name": "mcp_tool", "decision": "accept", "source": "config", "tool_source": "mcp", "tool_parameters": params}))  # fmt: skip
                            recs.append((t, "claude_code.tool_result", {**base, "event.name": "tool_result", "tool_name": "mcp_tool", "success": "true", "duration_ms": rng.randint(50, 3000), "tool_parameters": params, "mcp_server_scope": "user"}))  # fmt: skip
                        else:
                            recs.append((t, "claude_code.tool_decision", {**base, "event.name": "tool_decision", "tool_name": tool, "decision": "accept", "source": "user_temporary", "tool_source": "builtin"}))  # fmt: skip
                            recs.append((t, "claude_code.tool_result", {**base, "event.name": "tool_result", "tool_name": tool, "success": "true", "duration_ms": rng.randint(5, 900)}))  # fmt: skip
                    bodies.append(
                        otlp("claude-code", "com.anthropic.claude_code.events", host, recs)
                    )
    return bodies


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8090")
    ap.add_argument("--logs", type=Path, required=True, help="the folder generate.py wrote")
    args = ap.parse_args()
    wait_for(args.url.rstrip("/"))
    api = Client(args.url)

    with tempfile.TemporaryDirectory() as tmp:
        country, asn = geoip_files(Path(tmp))
    api.call("POST", "/api/enrichment/feeds/geoip_country/upload", raw=country)
    api.call("POST", "/api/enrichment/feeds/geoip_asn/upload", raw=asn)
    api.call("PUT", "/api/enrichment/places", {"approved_countries": ["US"], "internal_networks": ["10.0.0.0/8"]})  # fmt: skip
    print("GeoIP: synthetic country and ASN files; approved country US")

    have = {s["source_id"] for s in api.call("GET", "/api/sources")}
    for tid, fmt in FORMATS.items():
        folder = args.logs.resolve() / tid
        if tid in have or not folder.is_dir():
            continue
        body = {
            "source_id": tid,
            "format": fmt,
            "path": str(folder),
            "glob": "*.log",
            "template_id": tid,
        }
        api.call("POST", "/api/sources", body)
        print(f"source {tid}")

    if "claude" not in have:
        made = api.call("POST", "/api/sources", {"source_id": "claude", "kind": "otlp", "format": "json", "template_id": "auto"})  # fmt: skip
        token = made["otlp_token"]
        bodies = coding_sessions(datetime.now(UTC))
        for body in bodies:
            api.call("POST", "/api/otlp/v1/logs", body, token=token)
        print(f"source claude: {len(bodies)} Claude Code sessions over OTLP")

    for svc, status in (("claude", "approved"), ("anthropic_api", "approved"), ("microsoft_copilot", "approved"), ("chatgpt", "approved"), ("gemini", "not_approved")):  # fmt: skip
        api.call("PUT", f"/api/ai/services/{svc}/status", {"status": status})
    api.call("PUT", "/api/ai/mcp-rules", {"pattern": "github", "status": "approved"})
    api.call("PUT", "/api/ai/mcp-rules", {"pattern": "jira", "status": "approved"})
    api.call("PUT", "/api/ai/mcp-rules", {"pattern": "paste-share", "status": "not_approved"})
    print("AI services reviewed (DeepSeek left unreviewed); MCP servers reviewed")
    print("done: the first ingest pass takes a few seconds")


if __name__ == "__main__":
    main()
