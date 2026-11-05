"""scripts/docs/assemble.py (ADR-0044): one file per release note and per decision,
assembled into release-notes.md and SPEC section 9; the queue's prep step numbers new
notes and renumbers a clashing decision with its citations; releases freeze the notes."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "docs" / "assemble.py"
_spec = importlib.util.spec_from_file_location("assemble", SCRIPT)
assert _spec and _spec.loader
A: Any = importlib.util.module_from_spec(_spec)
sys.modules["assemble"] = A  # dataclasses look their module up while the class is made
_spec.loader.exec_module(A)

HAND = "\n".join(f"| D{n} | Decision {n} | Accepted |" for n in range(1, A.FROZEN + 1))
SPEC = f"# Spec\n\n## 9. Decisions log\n\n| # | Decision | Status |\n|---|---|---|\n{HAND}\n\n---\n\n## 10. Open\n"
NOTES = f"# Release notes\n\n## Unreleased\n\n{A.START}\n\n{A.END}\n\n## v0.3.0 (2026-11-02)\n\n### Old (2026-11-01)\n\n- Old note.\n"


def note(title: str) -> str:
    return f"### {title} (2026-11-05)\n\n- Something changed.\n- {A.WHAT} nothing to do.\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "release-notes.d").mkdir(parents=True)
    (tmp_path / "docs" / "decisions.d").mkdir()
    for d in ("release-notes.d", "decisions.d"):  # git keeps no empty folder
        (tmp_path / "docs" / d / ".gitkeep").write_text("")
    (tmp_path / "docs" / "SPEC.md").write_text(SPEC)
    (tmp_path / "docs" / "release-notes.md").write_text(NOTES)
    return tmp_path


def add(root: Path, rel: str, text: str) -> None:
    (root / rel).write_text(text)


def row(n: int, text: str = "x") -> str:
    return f"| D{n} | {text} | Accepted |\n"


def test_assembles_notes_newest_first_and_decisions_after_the_hand_rows(root: Path) -> None:
    add(root, "docs/release-notes.d/411-older.md", note("Older"))
    add(root, "docs/release-notes.d/420-newer.md", note("Newer"))
    add(root, "docs/release-notes.d/new-not-yet.md", note("Not yet numbered"))
    add(root, "docs/decisions.d/D210-b.md", row(210, "second"))
    add(root, "docs/decisions.d/D209-a.md", row(209, "first"))
    assert A.main(["--root", str(root)]) == 0
    notes = (root / "docs/release-notes.md").read_text()
    order = [notes.index(t) for t in ("Not yet numbered", "Newer", "Older", "## v0.3.0")]
    assert order == sorted(order)
    spec = (root / "docs/SPEC.md").read_text()
    assert spec.index(f"| D{A.FROZEN} |") < spec.index("| D209 | first") < spec.index("| D210 |")
    assert "| D210 | second | Accepted |\n\n---" in spec
    assert A.main(["--root", str(root), "--check"]) == 0
    # Running again changes nothing.
    assert A.main(["--root", str(root)]) == 0
    assert (root / "docs/SPEC.md").read_text() == spec


def test_check_finds_a_stale_page_and_a_hand_edit_inside_the_markers(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add(root, "docs/release-notes.d/412-a.md", note("A"))
    assert A.main(["--root", str(root), "--check"]) == 1
    assert "release-notes.md is not what the fragments assemble to" in capsys.readouterr().err
    A.main(["--root", str(root)])
    p = root / "docs/release-notes.md"
    p.write_text(p.read_text().replace("- Something changed.", "- Edited by hand."))
    assert A.main(["--root", str(root), "--check"]) == 1


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"D209-a.md": row(209), "D209-b.md": row(209)}, "duplicate decision numbers: D209"),
        ({"D210-a.md": row(210)}, "missing decision numbers: D209"),
        ({"D209-a.md": row(208)}, "the row says D208, the file name D209"),
        ({"D150-a.md": row(150)}, f"D1 to D{A.FROZEN} are hand-kept"),
        ({"D209-a.md": "not a row\n"}, "one line, a table row"),
        ({"d209.md": row(209)}, "name it D<nnn>-<slug>.md"),
    ],
)  # fmt: skip
def test_decision_problems(
    root: Path, files: dict[str, str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, text in files.items():
        add(root, f"docs/decisions.d/{name}", text)
    assert A.main(["--root", str(root)]) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("413-a.md", "### A (2026-11-05)\n\n- No line about installs.\n", "no 'What changes"),
        ("413-a.md", "- No heading.\n- What changes for existing installs: none.\n", "start with"),
        ("pr413.md", note("A"), "name it <pr>-<slug>.md"),
        ("413-a.md", "## Big\n\n" + note("A"), "only '###' headings"),
    ],
)  # fmt: skip
def test_note_problems(
    root: Path, name: str, text: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    add(root, f"docs/release-notes.d/{name}", text)
    assert A.main(["--root", str(root)]) == 1
    assert message in capsys.readouterr().err


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip


def test_prep_numbers_notes_and_renumbers_a_clashing_decision(root: Path) -> None:
    """The owner's rule (ADR-0044 change 1): the later PR gets the next free number, its
    own changed files follow, and nothing else changes."""
    add(root, "untouched.md", "Elsewhere D209 means the merged decision.\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "checkout", "-qb", "mine")
    add(root, "docs/decisions.d/D209-mine.md", row(209, "mine"))
    add(root, "docs/release-notes.d/new-mine.md", note("Mine"))
    add(root, "code.py", "# The rule from D209 (and not D2090).\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "mine")
    git(root, "checkout", "-q", "main")
    add(root, "docs/decisions.d/D209-theirs.md", row(209, "theirs"))
    A.main(["--root", str(root)])
    git(root, "add", "-A")
    git(root, "commit", "-qm", "theirs merged")
    git(root, "checkout", "-q", "mine")
    git(root, "rebase", "-q", "main")
    assert A.main(["--root", str(root), "--prep", "--base", "main", "--pr", "421"]) == 0
    assert (root / "docs/decisions.d/D210-mine.md").read_text() == row(210, "mine")
    assert not (root / "docs/decisions.d/D209-mine.md").exists()
    assert (root / "docs/release-notes.d/421-mine.md").exists()
    assert (root / "code.py").read_text() == "# The rule from D210 (and not D2090).\n"
    assert "Elsewhere D209" in (root / "untouched.md").read_text()
    spec = (root / "docs/SPEC.md").read_text()
    assert "| D209 | theirs" in spec and "| D210 | mine" in spec
    assert A.main(["--root", str(root), "--check"]) == 0


def test_release_freezes_the_notes(root: Path) -> None:
    add(root, "docs/release-notes.d/414-a.md", note("A"))
    add(root, "docs/release-notes.d/415-b.md", note("B"))
    A.main(["--root", str(root)])
    assert A.main(["--root", str(root), "--release", "v0.4.0", "--date", "2026-11-20"]) == 0
    notes = (root / "docs/release-notes.md").read_text()
    assert f"{A.START}\n\n{A.END}\n\n## v0.4.0 (2026-11-20)\n\n### B" in notes
    assert notes.index("### A") < notes.index("## v0.3.0")
    assert list((root / "docs/release-notes.d").glob("*.md")) == []
    assert A.main(["--root", str(root), "--check"]) == 0


def test_hand_rows_keep_their_order(root: Path) -> None:
    """D1 to D208 are left as they are (ADR-0044 row 7), even out of number order."""
    spec = root / "docs/SPEC.md"
    lines = spec.read_text().split("\n")
    i, j = (
        lines.index("| D1 | Decision 1 | Accepted |"),
        lines.index("| D2 | Decision 2 | Accepted |"),
    )
    lines[i], lines[j] = lines[j], lines[i]
    spec.write_text("\n".join(lines))
    before = spec.read_text()
    add(root, "docs/decisions.d/D209-a.md", row(209))
    assert A.main(["--root", str(root)]) == 0
    assert spec.read_text() == before.replace(
        f"| D{A.FROZEN} | Decision {A.FROZEN} | Accepted |",
        f"| D{A.FROZEN} | Decision {A.FROZEN} | Accepted |\n| D209 | x | Accepted |",
    )
