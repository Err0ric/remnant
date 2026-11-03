"""Owner 2026-11-02, before the pilot: the hooks plugin leaves a status file (metadata only)
after every run, and the installer's doctor mode checks a machine end to end with a pass or
fail per check, never printing the token."""

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.integration.test_claude_hooks import (  # noqa: F401  # the fixture
    PLATFORMS,
    SESSION,
    Catcher,
    home_with,
    lab,
    plugin_for,
    quiet,
    run,
)


def status(home: Path) -> dict[str, str]:
    text = (home / "plugin-data" / "status").read_text()
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_each_run_leaves_a_status_without_the_token(
    lab: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    platform: str,
) -> None:
    catcher = Catcher()
    plugin, token = plugin_for(lab, tmp_path, platform, catcher.url)
    home = home_with(tmp_path)
    assert quiet(run(plugin, SESSION[0], home, platform))
    st = status(home)
    assert st["result"] == "sent" and st["http_status"] == "200"
    assert st["last_event"] == "SessionStart" and st["config"] == "plugin"
    assert st["plugin_variant"] == platform and st["last_run"].endswith("Z")
    raw = (home / "plugin-data" / "status").read_text()
    assert token not in raw and token[4:] not in raw


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_refused_token_shows_as_queued_with_the_status_code(
    lab: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    platform: str,
) -> None:
    catcher = Catcher(status=401)
    plugin, _ = plugin_for(lab, tmp_path, platform, catcher.url)
    home = home_with(tmp_path)
    assert quiet(run(plugin, SESSION[0], home, platform))
    st = status(home)
    assert st["result"] == "queued: not sent" and st["http_status"] == "401"
    assert st["queue"] == "1"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_why_nothing_was_sent_is_written_down(
    lab: dict[str, Any],  # noqa: F811
    tmp_path: Path,
    platform: str,
) -> None:
    catcher = Catcher()
    plugin, _ = plugin_for(lab, tmp_path, platform, catcher.url, pilot_users=["erin@example.com"])
    home = home_with(tmp_path)
    assert quiet(run(plugin, SESSION[0], home, platform))
    assert status(home)["result"] == "skipped: not in PILOT_USERS"
    (plugin / "config").unlink()
    assert quiet(run(plugin, SESSION[0], home, platform))
    assert status(home)["result"] == "skipped: no config file"
    assert catcher.bodies == []


class _Server:
    """GET /api/health answers 200; POST answers `post_status`."""

    def __init__(self, post_status: int) -> None:
        self.posts: list[bytes] = []
        posts = self.posts

        class H(BaseHTTPRequestHandler):
            def _answer(self, code: int) -> None:
                self.send_response(code)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def do_GET(self) -> None:  # http.server's name
                self._answer(200 if self.path == "/api/health" else 404)

            def do_POST(self) -> None:  # http.server's name
                posts.append(self.rfile.read(int(self.headers.get("content-length", "0"))))
                self._answer(post_status)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def doctor(plugin: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    env["CLAUDE_PLUGIN_DATA"] = str(home / "plugin-data")
    return subprocess.run(
        ["sh", str(plugin / "install-local.sh"), "--doctor"],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip


@pytest.mark.skipif(os.name == "nt", reason="the shell installer")
def test_doctor_passes_a_working_machine_and_names_what_fails(
    lab: dict[str, Any],  # noqa: F811
    tmp_path: Path,
) -> None:
    ok = _Server(200)
    plugin, token = plugin_for(lab, tmp_path, "posix", ok.url)
    home = home_with(tmp_path)
    run(plugin, SESSION[0], home, "posix")  # the hook ran once: there is a status file
    done = doctor(plugin, home)
    assert done.returncode == 0, done.stdout
    assert "PASS  The token works: a test record was accepted (HTTP 200)" in done.stdout
    assert "PASS  The hook has run on this machine" in done.stdout
    assert "result=" in done.stdout and token not in done.stdout and token[:8] in done.stdout
    assert b'"test_record"' in ok.posts[-1]  # the doctor's record is marked as a test
    refused = _Server(401)
    text = (plugin / "config").read_text().replace(ok.url, refused.url)
    (plugin / "config").write_text(text)
    done = doctor(plugin, home)
    assert done.returncode == 1
    assert "FAIL  The server refused the token (HTTP 401)" in done.stdout
    (home / "plugin-data" / "status").unlink()
    assert "FAIL  No status file" in doctor(plugin, home).stdout
