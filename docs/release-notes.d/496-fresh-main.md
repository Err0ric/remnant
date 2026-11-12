### Development: the session check fast-forwards main (2026-11-10)

- `scripts/dev/session-check.sh` now fast-forwards a local `main` that is only behind `origin/main` (when it is not checked out elsewhere and has no local changes), so tools never compare against a stale `main`. A `main` with commits of its own is still only reported.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. A development script only.
