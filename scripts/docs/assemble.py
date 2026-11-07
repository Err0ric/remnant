#!/usr/bin/env python3
"""Release notes and decisions as one file per change (ADR-0044).

Each PR adds `docs/release-notes.d/<pr>-<slug>.md` (a release note) and, for a decision,
`docs/decisions.d/D<nnn>-<slug>.md` (one SPEC section 9 table row). This script writes
them into the two shared pages, so no two PRs edit the same lines:

- the Unreleased section of `docs/release-notes.md`, between the
  `<!-- unreleased:start -->` and `<!-- unreleased:end -->` markers, newest PR first
  (a `new-<slug>.md` note, not yet numbered, comes first);
- SPEC section 9: the hand-kept rows D1 to D{FROZEN} stay as they are, and every row
  after them is written from the decision files in number order. (An HTML comment inside
  a Markdown table ends the table, so the table's end is the assembled block, not a
  marker pair.)

  python3 scripts/docs/assemble.py              # write both pages
  python3 scripts/docs/assemble.py --check      # change nothing; exit 1 with the reasons
  python3 scripts/docs/assemble.py --prep --base origin/main --pr 421
      # the merge queue, in the PR branch after its rebase: number `new-` notes, renumber
      # a decision whose number main already has (citations in the PR's own changed
      # files follow), assemble, then check
  python3 scripts/docs/assemble.py --release v0.4.0 [--date 2026-11-20]
      # freeze the Unreleased notes into a dated section and delete their files

Standard library only; `--prep` runs git.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

FROZEN = 208  # D1 to D208 are hand-kept rows in SPEC (ADR-0044 row 7)
NOTES_DIR = "docs/release-notes.d"
DECISIONS_DIR = "docs/decisions.d"
NOTES = "docs/release-notes.md"
SPEC = "docs/SPEC.md"
START, END = "<!-- unreleased:start -->", "<!-- unreleased:end -->"
WHAT = "What changes for existing installs:"
NOTE_NAME = re.compile(r"^(?:(\d+)|new)-[a-z0-9][a-z0-9-]{0,80}\.md$")
DECISION_NAME = re.compile(r"^D(\d+)-[a-z0-9][a-z0-9-]{0,80}\.md$")
ROW = re.compile(r"^\| D(\d+) \|.*\|$")


def num(row: str) -> int:
    """The decision number of a table row ROW matched."""
    m = ROW.match(row)
    return int(m.group(1)) if m else -1


@dataclass
class Docs:
    root: Path
    problems: list[str] = field(default_factory=list)

    # --- release notes ------------------------------------------------------------------

    def notes(self) -> list[tuple[Path, str]]:
        out: list[tuple[int, str, Path, str]] = []
        for p in sorted((self.root / NOTES_DIR).glob("*.md")):
            m = NOTE_NAME.match(p.name)
            if not m:
                self.problems.append(f"{p.name}: name it <pr>-<slug>.md or new-<slug>.md")
                continue
            text = p.read_text().strip("\n")
            lines = text.splitlines()
            if not lines or not lines[0].startswith("### "):
                self.problems.append(f"{p.name}: start with a '### Title (date)' heading")
            if WHAT not in text:
                self.problems.append(f"{p.name}: no '{WHAT}' line")
            if re.search(r"^#{1,2} ", text, re.M):
                self.problems.append(f"{p.name}: only '###' headings belong in a note")
            pr = int(m.group(1)) if m.group(1) else 10**9  # unnumbered notes first
            out.append((pr, p.name, p, text))
        out.sort(key=lambda t: (-t[0], t[1]))
        return [(p, text) for _, _, p, text in out]

    def notes_page(self) -> str | None:
        path = self.root / NOTES
        page = path.read_text()
        if page.count(START) != 1 or page.count(END) != 1 or page.index(START) > page.index(END):
            self.problems.append(f"{NOTES}: needs one {START} and one {END}, in that order")
            return None
        body = "\n\n".join(text for _, text in self.notes())
        block = f"{START}\n\n{body}\n\n{END}" if body else f"{START}\n\n{END}"
        head, rest = page.split(START, 1)
        _, tail = rest.split(END, 1)
        return head + block + tail

    # --- decisions ----------------------------------------------------------------------

    def decisions(self) -> list[tuple[int, str, Path]]:
        out = []
        for p in sorted((self.root / DECISIONS_DIR).glob("*.md")):
            m = DECISION_NAME.match(p.name)
            if not m:
                self.problems.append(f"{p.name}: name it D<nnn>-<slug>.md")
                continue
            n = int(m.group(1))
            lines = [x for x in p.read_text().splitlines() if x.strip()]
            if len(lines) != 1 or not ROW.match(lines[0]):
                self.problems.append(f"{p.name}: one line, a table row '| D{n} | ... |'")
                continue
            row_n = num(lines[0])
            if row_n != n:
                self.problems.append(f"{p.name}: the row says D{row_n}, the file name D{n}")
            if n <= FROZEN:
                self.problems.append(f"{p.name}: D1 to D{FROZEN} are hand-kept in SPEC")
            out.append((n, lines[0], p))
        out.sort(key=lambda t: t[0])
        return out

    def spec_page(self) -> str | None:
        page = (self.root / SPEC).read_text()
        lines = page.split("\n")
        try:
            sec = next(i for i, x in enumerate(lines) if x.startswith("## 9."))
        except StopIteration:
            self.problems.append(f"{SPEC}: no '## 9.' section")
            return None
        rows = [i for i in range(sec, len(lines)) if ROW.match(lines[i])]
        if not rows or rows != list(range(rows[0], rows[-1] + 1)):
            self.problems.append(f"{SPEC}: the section 9 rows must be one unbroken table")
            return None
        hand = [lines[i] for i in rows if num(lines[i]) <= FROZEN]
        nums = [num(x) for x in hand]
        files = self.decisions()
        all_nums = nums + [n for n, _, _ in files]
        dups = sorted({n for n in all_nums if all_nums.count(n) > 1})
        gaps = sorted(set(range(1, max(all_nums, default=0) + 1)) - set(all_nums))
        if dups:
            self.problems.append("duplicate decision numbers: " + ", ".join(f"D{n}" for n in dups))
        if gaps:
            self.problems.append("missing decision numbers: " + ", ".join(f"D{n}" for n in gaps))
        lines[rows[0] : rows[-1] + 1] = hand + [row for _, row, _ in files]
        return "\n".join(lines)

    # --- write and check ----------------------------------------------------------------

    def pages(self) -> dict[str, str]:
        out = {}
        for name, page in ((NOTES, self.notes_page()), (SPEC, self.spec_page())):
            if page is not None:
                out[name] = page
        return out

    def write(self) -> bool:
        pages = self.pages()
        if self.problems:
            return False
        for name, page in pages.items():
            (self.root / name).write_text(page)
        return True

    def check(self) -> bool:
        for name, page in self.pages().items():
            if (self.root / name).read_text() != page:
                self.problems.append(
                    f"{name} is not what the fragments assemble to;"
                    " run python3 scripts/docs/assemble.py"
                )
        return not self.problems


# --- the merge queue ------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    # git from PATH with fixed subcommands; the arguments are paths and refs from the repo.
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def prep(root: Path, base: str, pr: int) -> list[str]:
    """In the PR branch after its rebase onto `base`: give `new-` notes the PR number,
    give the decisions this PR added the next free numbers after `base`'s highest (a clash
    or a gap is renumbered)
    (citations of the old number in the files this PR changed follow), then assemble.
    Returns what it changed, for the queue's log."""
    done: list[str] = []
    for p in sorted((root / NOTES_DIR).glob("new-*.md")):
        new = p.with_name(f"{pr}-{p.name.removeprefix('new-')}")
        _git(root, "mv", str(p.relative_to(root)), str(new.relative_to(root)))
        done.append(f"{p.name} -> {new.name}")
    changed = [x for x in _git(root, "diff", "--name-only", f"{base}...HEAD").splitlines() if x]
    added = set(_git(root, "diff", "--name-only", "--diff-filter=A", f"{base}...HEAD").splitlines())
    base_spec = _git(root, "show", f"{base}:{SPEC}")
    taken = {int(n) for n in re.findall(r"^\| D(\d+) \|", base_spec, re.M)}
    base_files = _git(root, "ls-tree", "--name-only", f"{base}", f"{DECISIONS_DIR}/").splitlines()
    taken |= {int(m.group(1)) for f in base_files if (m := DECISION_NAME.match(Path(f).name))}
    mine = sorted(
        (int(m.group(1)), f)
        for f in added
        if f.startswith(DECISIONS_DIR + "/") and (m := DECISION_NAME.match(Path(f).name))
    )
    # Numbers follow on from base with no gap and no clash, in this PR's own order, so
    # PRs that picked numbers in parallel land as the next free ones whatever the merge order.
    free = max(taken, default=FROZEN) + 1
    renames: dict[int, int] = {}
    for n, _ in mine:
        if n != free:
            renames[n] = free
        free += 1
    moves: list[tuple[Path, Path]] = []
    for n, f in mine:
        if n not in renames:
            continue
        path = root / f
        new = path.with_name(re.sub(r"^D\d+", f"D{renames[n]}", path.name))
        text = path.read_text().replace(f"| D{n} |", f"| D{renames[n]} |", 1)
        path.write_text(text)
        tmp = path.with_name(f"tmp-{path.name}")
        # Two steps: a new number may be another of this PR's old ones.
        _git(root, "mv", f, str(tmp.relative_to(root)))
        moves.append((tmp, new))
        why = f"main already has D{n}" if n in taken else "the next free number"
        done.append(f"D{n} -> D{renames[n]} ({new.name}; {why})")
    for tmp, new in moves:
        _git(root, "mv", str(tmp.relative_to(root)), str(new.relative_to(root)))
    if renames:
        # Only lines this PR added cite its own decision; the same number on a line from
        # main is the decision that took it first. Assembled table rows are rewritten by
        # assembly, not here.
        cite = re.compile(r"\bD(" + "|".join(str(n) for n in renames) + r")\b")
        for f in changed:
            p = root / f
            if not p.is_file() or f.startswith(DECISIONS_DIR + "/"):
                continue
            diff = _git(root, "diff", "-U0", f"{base}...HEAD", "--", f)
            added = {
                x[1:] for x in diff.splitlines() if x.startswith("+") and not x.startswith("+++")
            }
            try:
                lines = p.read_text().split("\n")
            except UnicodeDecodeError:
                continue
            hit = False
            for i, line in enumerate(lines):
                if line in added and not ROW.match(line) and cite.search(line):
                    lines[i] = cite.sub(lambda m: f"D{renames[int(m.group(1))]}", line)
                    hit = True
            if hit:
                p.write_text("\n".join(lines))
                done.append(f"citations updated in {f}")
    return done


# --- releases -------------------------------------------------------------------------


def release(root: Path, version: str, date: str) -> list[str]:
    """Freeze the Unreleased notes into a `## <version> (<date>)` section under the
    markers, and delete their files."""
    docs = Docs(root)
    notes = docs.notes()
    if docs.problems or not notes:
        return docs.problems or ["no release notes to release"]
    page = (root / NOTES).read_text()
    body = "\n\n".join(text for _, text in notes)
    head, rest = page.split(START, 1)
    _, tail = rest.split(END, 1)
    frozen = f"\n\n## {version} ({date})\n\n{body}\n\n"
    (root / NOTES).write_text(head + f"{START}\n\n{END}" + frozen + tail.lstrip("\n"))
    for p, _ in notes:
        p.unlink()
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--prep", action="store_true")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--release")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args(argv)
    if a.release:
        problems = release(a.root, a.release, a.date)
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    if a.prep:
        if a.pr is None:
            print("--prep needs --pr", file=sys.stderr)
            return 2
        for line in prep(a.root, a.base, a.pr):
            print(line)
    docs = Docs(a.root)
    ok = docs.check() if a.check else docs.write()
    if a.prep and ok:
        ok = Docs(a.root).check()
    for p in docs.problems:
        print(p, file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
