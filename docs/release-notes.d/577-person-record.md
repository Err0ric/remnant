### Design: the person page is one page (2026-11-13)

- Console redesign, build row 22 (ADR-0052, DESIGN.md 6.3). A person's page no longer has tabs. It leads with one sentence and five numbers (Open alerts, Sign-ins, Devices, Addresses, AI services), then Open alerts, Activity per day, Microsoft 365, AI use, and What it did, with Accounts, Devices, and Addresses at the side.
- Activity per day is new: one bar per day with failed sign-ins marked (real failures only; a sign-in that was interrupted or expired is not a failure), and a bar opens that day's events in Logs.
- Devices and Addresses list every row with events, failed sign-ins, and last seen, as the old Hosts and devices tab did, in the side column.
- Microsoft 365 is one table with a Sign-ins, Mail, Admin switch and Open in Logs. It is shown only when you can read a Microsoft 365 source. The server builds and runs each list with your own source access.
- The pages of a person, an address, and a host have the entity as the title, "People & devices" above it to go back, and Open in Logs as the one filled button.
- How it connects and the Timeline are folded at the foot of a person's page and are read only when opened, so the page loads faster.
- Without View people in AI usage, a notice above the summary says the person's AI activity is not shown, and the AI services number reads "Hidden".
- New read-only API: `GET /api/people/{person}/record` and `GET /api/people/{person}/m365` (in `docs/api.md`). `GET /api/people/{person}/signins` is unchanged.
- What you will notice: a person's page is one scrolling page instead of five tabs, with a chart of activity per day and Mail and Admin rows beside the sign-ins.
- What changes for existing installs: nothing to do. Links to a person's page work as before; a link that named the AI use tab opens the page at AI use.
