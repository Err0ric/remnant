"""Sign-in for development tools that drive a throwaway server (speed check, smoke test,
demo, screenshots).

There is no no-sign-in mode (D245): a server with no accounts only accepts the one-time
setup link. A tool that starts such a server makes its first administrator here, with the
link `app-admin setup-link` prints on the server, and a password generated for that run.
The account is written to `dev-account.json` (mode 0600) in the server's data folder, so
a later tool, or a person opening the demo, can sign in. Never used for a real install.
"""

import http.cookiejar
import json
import os
import secrets
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_FILE = "dev-account.json"
USERNAME = "admin"
LINK = [sys.executable, "-c", "from app.admin import main; main()", "setup-link"]


@dataclass(frozen=True)
class Session:
    cookie: str  # a Cookie header value
    csrf: str

    def headers(self) -> dict[str, str]:
        return {"Cookie": self.cookie, "X-CSRF-Token": self.csrf}


def _post(url: str, path: str, body: dict[str, str]) -> Session:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST")  # noqa: S310  # the tool's own server
    req.add_header("Content-Type", "application/json")
    with opener.open(req, timeout=60) as res:
        out: dict[str, Any] = json.loads(res.read())
    return Session("; ".join(f"{c.name}={c.value}" for c in jar), str(out.get("csrf_token") or ""))


def account(data: Path) -> dict[str, str] | None:
    """The account an earlier run made for the server on this data folder, if any."""
    try:
        found: dict[str, str] = json.loads((data / ACCOUNT_FILE).read_text())
        return found
    except (OSError, ValueError):
        return None


def sign_in(
    url: str,
    data: Path,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    python: str = sys.executable,
) -> Session | None:
    """A signed-in administrator session on the server at `url`, whose data folder is
    `data`. `env` and `cwd` are the server's own (default: this process's environment and
    the backend folder), so the link command opens the same database. None for a server
    from before D245 that still runs without accounts (the speed check's "before" side)."""
    with urllib.request.urlopen(url + "/api/auth/state", timeout=10) as res:  # noqa: S310  # same
        mode = json.loads(res.read()).get("mode")
    if mode == "open":
        return None
    known = account(data)
    if mode == "login":
        if known is None:
            raise RuntimeError(f"{url} has accounts, but {data / ACCOUNT_FILE} is missing")
        return _post(url, "/api/auth/login", known)
    # The command must open this server's database, whatever the caller's environment says.
    run_env = (env if env is not None else dict(os.environ)) | {"APP__PATHS__DATA_DIR": str(data)}
    out = subprocess.run(  # noqa: S603  # fixed command, the server's own admin tool
        [python, *LINK[1:]],
        env=run_env,
        cwd=cwd or ROOT / "backend",
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    if out.returncode != 0 or "/setup#" not in out.stdout:
        raise RuntimeError(f"no setup link for {url}: {out.stderr.strip() or out.stdout.strip()}")
    token = out.stdout.split("/setup#", 1)[1].split()[0]
    made = {"username": USERNAME, "password": secrets.token_urlsafe(18)}
    session = _post(url, "/api/setup", {"token": token, **made})
    path = data / ACCOUNT_FILE
    path.touch(mode=0o600)
    path.write_text(json.dumps(made))
    return session
