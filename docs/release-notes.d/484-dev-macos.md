### Development scripts and tests run on macOS too (2026-11-10)

- The update script (`scripts/update-systemd.sh`) used two Linux-only commands (`find -perm /0111` and `stat -c`); it now uses forms that work on Linux and macOS, with the same result on Linux.
- The speed check reads the server's CPU time through `ps` where `/proc` is missing, so its CPU confirmation works on macOS.
- Tests that need Linux (file names that are not UTF-8, per-thread priority) skip on macOS with the reason; Linux and CI still run them. The out-of-memory test for AI usage also skips on macOS: DuckDB crashes there about 1 run in 3 when that query runs out of memory. The AI usage memory test fixes two threads per query, as a 4 vCPU install gets.
- The merge queue runs the smoke test through the backend's environment (`uv run`), where Playwright is installed, instead of whichever `python3` is first on the path.
- The merge queue marks a draft PR ready with `gh pr ready` (the path it used only worked through the old cloud session) and stamps its push time with GNU or BSD `date`.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. The update script behaves the same on Linux; to go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
