### The terminal interface no longer errors when closed quickly (2026-11-11)

- In the terminal interface (`app tui`), the source list loads in the background. Closing the window before it arrived could end with an error; a result that arrives after the window is gone is now ignored. This also fixes a test that failed now and then.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
