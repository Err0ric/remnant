"""scripts/update-systemd.sh fetches origin's main itself, fails loudly when the fetch
fails, says "already up to date" when nothing changed, and only reports "Updated to X"
when HEAD is origin/main (owner, 2026-11-01: an update reported success at the old commit).

Runs the real script against a local "origin" with systemctl, journalctl, pnpm, uv, and
id stubbed on PATH; the stubs record what they were asked to do."""

import os
import shutil
import subprocess
import time
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


REPORT = """Start timestamp: 2026-11-01 12:00:00 -0800 (AIDE 0.18.6)
AIDE found differences between database and filesystem!!

Summary:
  Total number of entries:\t4120
  Added entries:\t\t{added}
  Removed entries:\t\t0
  Changed entries:\t\t{changed}

---------------------------------------------------
Changed entries:
---------------------------------------------------

{lines}
"""


def _aide(box: dict[str, Path], rc: int, paths: list[str] = ()) -> dict[str, str]:  # type: ignore[assignment]  # tuple default for a list
    """A stub `aide --check` with this exit code and these changed paths."""
    report = box["install"].parent / "aide-report.txt"
    lines = "\n".join(f"f   ...    .C... : {p}" for p in paths)
    report.write_text(REPORT.format(added=0, changed=len(paths), lines=lines))
    stub = box["bin"] / "aide"
    stub.write_text('#!/bin/sh\necho "aide $*" >> "$CALLS"\ncat "$AIDE_REPORT"\nexit "$AIDE_RC"\n')
    stub.chmod(0o755)
    return {"AIDE_REPORT": str(report), "AIDE_RC": str(rc)}


def _run_aide(
    box: dict[str, Path], flag: str, *more: str, **extra: str
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{box['bin']}:{os.environ['PATH']}", "INSTALL_DIR": str(box["install"]),
        "CALLS": str(box["calls"]), "HOME": str(box["install"].parent),
        "ENV_FILE": str(box["install"].parent / "no-env-file"),
        "AIDE_CONF_D": str(box["install"].parent / "no-aide"),
        "STATE_FILE": str(_installed(box)),
        "STATE_OWNER": f"{os.getuid()}:{os.getgid()}", **extra,
    }  # fmt: skip
    return subprocess.run(["sh", str(SCRIPT), flag, *more], capture_output=True, text=True, env=env)


def _new_commit(box: dict[str, Path]) -> str:
    _record(box, _git(box["install"], "rev-parse", "HEAD"))
    new = _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    return new


def test_a_clean_check_then_an_update_re_baselines(box: dict[str, Path]) -> None:
    new = _new_commit(box)
    res = _run_aide(box, "--aide", **_aide(box, 0))
    assert res.returncode == 0, res.stderr
    calls = _calls(box).splitlines()
    assert calls[0].startswith("aide --config") and "--check" in calls[0]  # before anything
    assert calls.index("systemctl start remnant") < calls.index("aideinit -y -f")
    assert _git(box["install"], "rev-parse", "--short", "HEAD") == new


def test_changes_outside_the_install_stop_the_update(box: dict[str, Path]) -> None:
    head = _git(box["install"], "rev-parse", "HEAD")
    _new_commit(box)
    paths = [f"{box['install']}/backend/app/main.py", "/etc/passwd", "/usr/local/bin/tool"]
    res = _run_aide(box, "--aide", **_aide(box, 4, paths))
    assert res.returncode == 1
    assert "AIDE: 0 added, 0 removed, 3 changed" in res.stdout
    assert "/etc/passwd" in res.stdout and "/usr/local/bin/tool" in res.stdout
    assert f"{box['install']}/backend/app/main.py" not in res.stdout.split("Changed outside")[1]
    assert "not made by this update" in res.stderr and "--aide-accept" in res.stderr
    assert "systemctl" not in _calls(box) and "aideinit" not in _calls(box)
    assert _git(box["install"], "rev-parse", "HEAD") == head


def test_important_paths_come_first_and_busy_folders_are_counted(box: dict[str, Path]) -> None:
    """Owner, 2026-11-01: /run noise came first and the list stopped at 25, so an
    important path could be hidden. /etc, /usr, /opt, and /var/lib first, then counts."""
    _new_commit(box)
    noise = [f"/run/user/1000/f{i}" for i in range(640)] + ["/tmp/a", "/var/log/syslog"]
    paths = [*noise, "/etc/sudoers.d/extra", "/var/lib/remnant/.key"]
    res = _run_aide(box, "--aide", **_aide(box, 4, paths))
    assert res.returncode == 1
    out = res.stdout.split("Changed outside")[1]
    assert "644 paths" in out
    listed = out.splitlines()[1:3]
    assert listed == ["  /etc/sudoers.d/extra", "  /var/lib/remnant/.key"]  # first
    assert "... and 619 more. By folder:" in out
    by = out[out.index("By folder:") :]
    assert "/run: 640 entries" in by and "/tmp: 1 entry" in by and "/var/log: 1 entry" in by
    assert by.index("/run:") < by.index("/tmp:")  # busiest first


