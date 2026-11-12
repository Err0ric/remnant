### Development: publishing checks its folder, its source, and names outside file contents (2026-11-12)

- Development tooling only (`scripts/publish/publish.sh`, not part of the public tree). Found by the 2026-11 audit: the script emptied whatever folder `PUB_DIR` named without checking it, copied the local `main` instead of what the merge queue had put on `origin/main`, and matched the name list against file contents only.
- It now stops, before removing anything, unless `PUB_DIR` is a separate clone standing exactly on the public `main` (never the development checkout or one of its worktrees); publishes `origin/main` and stops when the local `main` differs from it; refuses a tree that still contains `scripts/dev/`; checks the name list against file names, the commit message, and the tag; fixes the public commit's author and committer whatever the environment says; and checks that the one new commit sits directly on the public `main` before pushing.
- Not decided here: whether `docs/handoff.md` should stay in the public tree (owner).
- What you will notice: nothing visible.
- What changes for existing installs: nothing.
