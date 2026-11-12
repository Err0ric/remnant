### View people in AI usage permission (2026-11-11)

- Users and access has a new per-user permission, **View people in AI usage**. Administrators always have it. Analysts and Auditors, new and existing, start without it; an administrator turns it on per user, and each change is in the audit log as `admin.change` (ADR-0029 G1, D242).
- Without it, the next updates show the machine or address instead of a person's name on AI pages, or "Hidden" where there is none; counts of people stay. The server removes the names from its answers, not only the page (G2). Views that show names are recorded as `ai.view_people`, others as `ai.view` (G3).
- What you will notice: administrators get a "View people in AI usage" switch per user on the Users page; analysts and auditors will stop seeing names on AI pages as the following updates land, until an administrator turns it on for them.
- What changes for existing installs: nothing to do; the update adds one column to the users table, off for every existing analyst and auditor. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); the column stays and the older release ignores it.
