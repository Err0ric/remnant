"""The merge queue's lock and heavy.sh (owner order, 2026-11-12): heavy jobs run only
while no running queue holds the lock. Runs the shell scripts in a throwaway git
repository; never the real queue (queue.sh stops at its first check here)."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

DEV = Path(__file__).resolve().parents[3] / "scripts" / "dev"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    return r


def _clean() -> dict[str, str]:
    """The environment without a running queue's own variables: a queue that runs this suite
    exports REMNANT_QUEUE_COPY and REMNANT_QUEUE_LOCK_LIB, and a queue.sh under test that saw
    them would skip its own copy step and use the real queue's lock."""
    return {k: v for k, v in os.environ.items() if not k.startswith("REMNANT_QUEUE_")}


def sh(repo: Path, script: str, **env: str) -> subprocess.CompletedProcess[str]:
    """`script` with lock.sh sourced, in the repository."""
    return subprocess.run(
        ["sh", "-c", f'. "{DEV}/lock.sh"; {script}'],
        cwd=repo, capture_output=True, text=True, env={**_clean(), **env},
    )  # fmt: skip


def heavy(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(DEV / "heavy.sh"), *args], cwd=repo, capture_output=True, text=True
    )


def lock_path(repo: Path) -> Path:
    return Path(sh(repo, "queue_lock_path").stdout.strip())


def dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_the_lock_is_shared_by_every_worktree(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "one"],
                   check=True, env={**_clean(), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})  # fmt: skip
    other = repo.parent / "other"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(other)], check=True)
    assert lock_path(other) == lock_path(repo)
    assert lock_path(repo).name == "remnant-queue.lock"


def test_no_lock_runs_the_command(repo: Path) -> None:
    res = heavy(repo, "sh", "-c", "echo ran")
    assert (res.returncode, res.stdout) == (0, "ran\n")


def test_a_live_lock_refuses_with_75_and_names_the_pr(repo: Path) -> None:
    assert sh(repo, f"queue_lock_take 501 {os.getpid()}").returncode == 0
    res = heavy(repo, "sh", "-c", "echo ran")
    assert res.returncode == 75 and res.stdout == ""
    assert res.stderr.startswith("The merge queue is running PR 501 (since 20")
    assert f"pid {os.getpid()}). Heavy runs wait until it finishes: sh -c echo ran" in res.stderr


def test_a_stale_lock_is_ignored(repo: Path) -> None:
    assert sh(repo, f"queue_lock_take 501 {dead_pid()}").returncode == 0
    assert heavy(repo, "true").returncode == 0
    # and replaced by the next queue
    assert sh(repo, f"queue_lock_take 502 {os.getpid()}").returncode == 0
    assert "pr=502" in lock_path(repo).read_text()


def test_wait_runs_once_the_lock_is_gone(repo: Path) -> None:
    holder = subprocess.Popen(["sleep", "30"])
    try:
        assert sh(repo, f"queue_lock_take 501 {holder.pid}").returncode == 0
        waiting = subprocess.Popen(
            ["sh", str(DEV / "heavy.sh"), "--wait", "sh", "-c", "echo ran"],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**_clean(), "REMNANT_HEAVY_POLL_S": "0.1"},
        )  # fmt: skip
        time.sleep(0.5)
        assert waiting.poll() is None  # still waiting
        holder.kill()  # the queue ends (its lock is now stale)
        holder.wait()
        out, err = waiting.communicate(timeout=10)
        assert (waiting.returncode, out) == (0, "ran\n") and "Waiting for the merge queue" in err
    finally:
        holder.kill()


def test_take_and_release(repo: Path) -> None:
    me = os.getpid()
    assert sh(repo, f"queue_lock_take 501 {me}").returncode == 0
    text = lock_path(repo).read_text()
    assert f"pid={me}\npr=501\nstarted=20" in text
    refused = sh(repo, "queue_lock_take 502 1")  # another queue while this one runs
    assert refused.returncode == 1 and "PR 501" in refused.stdout
    assert sh(repo, "queue_lock_release 1").returncode == 0  # not its lock: kept
    assert lock_path(repo).exists()
    assert sh(repo, f"queue_lock_release {me}").returncode == 0
    assert not lock_path(repo).exists()