def test_files_already_readable_are_not_touched(box: dict[str, Path]) -> None:
    """Owner, 2026-11-01: chmod on every file changed every ctime, so AIDE flagged them
    all. Only files missing a+rX are changed."""
    _new_commit(box)
    keep = box["install"] / "backend" / "kept.txt"
    keep.parent.mkdir(exist_ok=True)
    keep.write_text("x")
    keep.chmod(0o644)
    shut = box["install"] / "backend" / "shut.txt"
    shut.parent.mkdir(exist_ok=True)
    shut.write_text("x")
    shut.chmod(0o600)
    time.sleep(1.1)
    before = keep.stat().st_ctime_ns
    res = _run(box)
    assert res.returncode == 0, res.stderr
    assert keep.stat().st_ctime_ns == before
    assert shut.stat().st_mode & 0o777 == 0o644


def test_changes_only_in_the_install_and_its_record_proceed(box: dict[str, Path]) -> None:
    _new_commit(box)
    rules = box["install"].parent / "no-aide" / "90_aide_remnant"  # AIDE_CONF_D in _run_aide
    paths = [f"{box['install']}/.git/FETCH_HEAD", str(rules), str(_installed(box))]
    res = _run_aide(box, "--aide", **_aide(box, 4, paths))
    assert res.returncode == 0, res.stderr
    assert "aideinit -y -f" in _calls(box)


