### Design: the rail lists pages only (2026-11-12)

- Console redesign, build row 4 (ADR-0052 section 3.2, D246). The left rail is nine entries with nothing under them and nothing to fold: Monitor (Dashboard, Alerts), Investigate (Logs, Ask AI, People & devices), AI (AI usage, Agents), and, pinned at the bottom, Health and Settings. A page's tabs are in its header. The rail is narrower (208px) and fits a laptop screen without scrolling.
- Logs, Ask AI, and People & devices are pages of their own, each titled by its own name. Saved searches is a tab of Logs. Addresses are unchanged.
- Microsoft 365 is no longer in the rail. Its pages still open by their address and from Ctrl+K ("Microsoft 365") until they move into Logs, the person page, and the AI inventory in later steps.
- Health shows a small dot in the rail only when one of the sources you can read needs attention; a source paused on purpose does not count. On the Dashboard and Health the dot follows what the page itself shows, as it refreshes. On other pages it asks a new numbers-only request, `/api/health/count`, once every five minutes, so there it can be up to five minutes behind; that request names no source and writes no audit row, like the alert count, and it never stands in for the recorded read of Health or Sources: opening those pages is still recorded as before.
- An Auditor sees only what they can open: no Ask AI, and Logs opens on Saved searches unless an administrator has allowed Auditors to run SQL.
- The open-alert counts in the rail and on the bell use the solid High color. Ctrl+K lists every page and every tab under Navigate.
- What you will notice: a shorter left menu with no sub-items; Saved searches is now a tab on Logs; Microsoft 365 is found through Ctrl+K.
- What changes for existing installs: nothing to do. Bookmarks keep working. The rail no longer remembers folded groups, since there is nothing to fold.
