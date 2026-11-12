### Agents and the AI inventory hide names without View people in AI usage (2026-11-11)

- On AI usage and Agents, a viewer without the **View people in AI usage** permission sees each Claude Code agent by its machines ("Claude Code: ws-0042") with no owners, and the AI inventory and its CSV or JSON export list agents the same way. Counts, machines, and exclusions stay the same (ADR-0029 G2, D242).
- A person's Alerts tab works again for everyone: without the permission, AI Watch items are left out of the person filter on `/api/alerts`; other alerts about the person are listed as before (D242, amended 2026-11-11).
- Each agents and inventory view is audited `ai.view_people` when it showed names and `ai.view` when it did not, with the surface, the time range, and the sources (G3).
- What you will notice: without View people in AI usage, agents and the AI inventory show machines instead of owners' names, and a person's Alerts tab works again, without AI watch items. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing stored changes. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