def test_hash_lines_in_the_details_are_not_read_as_paths(box: dict[str, Path]) -> None:
    """Owner, 2026-11-03: a hash (or its continuation line) that starts with "/" in AIDE's
    detailed section was listed as a changed path outside the install and stopped the
    update. Only the entry lists name paths."""
    inst = str(box["install"])
    env = _aide(box, 4, [f"{inst}/backend/app/main.py"])
    report = Path(env["AIDE_REPORT"])
    report.write_text(
        report.read_text()
        + "\n---------------------------------------------------\n"
        + "Detailed information about changes:\n"
        + "---------------------------------------------------\n\n"
        + f"File: {inst}/backend/app/main.py\n"
        + "  SHA256    : /Xk3pQ9vZ2mN8bLr1Ty+aW4cE6dF0gH5j | /Yz9aB2cD4eF6gH8iJ0kL2mN4oP6qR8s\n"
        + "  SHA512    : 7aQ2wE4rT6yU8iO0pA2sD4fG6hJ8kL0z | qW2eR4tY6uI8oP0aS2dF4gH6jK8lZ0x\n"
        + "              /c9V1bN3mQ5wE7rT9yU1iO3pA5sD7fG9h | +h1J3kL5zX7cV9bN1mQ3wE5rT7yU9iO\n"
    )
    _new_commit(box)
    res = _run_aide(box, "--aide", **env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Changed outside" not in res.stdout
    assert "/Xk3pQ9" not in res.stdout + res.stderr


def test_the_check_runs_with_this_install_s_current_rules(box: dict[str, Path]) -> None:
    """Owner, 2026-11-04: rules written by an older script (no spool rule) stayed in place,
    because the rules were written only after the pre-check and a pre-check that flagged
    the spool stopped the run first. The rules are written before AIDE checks."""
    conf_d = box["install"].parent / "no-aide"  # AIDE_CONF_D in _run_aide
    conf_d.mkdir()
    rules = conf_d / "90_aide_remnant"
    rules.write_text("# older rules\n!/var/lib/remnant/lake(/|$)\n")
    seen = box["install"].parent / "rules-at-check"
    env = _aide(box, 0)
    stub = box["bin"] / "aide"
    stub.write_text(
        f'#!/bin/sh\ncp "{rules}" "{seen}"\necho "aide $*" >> "$CALLS"\n'
        'cat "$AIDE_REPORT"\nexit "$AIDE_RC"\n'
    )
    _new_commit(box)
    res = _run_aide(box, "--aide", **env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "spool(/|$)" in seen.read_text()
    assert seen.read_text() == rules.read_text()
    out = res.stdout
    assert out.index("AIDE rules replaced") < out.index("Checking files against the AIDE baseline")


def test_a_no_op_run_checks_but_does_not_re_baseline(box: dict[str, Path]) -> None:
    _record(box, _git(box["install"], "rev-parse", "HEAD"))
    res = _run_aide(box, "--aide", **_aide(box, 0))
    assert res.returncode == 0, res.stderr
    assert "already up to date" in res.stdout
    assert "Not re-baselining AIDE: nothing was updated." in res.stdout
    assert "aide --config" in _calls(box) and "aideinit" not in _calls(box)
    assert "systemctl" not in _calls(box)


def test_aide_accept_proceeds_and_re_baselines(box: dict[str, Path]) -> None:
    new = _new_commit(box)
    res = _run_aide(box, "--aide-accept", **_aide(box, 4, ["/etc/passwd"]))
    assert res.returncode == 0, res.stderr
    assert "Accepted with --aide-accept" in res.stdout
    assert "aideinit -y -f" in _calls(box)
    assert _git(box["install"], "rev-parse", "--short", "HEAD") == new


def test_aide_that_cannot_check_stops_the_update(box: dict[str, Path]) -> None:
    _new_commit(box)
    res = _run_aide(box, "--aide", **_aide(box, 18))
    assert res.returncode == 1 and "AIDE could not check (exit 18)" in res.stderr
    assert "systemctl" not in _calls(box) and "aideinit" not in _calls(box)


def test_a_new_file_in_the_aide_rules_folder_stops_the_run(box: dict[str, Path]) -> None:
    """Only the rules file the script writes is exempt: another file in aide.conf.d could
    exclude paths and hide later tampering, so it is reported and stops the update."""
    head = _git(box["install"], "rev-parse", "HEAD")
    _new_commit(box)
    conf_d = box["install"].parent / "no-aide"
    for path in (conf_d / "95_quiet", Path("/etc/aide/aide.conf")):
        box["calls"].unlink(missing_ok=True)
        res = _run_aide(box, "--aide", **_aide(box, 5, [str(path)]))
        assert res.returncode == 1, res.stdout
        assert str(path) in res.stdout and "not made by this update" in res.stderr
        assert "systemctl" not in _calls(box) and "aideinit" not in _calls(box)
    assert _git(box["install"], "rev-parse", "HEAD") == head


# --- Rollback (owner, 2026-11-08: one command back to the previous version) -------------


def _previous(box: dict[str, Path]) -> Path:
    return box["install"].parent / "previous_commit"


def _from(box: dict[str, Path]) -> Path:
    return box["install"].parent / "rolled_back_from"


def _updated_once(box: dict[str, Path]) -> tuple[str, str]:
    """An install updated once by the script: (old, new) full commits."""
    old = _git(box["install"], "rev-parse", "HEAD")
    _record(box, old)
    _commit(box["work"], "two")
    _git(box["work"], "push", "-q", "origin", "main")
    res = _run(box)
    assert res.returncode == 0, res.stderr
    return old, _git(box["install"], "rev-parse", "HEAD")


def _rollback(box: dict[str, Path], *flags: str, **extra: str) -> subprocess.CompletedProcess[str]:
    box["calls"].unlink(missing_ok=True)
    return _run_aide(box, "--rollback", *flags, **extra)


def test_an_update_records_the_commit_it_replaced(box: dict[str, Path]) -> None:
    old, new = _updated_once(box)
    assert _previous(box).read_text().strip() == old
    assert oct(_previous(box).stat().st_mode & 0o777) == "0o644"
    assert _installed(box).read_text().strip() == new
    assert not list(box["install"].parent.glob("previous_commit.*"))  # no temp left


def test_rollback_checks_out_the_previous_commit_and_rebuilds(box: dict[str, Path]) -> None:
    old, new = _updated_once(box)
    res = _rollback(box)
    assert res.returncode == 0, res.stderr
    assert _git(box["install"], "rev-parse", "HEAD") == old
    assert _git(box["install"], "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"  # detached
    calls = _calls(box).splitlines()
    assert calls[0] == "systemctl stop remnant"
    build = [calls.index(c) for c in ("pnpm install --frozen-lockfile", "pnpm build",
                                      "uv sync --frozen --no-dev", "systemctl start remnant")]  # fmt: skip
    assert build == sorted(build)  # the same build as an update, then the start
    assert "Startup lines" in res.stdout and "listening on" in res.stdout
    assert f"Rolled back remnant from {new[:7]} to {old[:7]}." in res.stdout
    assert _installed(box).read_text().strip() == old
    assert _from(box).read_text().strip() == new
    assert not _previous(box).exists()


def test_a_second_rollback_is_refused_and_an_update_rolls_forward(box: dict[str, Path]) -> None:
    """One step back only: a second rollback would otherwise swap back to the newer build
    without the update's fetch and checks."""
    old, new = _updated_once(box)
    assert _rollback(box).returncode == 0
    res = _rollback(box)
    assert res.returncode == 1
    assert f"Already rolled back from {new[:7]} to {old[:7]}" in res.stderr
    assert "Nothing was changed" in res.stderr and _calls(box) == ""
    box["calls"].unlink(missing_ok=True)
    fwd = _run(box)  # roll forward: the ordinary update
    assert fwd.returncode == 0, fwd.stderr
    assert _git(box["install"], "rev-parse", "HEAD") == new
    assert _git(box["install"], "rev-parse", "--abbrev-ref", "HEAD") == "main"  # attached
    assert _previous(box).read_text().strip() == old and not _from(box).exists()


def test_rollback_without_a_previous_commit_is_refused(box: dict[str, Path]) -> None:
    head = _git(box["install"], "rev-parse", "HEAD")
    _record(box, head)
    res = _rollback(box)
    assert res.returncode == 1
    assert "No previous version is recorded" in res.stderr and "Nothing was changed" in res.stderr
    assert _calls(box) == "" and _git(box["install"], "rev-parse", "HEAD") == head


def test_rollback_refuses_a_dirty_checkout(box: dict[str, Path]) -> None:
    _old, new = _updated_once(box)
    (box["install"] / "two").write_text("edited by hand")
    res = _rollback(box)
    assert res.returncode == 1 and "uncommitted changes" in res.stderr
    assert _calls(box) == "" and _git(box["install"], "rev-parse", "HEAD") == new
    assert _previous(box).exists()  # still there for when it is clean


def test_rollback_ignores_a_previous_commit_the_service_could_write(box: dict[str, Path]) -> None:
    """Same rule as installed_commit: a record not written by root is never a target."""
    _updated_once(box)
    _previous(box).chmod(0o666)
    res = _rollback(box)
    assert res.returncode == 1 and "Ignoring" in res.stderr
    assert "No previous version is recorded" in res.stderr and _calls(box) == ""


def test_rollback_refuses_a_commit_that_is_not_behind_the_checkout(box: dict[str, Path]) -> None:
    _updated_once(box)
    (box["install"] / "side").write_text("x")
    _git(box["install"], "checkout", "-q", "-b", "side")
    side = _commit(box["install"], "side")
    _git(box["install"], "checkout", "-q", "main")
    _previous(box).write_text(_git(box["install"], "rev-parse", side) + "\n")
    res = _rollback(box)
    assert res.returncode == 1 and "not an ancestor" in res.stderr and _calls(box) == ""


def test_a_failed_start_after_rollback_keeps_the_target_for_a_retry(box: dict[str, Path]) -> None:
    old, new = _updated_once(box)
    res = _rollback(box, NOT_UP="1")
    assert res.returncode != 0 and "is not up" in res.stderr
    assert _installed(box).read_text().strip() == new and _previous(box).exists()
    again = _rollback(box)
    assert again.returncode == 0, again.stderr
    assert _installed(box).read_text().strip() == old


def test_rollback_with_aide_checks_first_and_re_baselines_after(box: dict[str, Path]) -> None:
    """The records rollback writes are this script's own, like installed_commit."""
    old, _new = _updated_once(box)
    paths = [str(_installed(box)), str(_previous(box)), str(_from(box))]
    res = _rollback(box, "--aide", **_aide(box, 4, paths))
    assert res.returncode == 0, res.stdout + res.stderr
    calls = _calls(box).splitlines()
    assert calls[0].startswith("aide --config") and "--check" in calls[0]
    assert calls.index("systemctl start remnant") < calls.index("aideinit -y -f")
    assert _git(box["install"], "rev-parse", "HEAD") == old
    box["calls"].unlink()
    bad = _run_aide(box, "--rollback", **_aide(box, 4, ["/etc/passwd"]))
    assert bad.returncode == 1  # refused anyway: nothing to roll back to now


# --- audit 2026-11 H4: a failed update leaves a known version, and rollback goes one back --


def test_a_failed_build_goes_back_to_the_version_that_was_running(box: dict[str, Path]) -> None:
    """The build of the new commit fails after the checkout moved: the checkout returns to
    the commit that was running and is rebuilt, so the service never starts on new code
    with the old packages, and the records still describe what runs."""
    old, new = _updated_once(box)
    _commit(box["work"], "three")
    _git(box["work"], "push", "-q", "origin", "main")
    box["calls"].unlink(missing_ok=True)
    once = box["install"].parent / "pnpm-failed-once"
    (box["bin"] / "pnpm").write_text(
        f'#!/bin/sh\necho "pnpm $*" >> "$CALLS"\n[ -e "{once}" ] || {{ : > "{once}"; exit 1; }}\n'
    )
    res = _run(box)
    assert res.returncode != 0
    assert _git(box["install"], "rev-parse", "HEAD") == new  # back on what was running
    assert f"back to {new[:7]}" in res.stderr
    calls = _calls(box).splitlines()
    assert calls[-1] == "systemctl start remnant"
    assert calls.count("pnpm build") == 1  # the rebuild of the old version
    assert _installed(box).read_text().strip() == new
    assert _previous(box).read_text().strip() == old  # --rollback still means: one back


def test_after_a_failed_start_rollback_returns_to_the_version_that_was_running(
    box: dict[str, Path],
) -> None:
    """The new version was built but did not come up. `--rollback` must return to the
    commit that was running before this update, not to the one before that (D226)."""
    old, new = _updated_once(box)
    newest = _commit(box["work"], "three")
    _git(box["work"], "push", "-q", "origin", "main")
    res = _run(box, NOT_UP="1")
    assert res.returncode != 0 and "is not up" in res.stderr
    assert f"--rollback returns to {new[:7]}" in res.stderr
    assert _installed(box).read_text().strip() == new  # what last ran, as before
    back = _rollback(box)
    assert back.returncode == 0, back.stderr
    assert _git(box["install"], "rev-parse", "HEAD") == new
    assert _git(box["install"], "rev-parse", "--short", "HEAD") != newest
    assert _git(box["install"], "rev-parse", "HEAD") != old


def test_the_aide_rules_skip_scheduled_backups_and_pin_the_folders(box: dict[str, Path]) -> None:
    """Scheduled backups (#468) write a new archive every night: without a rule each one
    was an AIDE change at the next update. The folders themselves stay watched for their
    owner and mode (owner, 2026-11-12)."""
    res = _run_aide(box, "--print-aide-rules")
    rules = res.stdout.splitlines()
    assert "!/var/lib/remnant/backups/.*" in rules
    assert "=/var/lib/remnant/backups$ p+u+g" in rules
    assert "=/var/lib/remnant$ p+u+g" in rules


def _fail_first_build(box: dict[str, Path]) -> None:
    once = box["install"].parent / "pnpm-failed-once"
    once.unlink(missing_ok=True)
    (box["bin"] / "pnpm").write_text(
        f'#!/bin/sh\necho "pnpm $*" >> "$CALLS"\n[ -e "{once}" ] || {{ : > "{once}"; exit 1; }}\n'
    )


def test_rollback_after_a_failed_start_names_what_it_left(box: dict[str, Path]) -> None:
    _old, new = _updated_once(box)
    _commit(box["work"], "three")
    _git(box["work"], "push", "-q", "origin", "main")
    assert _run(box, NOT_UP="1").returncode != 0
    newest = _git(box["install"], "rev-parse", "HEAD")
    back = _rollback(box)
    assert back.returncode == 0, back.stderr
    assert f"Rolled back remnant from {newest[:7]} to {new[:7]}." in back.stdout
    assert _from(box).read_text().strip() == newest
    again = _rollback(box)
    assert again.returncode == 1
    assert f"Already rolled back from {newest[:7]} to {new[:7]}" in again.stderr


def test_a_failed_build_goes_back_to_what_last_ran_not_to_a_build_that_never_started(
    box: dict[str, Path],
) -> None:
    _old, new = _updated_once(box)
    _commit(box["work"], "three")
    _git(box["work"], "push", "-q", "origin", "main")
    assert _run(box, NOT_UP="1").returncode != 0  # three is checked out, never came up
    _commit(box["work"], "four")
    _git(box["work"], "push", "-q", "origin", "main")
    _fail_first_build(box)
    res = _run(box)
    assert res.returncode != 0 and f"Going back to {new[:7]}" in res.stderr
    assert _git(box["install"], "rev-parse", "HEAD") == new
    assert _installed(box).read_text().strip() == new


def test_a_rollback_whose_build_fails_goes_back_to_what_last_ran(box: dict[str, Path]) -> None:
    old, new = _updated_once(box)
    box["calls"].unlink(missing_ok=True)
    _fail_first_build(box)
    res = _run_aide(box, "--rollback")
    assert res.returncode != 0 and f"Going back to {new[:7]}" in res.stderr
    assert _git(box["install"], "rev-parse", "HEAD") == new  # code and packages agree again
    assert _calls(box).splitlines()[-1] == "systemctl start remnant"
    assert _installed(box).read_text().strip() == new
    assert _previous(box).read_text().strip() == old  # the rollback can be tried again
