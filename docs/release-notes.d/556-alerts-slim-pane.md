### Design: a slimmer alert pane with one filled button (2026-11-12)

- Console redesign, build row 19 (ADR-0052, DESIGN.md 6.2e). The pane beside the alert list shows what you need to decide: severity, kind, state, and the alert's ID; the title; what fired; why it matters; who and what it is about; when; the next steps; then the actions. Close is the one filled button. "Show events in Logs" sits beside it and opens the alert's own events.
- Changes today, the rows that fired, Approve or Not approved, and the history are still in the pane, in one section called "Evidence, changes, and history" that starts closed. They move to the full alert page when that page is built; until then nothing is lost, it is one click away.
- The summary strip above the list (open by severity, new today, oldest open, by category) is removed. The Severity and Category filters under the tabs do the same filtering. The note about alerts in sources you cannot read is at the foot of the list, with no count.
- What you will notice: the alert pane is shorter and fits a laptop screen without scrolling; to approve a service or read the history from an alert, open "Evidence, changes, and history" first.
- What changes for existing installs: nothing.
