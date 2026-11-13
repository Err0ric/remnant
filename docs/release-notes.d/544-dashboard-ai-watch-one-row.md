### Audit: AI Watch on the Dashboard is part of the visit's entry unless it shows a name (2026-11-12)

- A Dashboard visit wrote its `dashboard.view` entry and, for AI Watch, a separate `ai.view` entry on every load and every refresh. Now AI Watch that names no one, for the window the page shows, is listed as `ai_watch` in the visit's entry and writes nothing of its own (owner decision; ADR-0029 G3 amended).
- AI Watch that shows a person's name still writes `ai.view_people` every time, so the list of who saw people's AI usage stays complete.
- Requests outside a Dashboard visit (the CLI, scripts), and AI Watch asked for another range than the page's window, are audited one by one as before.
- What you will notice: nothing on screen; fewer "Viewed AI usage" entries in the audit log.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/team-vm.md`, Rolling back); entries already written stay as they are.
