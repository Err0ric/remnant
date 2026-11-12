### The merge queue stops when the CI changes job fails (2026-11-12)

- Development tooling only. The CI `changes` job decides whether the backend and frontend jobs run. When it failed, both were skipped, and the merge queue read "architecture passed, the others skipped" as a green run and merged (found by the 2026-11 audit).
- The queue now requires the `changes` job to succeed, and requires the job each changed path needs (backend for `backend/`, `library/`, `templates/`, `scripts/`; frontend for `frontend/`) to succeed, not to be skipped. Docs-only PRs still run no CI.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.
