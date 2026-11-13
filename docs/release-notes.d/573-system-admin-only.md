### Backups, Page rollups, and Speed are sent to administrators only (2026-11-13)

- Owner decision of 2026-11-13, following Settings > System (ADR-0052 section 3.3). The server now leaves the state of scheduled backups and the page rollups out of what it sends to Analysts and Auditors: `GET /api/health-checks` answers `backup: null` and `rollups: []` for them. Page speed was already for administrators. Before this, only the web page hid them.
- A failed or overdue backup still raises an alert that everyone sees.
- The panels that count whole days back from now say so: the Agents numbers, sessions and tool rows, and a person's AI activity and devices are labeled "Last 7 days" (or 24 hours, or the days counted), whatever the page's time choice is.
- What you will notice: the Agents numbers, sessions and tool rows, and a person's AI activity and devices now start with "Last 7 days" (or the days they count). Nothing else changes on the page for anyone: Settings > System was already hidden from Analysts and Auditors.
- What changes for existing installs: nothing to do. A script that read `backup` or `rollups` from `/api/health-checks` with an Analyst's or Auditor's token now gets null and an empty list; use an administrator's token.
