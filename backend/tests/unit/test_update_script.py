"""scripts/update-systemd.sh fetches origin's main itself, fails loudly when the fetch
fails, says "already up to date" when nothing changed, and only reports "Updated to X"
when HEAD is origin/main (owner, 2026-11-01: an update reported success at the old commit).

Runs the real script against a local "origin" with systemctl, journalctl, pnpm, uv, and
id stubbed on PATH; the stubs record what they were asked to do."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "update-systemd.sh"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

STUBS = {
    "id": "echo 0",
    "systemctl": 'echo "systemctl $*" >> "$CALLS"; exit 0',
    "journalctl": 'echo "listening on https://127.0.0.1:8080"',
    "pnpm": 'echo "pnpm $*" >> "$CALLS"',
    "uv": 'echo "uv $*" >> "$CALLS"',
    "sleep": "exit 0",
}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}  # fmt: skip
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", name)
    return _git(repo, "rev-parse", "--short", "HEAD")


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Path]:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    _commit(work, "one")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main")
    install = tmp_path / "opt-remnant"
    _git(tmp_path, "clone", "-q", str(origin), str(install))
    (install / "frontend").mkdir()
    (install / "backend").mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in STUBS.items():
        (bin_ / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_ / name).chmod(0o755)
    return {"origin": origin, "work": work, "install": install, "bin": bin_,
            "calls": tmp_path / "calls"}  # fmt: skip


def _run(box: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{box['bin']}:{os.environ['PATH']}",
        "INSTALL_DIR": str(box["install"]),
        "CALLS": str(box["calls"]),
        "HOME": str(box["install"].parent),
    }
    return subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, env=env)


def _calls(box: dict[str, Path]) -> str:
    return box["calls"].read_text() if box["calls"].exists() else ""


def test_new_commits_are_installed_and_reported(box: dict[str, Path]) -> None:
    new = _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    res = _run(box)
    assert res.returncode == 0, res.stderr
    assert _git(box["install"], "rev-parse", "--short", "HEAD") == new
    assert f"Updated remnant to {new}." in res.stdout
    assert "systemctl stop remnant" in _calls(box) and "systemctl start remnant" in _calls(box)


def test_already_up_to_date_says_so_and_touches_nothing(box: dict[str, Path]) -> None:
    head = _git(box["install"], "rev-parse", "--short", "HEAD")
    res = _run(box)
    assert res.returncode == 0, res.stderr
    assert f"already up to date at {head}" in res.stdout
    assert "Updated" not in res.stdout
    assert _calls(box) == ""  # the service was never stopped


def test_a_failed_fetch_fails_loudly_and_changes_nothing(box: dict[str, Path]) -> None:
    _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    head = _git(box["install"], "rev-parse", "--short", "HEAD")
    box["origin"].rename(box["origin"].with_suffix(".gone"))  # the remote is unreachable
    res = _run(box)
    assert res.returncode != 0
    assert "git fetch from origin failed" in res.stderr and head in res.stderr
    assert "Updated" not in res.stdout and "up to date" not in res.stdout
    assert _git(box["install"], "rev-parse", "--short", "HEAD") == head
    assert _calls(box) == ""


def test_an_upstream_other_than_main_still_gets_origin_main(box: dict[str, Path]) -> None:
    """The fetch never relies on the branch's upstream: a checkout tracking another
    branch (one way to get "Updated to <old commit>") still moves to origin/main."""
    _git(box["work"], "push", "-q", "origin", "main:old")
    _git(box["install"], "fetch", "-q", "origin")
    _git(box["install"], "branch", "-q", "--set-upstream-to", "origin/old")
    new = _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    res = _run(box)
    assert res.returncode == 0, res.stderr
    assert _git(box["install"], "rev-parse", "--short", "HEAD") == new


def test_local_commits_are_refused_before_the_service_stops(box: dict[str, Path]) -> None:
    _commit(box["install"], "local-change")
    _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    res = _run(box)
    assert res.returncode != 0 and "not an ancestor" in res.stderr
    assert _calls(box) == ""
