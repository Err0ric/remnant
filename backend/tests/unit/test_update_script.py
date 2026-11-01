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
    "journalctl": '[ -n "${NOT_UP:-}" ] || echo "listening on https://127.0.0.1:8080"',
    "aideinit": 'echo "aideinit $*" >> "$CALLS"',
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


def _run(box: dict[str, Path], **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{box['bin']}:{os.environ['PATH']}",
        "INSTALL_DIR": str(box["install"]),
        "CALLS": str(box["calls"]),
        "HOME": str(box["install"].parent),
        "ENV_FILE": str(box["install"].parent / "no-env-file"),
        "AIDE_CONF_D": str(box["install"].parent / "no-aide"),
        "STATE_FILE": str(box["install"].parent / "installed_commit"),
        # CI does not run as root: the record is owned by whoever runs the tests there.
        "STATE_OWNER": f"{os.getuid()}:{os.getgid()}",
        **extra,
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


def _installed(box: dict[str, Path]) -> Path:
    return box["install"].parent / "installed_commit"


def _record(box: dict[str, Path], sha: str) -> None:
    """An installed commit as the script writes it (owner and mode it trusts)."""
    _installed(box).write_text(sha + "\n")
    _installed(box).chmod(0o644)


def test_already_up_to_date_says_so_and_touches_nothing(box: dict[str, Path]) -> None:
    head = _git(box["install"], "rev-parse", "--short", "HEAD")
    _record(box, _git(box["install"], "rev-parse", "HEAD"))
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


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to give the checkout away")
def test_dubious_ownership_is_explained_and_nothing_changes(box: dict[str, Path]) -> None:
    """Under sudo, git refuses a checkout owned by another user unless it is in
    safe.directory; the script names that and stops before the service."""
    _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    for path in [box["install"], *box["install"].rglob("*")]:
        os.lchown(path, 65534, 65534)
    res = _run(box)
    assert res.returncode != 0
    assert "dubious ownership" in res.stderr and "safe.directory" in res.stderr
    assert "Nothing was changed" in res.stderr and "Updated" not in res.stdout
    assert _calls(box) == ""


def test_aide_rules_are_written_once_and_replaced_when_they_change(
    box: dict[str, Path],
) -> None:
    conf_d = box["install"].parent / "aide.conf.d"
    conf_d.mkdir()
    (box["bin"] / "aide").write_text("#!/bin/sh\nexit 0\n")
    (box["bin"] / "aide").chmod(0o755)
    rules = conf_d / "90_aide_remnant"
    res = _run(box, AIDE_CONF_D=str(conf_d))
    assert res.returncode == 0, res.stderr
    assert f"AIDE rules written: {rules}" in res.stdout
    assert "!/var/lib/remnant/lake(/|$)" in rules.read_text()
    assert oct(rules.stat().st_mode & 0o777) == "0o644"
    again = _run(box, AIDE_CONF_D=str(conf_d))
    assert "AIDE rules" not in again.stdout  # unchanged: nothing to say
    rules.write_text("!/var/lib/remnant\n")  # the old hand-made rule, which hid tls/ too
    env = box["install"].parent / "remnant.env"
    env.write_text("APP__PATHS__DATA_DIR=/srv/remnant\n")
    third = _run(box, AIDE_CONF_D=str(conf_d), ENV_FILE=str(env))
    assert f"AIDE rules replaced: {rules} (data folder /srv/remnant)" in third.stdout
    assert "!/srv/remnant/lake(/|$)" in rules.read_text()
    assert sorted(p.name for p in conf_d.iterdir()) == ["90_aide_remnant"]


def test_no_aide_rules_without_aide(box: dict[str, Path]) -> None:
    res = _run(box)
    assert res.returncode == 0 and "AIDE rules" not in res.stdout
    assert not (box["install"].parent / "no-aide").exists()


def test_a_checkout_at_origin_main_but_never_installed_is_built(box: dict[str, Path]) -> None:
    """Owner, 2026-11-01: fetched and merged by hand, then the script said "already up to
    date" and the service kept running the old build. Up to date means installed."""
    head = _git(box["install"], "rev-parse", "HEAD")
    res = _run(box)  # no record of an installed build
    assert res.returncode == 0, res.stderr
    assert "already up to date" not in res.stdout
    assert "installed build is unknown: building it" in res.stdout
    assert "systemctl stop remnant" in _calls(box) and "pnpm build" in _calls(box)
    assert "systemctl start remnant" in _calls(box)
    assert _installed(box).read_text().strip() == head
    assert f"Updated remnant to {head[:7]}." in res.stdout
    second = _run(box)
    assert "already up to date" in second.stdout  # now it is


def test_a_checkout_moved_ahead_of_the_installed_build_is_built(box: dict[str, Path]) -> None:
    old = _git(box["install"], "rev-parse", "HEAD")
    _record(box, old)
    new = _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    _git(box["install"], "pull", "-q", "--ff-only", "origin", "main")  # by hand
    res = _run(box)
    assert res.returncode == 0, res.stderr
    assert f"installed build is {old[:7]}: building it" in res.stdout
    assert "pnpm build" in _calls(box)
    assert _installed(box).read_text().strip().startswith(new)


def test_a_failed_start_leaves_the_installed_commit_alone(box: dict[str, Path]) -> None:
    old = _git(box["install"], "rev-parse", "HEAD")
    _record(box, old)
    _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    res = _run(box, NOT_UP="1")
    assert res.returncode != 0 and "is not up" in res.stderr
    assert _installed(box).read_text().strip() == old  # the next run builds again


def test_aide_rebaselines_even_when_up_to_date(box: dict[str, Path]) -> None:
    _record(box, _git(box["install"], "rev-parse", "HEAD"))
    res = subprocess.run(
        ["sh", str(SCRIPT), "--aide"],
        capture_output=True, text=True,
        env={
            "PATH": f"{box['bin']}:{os.environ['PATH']}", "INSTALL_DIR": str(box["install"]),
            "CALLS": str(box["calls"]), "HOME": str(box["install"].parent),
            "ENV_FILE": str(box["install"].parent / "no-env-file"),
            "AIDE_CONF_D": str(box["install"].parent / "no-aide"),
            "STATE_FILE": str(_installed(box)),
            "STATE_OWNER": f"{os.getuid()}:{os.getgid()}",
        },
    )  # fmt: skip
    assert res.returncode == 0, res.stderr
    assert "already up to date" in res.stdout
    assert "aideinit -y -f" in _calls(box) and "systemctl" not in _calls(box)


@pytest.mark.skipif(os.geteuid() != 0, reason="checks root ownership")
def test_the_installed_commit_is_root_owned_and_read_only_to_others(
    box: dict[str, Path],
) -> None:
    res = _run(box)
    assert res.returncode == 0, res.stderr
    st = _installed(box).stat()
    assert (st.st_uid, st.st_gid, oct(st.st_mode & 0o777)) == (0, 0, "0o644")
    assert not list(_installed(box).parent.glob("installed_commit.*"))  # no temp left


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to give the file away")
def test_an_installed_commit_the_service_could_write_is_ignored(box: dict[str, Path]) -> None:
    """A compromised service must not be able to fake "already up to date"."""
    head = _git(box["install"], "rev-parse", "HEAD")
    state = _installed(box)
    for owner, mode in ((65534, 0o644), (0, 0o666)):
        state.write_text(head + "\n")
        os.chown(state, owner, owner)
        os.chmod(state, mode)
        res = _run(box)
        assert res.returncode == 0, res.stderr
        assert "Ignoring" in res.stderr and "already up to date" not in res.stdout
        assert "pnpm build" in _calls(box)
        box["calls"].unlink()
    state.unlink()
    state.symlink_to(box["install"].parent / "elsewhere")
    (box["install"].parent / "elsewhere").write_text(head + "\n")
    res = _run(box)
    assert "Ignoring" in res.stderr and "already up to date" not in res.stdout


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to give the record away")
def test_state_owner_comes_only_from_the_root_process(box: dict[str, Path]) -> None:
    """STATE_OWNER is read from the environment of the root process running the script
    and nowhere else: not the service's env file, its app config, or the data folder,
    all of which the service or its settings can carry. A record owned by the service
    user stays untrusted whatever those say (owner, 2026-11-01)."""
    nobody = "65534:65534"
    data = box["install"].parent / "data"
    data.mkdir()
    pwned = box["install"].parent / "pwned"
    env = box["install"].parent / "remnant.env"
    env.write_text(
        f"APP__PATHS__DATA_DIR={data}\nSTATE_OWNER={nobody}\nAPP__SERVER__STATE_OWNER={nobody}\n"
        f"STATE_OWNER={nobody}; touch {pwned}\n"
    )
    (box["install"] / "config").mkdir()
    (box["install"] / "config" / "app.yaml").write_text(f"server:\n  state_owner: '{nobody}'\n")
    (data / "STATE_OWNER").write_text(nobody)
    record = data / "installed_commit"  # where the script looks: the data folder
    record.write_text(_git(box["install"], "rev-parse", "HEAD") + "\n")
    os.chown(record, 65534, 65534)
    record.chmod(0o644)
    res = _run(box, ENV_FILE=str(env), STATE_FILE="", STATE_OWNER="")  # none from root
    assert res.returncode == 0, res.stderr
    assert "Ignoring" in res.stderr and "already up to date" not in res.stdout
    assert "pnpm build" in _calls(box)  # built instead of trusting the forged record
    assert not pwned.exists()  # the env file is read for one setting, never run
    st = record.stat()
    assert (st.st_uid, st.st_gid, oct(st.st_mode & 0o777)) == (0, 0, "0o644")
