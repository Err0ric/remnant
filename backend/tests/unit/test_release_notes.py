"""docs/release-notes.md stays readable after merges (owner rule: every change gets a note
ending with "What changes for existing installs:"). Merges of this file dropped that line
from six notes and the blank line before nine headings (found 2026-11-04)."""

import re
from pathlib import Path

NOTES = Path(__file__).resolve().parents[3] / "docs" / "release-notes.md"


def _unreleased() -> list[str]:
    text = NOTES.read_text()
    section = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    return re.split(r"\n### ", section)[1:]


def test_every_unreleased_note_says_what_changes_for_existing_installs() -> None:
    missing = [
        n.splitlines()[0] for n in _unreleased() if "What changes for existing installs:" not in n
    ]
    assert missing == []


def test_every_heading_has_a_blank_line_before_it() -> None:
    text = NOTES.read_text()
    glued = [m.group(0).splitlines()[-1] for m in re.finditer(r"[^\n]\n#{2,3} [^\n]*", text)]
    assert glued == []
