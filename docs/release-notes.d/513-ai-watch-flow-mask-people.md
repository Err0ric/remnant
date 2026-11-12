### AI watch, the AI flow, and a person's timeline hide names without View people in AI usage (2026-11-11)

- On the Dashboard, a viewer without the **View people in AI usage** permission sees the AI Watch cards with machines instead of names: "Most from ws-0042" on the sensitive data card, app consents without who granted them, and new Claude Code agents by their machines. Counts stay the same, and a named view is never served to them from the page cache (ADR-0029 G2, D242).
- In Investigate, the AI flow shows each person as the machine they used most (or "Hidden"), in the People group, with Open in Logs by machine and no "Investigate this"; asking the AI flow for one person answers "Needs View people in AI usage". Devices and addresses with no person are listed as before.
- A person's timeline leaves out Claude sessions, first use of AI services, AI telemetry events, and AI Watch alerts for a viewer without the permission; the rest of the timeline is unchanged.
- Each AI Watch, AI flow, and timeline view is audited `ai.view_people` when it showed names and `ai.view` when it did not, with the surface and the sources (G3).
- What you will notice: without View people in AI usage, AI watch cards on the Dashboard, the AI flow in Investigate, and AI rows on a person's timeline show machines or leave names out. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing stored changes. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