def test_a_failing_shell_releases_the_lock_on_exit(repo: Path) -> None:
    res = subprocess.run(
        ["bash", "-c", f'. "{DEV}/lock.sh"; trap queue_lock_release EXIT; queue_lock_take 501;'
         ' test -f "$(queue_lock_path)" || exit 9; false || exit 1'],
        cwd=repo, capture_output=True, text=True,
    )  # fmt: skip
    assert res.returncode == 1
    assert not lock_path(repo).exists()


def _queue(repo: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """queue.sh with a stand-in session check that records the lock and fails, so the
    queue stops at its first step, before any fetch."""
    check = repo / "scripts" / "dev" / "session-check.sh"
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_text(f'cat "{lock_path(repo)}" > "{tmp_path}/seen"; exit 1\n')
    return subprocess.run(
        ["bash", str(DEV / "queue.sh"), "some-branch", "777"],
        cwd=repo, capture_output=True, text=True, env={**_clean(), "TMPDIR": str(tmp_path)},
    )  # fmt: skip


def test_the_queue_holds_the_lock_and_drops_it_when_it_fails(repo: Path, tmp_path: Path) -> None:
    res = _queue(repo, tmp_path)
    assert res.returncode == 1 and "STOP at 777" in res.stdout
    assert "pr=777" in (tmp_path / "seen").read_text()
    assert not lock_path(repo).exists()


def test_a_second_queue_stops_while_one_runs(repo: Path, tmp_path: Path) -> None:
    assert sh(repo, f"queue_lock_take 501 {os.getpid()}").returncode == 0
    res = _queue(repo, tmp_path)
    assert res.returncode == 1 and "another merge queue holds the lock: PR 501" in res.stdout
    assert not (tmp_path / "seen").exists()
    assert "pr=501" in lock_path(repo).read_text()


def uutils_mkdir(folder: Path) -> str:
    """A PATH whose `mkdir` does what the one on Ubuntu 25.10 and later does (uutils coreutils
    0.2.2, GitHub's runners since 2026-10): two processes racing for one directory are both
    told it worked (300 of 300 tries in a container). A program, as the real one is."""
    folder.mkdir()
    real = shutil.which("mkdir")
    fake = folder / "mkdir"
    fake.write_text(f'#!/bin/sh\n{real} "$@" 2>/dev/null || [ -d "$1" ]\n')
    fake.chmod(0o755)
    return f"{folder}{os.pathsep}{os.environ['PATH']}"


@pytest.mark.parametrize("flavor", ["exclusive-mkdir", "uutils-mkdir"])
def test_two_queues_taking_the_lock_at_once_exactly_one_wins(
    repo: Path, tmp_path: Path, flavor: str
) -> None:
    """The take is atomic: two takers released at the same moment, each for its own live
    queue, and exactly one holds the lock, round after round, from free and from stale. Also
    where `mkdir` lets both in: the exclusive `.owner` file decides. (Until 2026-11-13 the
    guard was `mkdir` alone, and on GitHub's runners both takers got in, saw each other, and
    backed off: safe, but nobody held the lock.)"""
    # Stand-in queues that outlive the test on the slowest runner: once they are gone their
    # locks are stale, and both takers would be right to win.
    queues = [subprocess.Popen(["sleep", "3600"]) for _ in range(2)]
    a, b = (q.pid for q in queues)
    go = tmp_path / "go"
    env = {"PATH": uutils_mkdir(tmp_path / "bin")} if flavor == "uutils-mkdir" else {}
    script = f"""
      take() {{ until [ -f "{go}" ]; do :; done; queue_lock_take "$1" "$2" >&2; }}
      take 601 {a} & pa=$!
      take 602 {b} & pb=$!
      touch "{go}"
      wait $pa; ra=$?
      wait $pb; rb=$?
      echo "$ra $rb"
    """
    try:
        for stale in (False, True) * 5:
            go.unlink(missing_ok=True)
            lock = lock_path(repo)
            lock.unlink(missing_ok=True)
            if stale:
                assert sh(repo, f"queue_lock_take 500 {dead_pid()}").returncode == 0
            res = sh(repo, script, **env)
            held = lock.read_text() if lock.exists() else ""
            seen = (
                f"{res.stdout}{res.stderr}stale={stale} lock={held!r}"
                f" queues alive={[q.poll() is None for q in queues]}"
            )
            assert sorted(res.stdout.split()) == ["0", "1"], seen
            winner = "601" if res.stdout.split()[0] == "0" else "602"
            assert f"pr={winner}\n" in held, seen
            assert not Path(f"{lock}.take").exists(), seen
    finally:
        for q in queues:
            q.kill()


# --- the guard (review of #543) ---------------------------------------------------------


def test_a_taker_that_is_not_alone_in_the_guard_backs_off_without_writing(repo: Path) -> None:
    """mkdir is exclusive, so two takers never share the guard. If they ever do (seen once
    on Linux CI), the one that finds another taker's file leaves the lock as it is."""
    holder = subprocess.Popen(["sleep", "3600"])
    other = subprocess.Popen(["sleep", "3600"])
    try:
        assert sh(repo, f"queue_lock_take 501 {holder.pid}").returncode == 0
        lock = lock_path(repo)
        before = lock.read_text()
        guard = Path(f"{lock}.take")
        guard.mkdir()
        (guard / str(other.pid)).touch()  # another taker, inside right now
        # A mkdir that is not exclusive stands in for whatever let two takers in.
        res = sh(repo, 'mkdir() { command mkdir -p "$@"; }; queue_lock_take 502')
        assert res.returncode == 1 and "at the same moment" in res.stdout
        assert lock.read_text() == before  # the holder's lock is untouched
        assert [p.name for p in guard.iterdir()] == [str(other.pid)]  # and the other's file
        # The loser's exit trap (queue.sh) must not remove the holder's lock either.
        assert sh(repo, "queue_lock_release").returncode == 0
        assert lock.read_text() == before
    finally:
        holder.kill()
        other.kill()


def test_a_guard_removed_under_a_taker_is_not_a_take(repo: Path) -> None:
    res = sh(repo, 'date() { rm -rf "$_g"; command date "$@"; }; queue_lock_take 501')
    assert res.returncode == 1 and "changed while this queue held it" in res.stdout


def test_a_lock_that_names_another_queue_after_the_guard_is_not_a_take(repo: Path) -> None:
    other = subprocess.Popen(["sleep", "3600"])
    try:
        steal = (
            f"rmdir() {{ printf 'pid={other.pid}\\npr=777\\nstarted=x\\n' > \"$_f\";"
            ' command rmdir "$@"; }; queue_lock_take 501'
        )
        res = sh(repo, steal)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "took the lock at the same moment: PR 777" in res.stdout
    finally:
        other.kill()


@pytest.mark.parametrize("left", ["dead", "empty"])
def test_a_guard_left_by_a_killed_taker_is_cleared(repo: Path, left: str) -> None:
    guard = Path(f"{lock_path(repo)}.take")
    guard.mkdir()
    if left == "dead":
        (guard / str(dead_pid())).touch()
    started = time.monotonic()
    res = sh(repo, f"queue_lock_take 501 {os.getpid()}")
    assert res.returncode == 0, res.stdout + res.stderr
    assert 1.5 < time.monotonic() - started < 9  # after about 2 s, not the 10 s give-up
    assert not guard.exists() and "pr=501" in lock_path(repo).read_text()


@pytest.mark.slow  # waits out the 10 s give-up
def test_a_guard_held_by_a_running_taker_is_never_cleared(repo: Path) -> None:
    taker = subprocess.Popen(["sleep", "3600"])
    try:
        guard = Path(f"{lock_path(repo)}.take")
        guard.mkdir()
        (guard / str(taker.pid)).touch()
        res = sh(repo, "queue_lock_take 501")
        assert res.returncode == 1 and "over 10 s" in res.stdout
        assert (guard / str(taker.pid)).exists() and not lock_path(repo).exists()
    finally:
        taker.kill()


def test_release_takes_this_queues_file_out_of_a_guard_it_left(repo: Path) -> None:
    """Interrupted between entering the guard and leaving it: the exit trap cleans up."""
    guard = Path(f"{lock_path(repo)}.take")
    guard.mkdir()
    (guard / "4242").touch()
    assert sh(repo, "queue_lock_release 4242").returncode == 0
    assert not guard.exists()


def test_a_lock_from_another_host_counts_as_live(repo: Path) -> None:
    """A container sharing the checkout cannot see the host's queue process: its lock must
    not read as stale there."""
    lock_path(repo).write_text(
        f"pid={dead_pid()}\npr=501\nstarted=2026-11-12T10:00:00Z\nhost=another.example\n"
    )
    res = heavy(repo, "sh", "-c", "echo ran")
    assert res.returncode == 75 and "PR 501" in res.stderr
    refused = sh(repo, "queue_lock_take 502")
    assert refused.returncode == 1 and "PR 501" in refused.stdout
