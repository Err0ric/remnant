# ADR-0044: Release notes and decisions as one file per change

- Status: accepted by the owner 2026-11-05, with changes 1 and 2 below (rows 3, 4, and 8 as amended)
- Changes how `docs/SPEC.md` section 9 and `docs/release-notes.md` are maintained (CLAUDE.md, Git; the D-row guard in the merge queue stays)

## Context

Every PR edits the same two places: a new row in the SPEC section 9 table, and a new note at the top of `docs/release-notes.md` under "Unreleased". PRs merge one at a time, each rebased onto the last, so these two spots conflict on almost every PR. Conflicts there are resolved by keeping both sides, and that has gone wrong three times in two days:

| Incident | What happened | Caught by |
|---|---|---|
| 2026-11-03 | D195 and D197 lost from SPEC; D199 and D200 never written | Hand audit (#408, #409) |
| 2026-11-04 | D206 present twice after a rebase | The queue's new D-row check |
| 2026-11-04 | Six release notes lost their "What changes for existing installs" line; nine headings lost their blank line | Hand reading (#418) |

The guards added since (the queue's lost and duplicate D-row check, `test_release_notes.py`) catch damage after it happens. The cause is that unrelated PRs edit the same lines.

## Decision (proposed)

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | Where a PR's release note goes | Its own file, `docs/release-notes.d/<pr>-<slug>.md`: a `### Title (date)` heading, the bullets, and the "What changes for existing installs:" line. A PR never edits `release-notes.md` | Two PRs never touch the same file, so there is nothing to merge | Keep one file and a smarter merge driver (still one shared hunk) |
| 2 | The PR number in the name | Open the PR first, then commit the note with its number. A note may start as `new-<slug>.md`; the queue renames it to `<pr>-<slug>.md` before merging | The number sorts notes in merge order and links note to PR | Date and slug only (ties within a day sort by name, not by merge) |
| 3 | Assembling the notes | `scripts/docs/assemble.py` (run in the PR branch, row 4) writes the "Unreleased" section of `release-notes.md` from the fragments, newest PR first, between `<!-- unreleased:start -->` and `<!-- unreleased:end -->`. Past releases below stay hand-kept and frozen | One readable file on dev and in the public repository, as today | Readers open the folder (no single page to read) |
| 4 | When assembly runs | **Changed by the owner:** in the PR branch, during the queue's rebase and before CI, so the assembled pages land inside the PR's own squash commit; nothing is ever pushed straight to `main`. CI and `publish.sh` run `--check` and stop if the committed pages are not what the fragments assemble to | `main` and the public copy never show a stale page, no commit bypasses review or CI, and a hand edit inside the markers is caught | A separate `docs:` commit on `main` after each merge (refused: nothing goes to `main` outside a PR) |
| 5 | Cutting a release | `assemble.py --release v0.4.0` moves the Unreleased fragments into a dated, frozen section and deletes them | Fragments are short-lived; the file keeps the history | Keep the fragments forever |
| 6 | Where a new decision goes | Its own file, `docs/decisions.d/D<nnn>-<slug>.md`: one line, the table row as it reads today (`\| D209 \| ... \| Accepted \|`) | Same reason as row 1 | Front matter fields (more structure than one table row needs) |
| 7 | The existing D1 to D208 | They stay in SPEC section 9 as they are. New rows come only from fragments, assembled below them between `<!-- decisions:start -->` and `<!-- decisions:end -->` in number order. An edit to an old row (a status change such as "accepted") stays a hand edit of that row | No 200-file migration; old rows rarely change, and when they do only one PR edits them | Move every row into a fragment (one source, but a large churn PR) |
| 8 | Choosing a number | The next number after the highest on `main` when the PR is written. **Changed by the owner:** when two PRs in flight pick the same one, the queue renumbers the later PR automatically to the next free number, updates citations of the old number in that PR's own changed files, and reruns `--check`; no hand renumbering. Once merged, a number is fixed | A number is needed while writing (code comments cite it), and a clash costs no one's time | Stop the queue and renumber by hand (refused) |
| 9 | Checks (the backstop stays) | `assemble.py --check`, in CI and in the queue: every fragment parses; D-numbers have no gaps or duplicates across the frozen rows and the fragments; every note has its heading and "What changes" line; the assembled blocks match what is committed. The queue's lost and duplicate D-row check and `test_release_notes.py` stay | Same guarantees, checked from the source instead of from the merged result | Rely on the new layout alone |
| 10 | The Project copy | `docs/SPEC.md` is synced to the Project after assembly, so the Project always shows every decision | The Project is where the owner reads SPEC | |
| 11 | What PRs still edit by hand | The rest of SPEC (sections 1 to 8, 10), DESIGN.md, ADRs, and CLAUDE.md, as today. Those edits are usually in different sections, and a real conflict there should stop for a human | Only the two always-touched spots move | |

## Consequences

- Two PRs in the queue no longer conflict over notes or decisions; a rebase of those files is a file add.
- One more script (`scripts/docs/assemble.py`) with its own tests, run by CI, the queue, and publish.
- Writing a change: open the PR, then add `docs/release-notes.d/<pr>-<slug>.md` and, for a decision, `docs/decisions.d/D<nnn>-<slug>.md`. CLAUDE.md's "every change gets a release note and a SPEC D-row" step says where.
- The rendered pages read the same as today. A reader of SPEC sees one table with D1 to the newest.
- A renumbered D-row (row 8) still needs its citations in code and docs updated by hand; the check names the clash, not the citations.

## As built

- Step 1 (2026-11-05): `scripts/docs/assemble.py` with `--check`, `--prep --base <ref> --pr <n>` (the queue's step: number `new-` notes, renumber a clashing decision and its citations in the PR's changed files, assemble, check), and `--release`; tests in `backend/tests/unit/test_assemble_docs.py`.
- Steps 2 to 4 (2026-11-05, #420): the 55 Unreleased notes became fragments (each named for the PR that added it); CI (`check-architecture.sh`) and `publish.sh` run `--check`; the queue moved into the repository as `scripts/dev/queue.sh` with the prep step (tested end to end against local repositories in `scripts/dev/test.sh`: two PRs that both took D209 merge as D209 and D210, the second PR's citation follows, the first's does not); CLAUDE.md; D209 is this ADR's row and the first decision file. Citations are updated only on lines the PR added, so the same number on a line from main keeps meaning the decision that took it first.
- Row 7 differs in one detail: SPEC section 9 has no marker pair. An HTML comment inside a Markdown table ends the table, so the assembled block is the table's rows after D208, written from the decision files; the rows D1 to D208 are left as they are.

## Rollout

1. `scripts/docs/assemble.py` with `--check` and `--release`, plus tests: gaps, duplicates, a missing "What changes" line, a stale assembled block, and release cutting.
2. Markers in SPEC section 9 and `release-notes.md`. The current Unreleased notes become fragments: about 55 files, generated once by the script. CI runs the check.
3. Queue: rename `new-` fragments, assemble after merge, and drop its D-row sorting step. The lost and duplicate check stays. `publish.sh` refuses a stale assembly.
4. CLAUDE.md (Git, section 8) and a SPEC row for this ADR, itself written as the first fragment.

## ATLAS / ATT&CK

None: build tooling only; nothing AI-facing changes.
