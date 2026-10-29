"""Checks the Windows hooks plugin script (ADR-0026 amendment 2026-10-29) without the server:
under Windows PowerShell 5.1 on Windows (the `hooks-windows` workflow), or under PowerShell 7
(`pwsh`) elsewhere for a quick run. Needs Python 3.12 and `cryptography`.

    python scripts/check_hooks_windows.py

Covers what only Windows PowerShell 5.1 can show: reading a .claude.json that
ConvertFrom-Json refuses (an empty-string key, JavaScriptSerializer), and checking the
server against the CA named in CA_FILE on 5.1's own TLS stack (wrong CA, right CA, wrong
host name). Also: only {} on stdout, a hostile
403 changes nothing, a hung receiver costs about 2 seconds, and dropped records are counted.
"""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "backend" / "app" / "ai" / "claude_plugin" / "windows"
WINDOWS = os.name == "nt"
SHELL = shutil.which("powershell") if WINDOWS else shutil.which("pwsh")


class Catcher:
    def __init__(
        self, status: int = 200, reply: bytes = b"", delay: float = 0, tls: Any = None
    ) -> None:
        self.bodies: list[bytes] = []
        bodies = self.bodies

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                bodies.append(
                    self.rfile.read(int(self.headers.get("content-length", "0")))
                )
                time.sleep(delay)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *a: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(tls[0]), str(tls[1]))
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        scheme, host = ("https", "localhost") if tls else ("http", "127.0.0.1")
        self.url = f"{scheme}://{host}:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def attrs(self, i: int) -> dict[str, str]:
        log = json.loads(self.bodies[i])["resourceLogs"][0]["scopeLogs"][0][
            "logRecords"
        ][0]
        return {a["key"]: next(iter(a["value"].values())) for a in log["attributes"]}


