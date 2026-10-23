"""The version on About says exactly which commit is installed."""

from pathlib import Path

from app.core.build import commit_of

SHA = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"


def _repo(tmp_path: Path) -> Path:
    code = tmp_path / "opt" / "remnant" / "backend" / "app"
    code.mkdir(parents=True)
    (tmp_path / "opt" / "remnant" / ".git" / "refs" / "heads").mkdir(parents=True)
    return code


def test_a_branch_checkout_reads_the_loose_ref(tmp_path: Path) -> None:
    code = _repo(tmp_path)
    git = tmp_path / "opt" / "remnant" / ".git"
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text(SHA + "\n")
    assert commit_of(code) == "1a2b3c4"


def test_a_packed_ref_and_a_detached_head(tmp_path: Path) -> None:
    code = _repo(tmp_path)
    git = tmp_path / "opt" / "remnant" / ".git"
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text(f"# pack-refs with: peeled\n{SHA} refs/heads/main\n")
    assert commit_of(code) == "1a2b3c4"
    (git / "HEAD").write_text(SHA.replace("1a", "9f", 1) + "\n")
    assert commit_of(code) == "9f2b3c4"


def test_an_image_stamp_and_nothing_known(tmp_path: Path) -> None:
    code = tmp_path / "srv" / "backend" / "app"
    code.mkdir(parents=True)
    assert commit_of(code) is None
    (tmp_path / "srv" / "BUILD_COMMIT").write_text("")  # built without GIT_COMMIT
    assert commit_of(code) is None
    (tmp_path / "srv" / "BUILD_COMMIT").write_text(SHA)
    assert commit_of(code) == "1a2b3c4"
    (tmp_path / "srv" / "BUILD_COMMIT").write_text("not a commit; rm -rf /")
    assert commit_of(code) is None
