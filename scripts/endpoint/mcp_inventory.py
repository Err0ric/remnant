#!/usr/bin/env python3
"""List the MCP servers configured on this machine, one JSON line per server (ADR-0015 row 6).

Reads the MCP configuration of Claude Desktop, Claude Code, Cursor, VS Code, and Windsurf
for the current user, or for every user under the home folder when run as root/admin.
Prints names only: server name, client, transport, the launcher command's name (npx, uvx,
docker, ...), the package name a launcher runs, and the host of a remote server's URL.
It never prints arguments, environment variables, headers, or full URLs: those often hold
tokens.

    python3 mcp_inventory.py                       # JSON lines to stdout
    python3 mcp_inventory.py --out /var/log/mcp-inventory.jsonl   # append to a file
    python3 mcp_inventory.py --endpoint https://siem.example.internal:8080/api/otlp \\
        --token-file /etc/remnant/mcp-inventory.token  [--ca /etc/remnant/ca.pem]

Python 3.8+, standard library only. Exit 0 even when nothing is configured.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import socket
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

# (client, path relative to the home folder, key holding the server map)
WINDOWS = [
    ("claude_desktop", "AppData/Roaming/Claude/claude_desktop_config.json", "mcpServers"),
    ("vscode", "AppData/Roaming/Code/User/mcp.json", "servers"),
]
MAC = [
    ("claude_desktop", "Library/Application Support/Claude/claude_desktop_config.json", "mcpServers"),
    ("vscode", "Library/Application Support/Code/User/mcp.json", "servers"),
]
LINUX = [
    ("claude_desktop", ".config/Claude/claude_desktop_config.json", "mcpServers"),
    ("vscode", ".config/Code/User/mcp.json", "servers"),
]
EVERYWHERE = [
    ("claude_code", ".claude.json", "mcpServers"),
    ("cursor", ".cursor/mcp.json", "mcpServers"),
    ("windsurf", ".codeium/windsurf/mcp_config.json", "mcpServers"),
]
PACKAGE = re.compile(r"^(@[a-z0-9][\w.-]*/)?[a-z0-9][\w.-]*(@[\w.^~<>=*-]+)?$", re.I)
LAUNCHERS = {"npx", "npx.cmd", "uvx", "bunx", "pnpm", "pipx", "dlx"}
MAX_FILE = 5 * 1024 * 1024


def homes() -> list[tuple[str, Path]]:
    """(user, home) pairs: everyone's when privileged, else the current user's."""
    me = Path.home()
    privileged = (hasattr(os, "geteuid") and os.geteuid() == 0) or _is_windows_admin()
    if not privileged:
        return [(getpass.getuser(), me)]
    skip = {"Public", "Default", "Default User", "All Users", "Shared"}
    found: list[tuple[str, Path]] = []
    try:
        for d in sorted(me.parent.iterdir()):
            if d.is_dir() and not d.is_symlink() and d.name not in skip:
                found.append((d.name, d))
    except OSError:
        pass
    if os.name != "nt" and Path("/root").is_dir() and all(h != Path("/root") for _, h in found):
        found.append(("root", Path("/root")))
    return found or [(getpass.getuser(), me)]


def _is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def locations() -> list[tuple[str, str, str]]:
    system = platform.system()
    native = WINDOWS if system == "Windows" else MAC if system == "Darwin" else LINUX
    return native + EVERYWHERE


def load(path: Path) -> Any:
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE:
            return None
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None


def server_maps(client: str, doc: Any, key: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """(scope, servers) found in one config file."""
    if not isinstance(doc, dict):
        return
    if isinstance(doc.get(key), dict):
        yield "user", doc[key]
    if client == "vscode" and isinstance(doc.get("mcp"), dict) and isinstance(doc["mcp"].get("servers"), dict):
        yield "user", doc["mcp"]["servers"]
    if client == "claude_code" and isinstance(doc.get("projects"), dict):
        for project in doc["projects"].values():
            if isinstance(project, dict) and isinstance(project.get("mcpServers"), dict):
                yield "project", project["mcpServers"]


def describe(entry: Any) -> dict[str, Any]:
    """Transport, launcher, package, URL host. Never args values, env, headers, or URLs."""
    if not isinstance(entry, dict):
        return {"transport": "unknown", "command": None, "package": None, "url_host": None}
    url = entry.get("url") or entry.get("serverUrl")
    if isinstance(url, str) and url:
        try:
            host = urlsplit(url).hostname
        except ValueError:
            host = None
        kind = entry.get("type") if entry.get("type") in ("http", "sse", "streamable-http") else "http"
        return {"transport": kind, "command": None, "package": None, "url_host": host}
    command = entry.get("command")
    name = Path(command).name if isinstance(command, str) and command else None
    package = None
    args = entry.get("args")
    if name and name.lower() in LAUNCHERS and isinstance(args, list):
        for a in args:
            if isinstance(a, str) and not a.startswith("-") and PACKAGE.match(a):
                package = _package_name(a)
                break
    return {"transport": "stdio", "command": name, "package": package, "url_host": None}


def _package_name(spec: str) -> str:
    """`@scope/name@1.2` -> `@scope/name`, `name@1.2` -> `name` (the version is dropped)."""
    at = spec.find("@", 1)
    return spec if at < 0 else spec[:at]


def inventory() -> Iterator[dict[str, Any]]:
    host = socket.gethostname()
    now = datetime.now(timezone.utc).isoformat()
    for user, home in homes():
        for client, rel, key in locations():
            path = home / rel
            doc = load(path)
            if doc is None:
                continue
            seen = set()
            for scope, servers in server_maps(client, doc, key):
                for name, entry in servers.items():
                    if not isinstance(name, str) or (scope, name) in seen:
                        continue
                    seen.add((scope, name))
                    yield {
                        "event": "mcp_inventory",
                        "time": now,
                        "host": host,
                        "os_user": user,
                        "client": client,
                        "server": name[:200],
                        "scope": scope,
                        "config": str(path),
                        **describe(entry),
                    }


def otlp_body(records: list[dict[str, Any]]) -> dict[str, Any]:
    def value(v: Any) -> dict[str, Any]:
        return {"stringValue": str(v)}

    nanos = str(time.time_ns())
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": value("remnant-mcp-inventory")},
                        {"key": "host.name", "value": value(socket.gethostname())},
                    ]
                },
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": nanos,
                                "attributes": [{"key": "event.name", "value": value("mcp_inventory")}]
                                + [
                                    {"key": k, "value": value(v)}
                                    for k, v in r.items()
                                    if k not in ("event", "time") and v is not None
                                ],
                            }
                            for r in records
                        ]
                    }
                ],
            }
        ]
    }


def send(records: list[dict[str, Any]], endpoint: str, token: str, ca: str | None) -> None:
    if not endpoint.startswith("https://") and not endpoint.startswith("http://127.0.0.1"):
        raise SystemExit("The endpoint must use https")
    context = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    for start in range(0, len(records), 500):
        data = json.dumps(otlp_body(records[start : start + 500])).encode()
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/v1/logs",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=30, context=context) as res:  # noqa: S310  # https checked above
            res.read()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="List configured MCP servers (names only).")
    p.add_argument("--out", help="append JSON lines to this file instead of printing")
    p.add_argument("--endpoint", help="Remnant OTLP base, e.g. https://siem:8080/api/otlp")
    p.add_argument("--token-file", help="file holding the source's ingest token")
    p.add_argument("--ca", help="CA bundle that signed Remnant's certificate")
    args = p.parse_args(argv)
    records = list(inventory())
    if args.endpoint:
        if not args.token_file:
            p.error("--endpoint needs --token-file (a token on the command line shows in ps)")
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
        if records:
            send(records, args.endpoint, token, args.ca)
        print(f"sent {len(records)} servers", file=sys.stderr)
        return 0
    text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