def cert(folder: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Lab server")])
    now = datetime.now(UTC)
    c = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    folder.mkdir(parents=True)
    (folder / "c.pem").write_bytes(c.public_bytes(serialization.Encoding.PEM))
    (folder / "k.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return folder / "c.pem", folder / "k.pem"


def main() -> int:
    if not SHELL:
        print("PowerShell not found")
        return 1
    version = subprocess.run(
        [SHELL, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()  # fmt: skip
    print(f"PowerShell {version}")
    tmp = Path(tempfile.mkdtemp())
    plugin = tmp / "plugin"
    shutil.copytree(PLUGIN, plugin)
    home = tmp / "home"
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "projects": {"": {"emailAddress": "other@example.net"}},
                "oauthAccount": {"emailAddress": "dana@example.com"},
            }
        )
    )
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            failures.append(what)
            if os.environ.get(
                "GITHUB_ACTIONS"
            ):  # readable from the API without the raw log
                text = (
                    what.replace("%", "%25")
                    .replace("\r", "")
                    .replace("\n", "%0A")[:900]
                )
                print(f"::error title=hooks-windows::{text}")

    def run(url: str, extra: str = "", env: dict[str, str] | None = None) -> bytes:
        (plugin / "config").write_text(f"REMNANT_URL={url}\nREMNANT_TOKEN=t\n{extra}")
        e = dict(os.environ) if WINDOWS else {"PATH": os.environ["PATH"]}
        e.update(
            HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home), OS="Windows_NT",
            CLAUDE_PLUGIN_DATA=str(tmp / "data"),
        )  # fmt: skip
        for k in (
            "CLAUDE_CODE_USER_EMAIL",
            "CLAUDE_CONFIG_DIR",
            "CLAUDE_CODE_IS_COWORK",
        ):
            e.pop(k, None)
        e.update(env or {})
        hook = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Read",
                "tool_input": {"file_path": "C:\\Users\\dana\\a.txt", "": "x"}}  # fmt: skip
        done = subprocess.run(
            [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(plugin / "hooks" / "send.ps1")],
            input=json.dumps(hook).encode(), capture_output=True, env=e, timeout=60, check=False,
        )  # fmt: skip
        check(
            done.returncode == 0 and done.stdout.strip() == b"{}" and not done.stderr,
            f"only {{}} and exit 0 ({done.stdout[:60]!r} {done.stderr[:200]!r})",
        )
        return done.stdout

    def explain(url: str, extra: str = "") -> str:
        """Why nothing was sent: a copy whose catches print the error (never the data)."""
        (plugin / "config").write_text(f"REMNANT_URL={url}\nREMNANT_TOKEN=t\n{extra}")
        src = (plugin / "hooks" / "send.ps1").read_text().replace("\r\n", "\n")
        dbg = src.replace(
            "} catch { }\nFinish",
            "} catch { [Console]::Error.WriteLine($_.ToString() + ' @ line '"
            " + $_.InvocationInfo.ScriptLineNumber) }\nFinish",
        ).replace(
            "} catch { $sent = $false }",
            "} catch { [Console]::Error.WriteLine('send: ' + $_.Exception.ToString()); $sent = $false }",
        )
        (plugin / "hooks" / "debug.ps1").write_text(dbg)
        e = dict(os.environ, USERPROFILE=str(home), HOME=str(home), OS="Windows_NT",
                 CLAUDE_PLUGIN_DATA=str(tmp / "data"))  # fmt: skip
        hook = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Read",
                "tool_input": {"file_path": "C:\\Users\\dana\\a.txt", "": "x"}}  # fmt: skip
        done = subprocess.run(
            [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
             str(plugin / "hooks" / "debug.ps1")],
            input=json.dumps(hook).encode(), capture_output=True, env=e, timeout=60, check=False,
        )  # fmt: skip
        return done.stderr.decode(errors="replace")[:700]

    ok = Catcher()
    run(ok.url)
    if not ok.bodies:
        check(False, "nothing sent: " + explain(ok.url))
        return 1
    a = ok.attrs(0)
    check(
        a.get("claude_account_email") == "dana@example.com",
        "account email despite an empty key",
    )
    check(
        a.get("path") == "C:\\Users\\dana\\a.txt"
        and a.get("plugin_variant") == "windows",
        "metadata",
    )
    run(ok.url, env={"CLAUDE_CODE_IS_COWORK": "true"})
    check(len(ok.bodies) == 1, "a Cowork session sends nothing")

    deny = b'{"hookSpecificOutput":{"permissionDecision":"deny"}}'
    hostile = Catcher(status=403, reply=deny)
    out = run(hostile.url)
    check(b"deny" not in out, "a 403 with a deny body is not echoed")
    hung = Catcher(delay=30)
    started = time.monotonic()
    run(hung.url)
    took = time.monotonic() - started
    check(took < 10, f"a hung receiver costs little ({took:.1f} s)")
    run(ok.url)
    check(ok.attrs(1).get("queued_at_send") == "2", "two records waited in the queue")
    backlog = json.loads(ok.bodies[2])["resourceLogs"][0]["scopeLogs"][0]["logRecords"] if len(ok.bodies) > 2 else []
    check(len(backlog) == 2, "the queue went out after the live record")

    c, k = cert(tmp / "tls")
    other, _ = cert(tmp / "other")
    server = Catcher(tls=(c, k))

    def sends(url: str, ca: Path) -> bool:
        before = len(server.bodies)
        run(url, f"CA_FILE={ca}\n")
        return len(server.bodies) > before

    check(not sends(server.url, other), "the wrong CA: nothing sent")
    right = sends(server.url, c)
    why = "" if right else ": " + explain(server.url, f"CA_FILE={c}\n")
    check(right, "the right CA: sent" + why)
    check(
        not sends(server.url.replace("localhost", "127.0.0.1"), c),
        "the right CA under another name: refused",
    )
    print(f"{len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a crash is reported where the API can read it too
        import traceback

        text = traceback.format_exc()
        print(text)
        if os.environ.get("GITHUB_ACTIONS"):
            short = (
                text[-900:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            )
            print(f"::error title=hooks-windows crash::{short}")
        sys.exit(1)
