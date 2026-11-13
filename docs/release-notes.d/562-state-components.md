### Design: loading, errors, and empty pages look the same everywhere they are used (2026-11-13)

- Console redesign, build row 14 (ADR-0052, DESIGN.md 6.0). Shared pieces for the states of a page: placeholder rows while a list loads (no jump when the data arrives, no spinner), an error in place with Retry, and an empty state at the top left with at most two lines and one action. Alerts and the Dashboard use them first.
- Alerts: an empty queue reads "No open alerts. Checked 2 min ago."; when the filters hide everything there is a Reset filters button; when the only alerts are in sources you cannot read, the page says so and does not say there are none.
- Dashboard: "No panels yet." with Go to Schedules.
- What you will notice: shorter, left-aligned messages on empty lists, and rows held in place while Alerts loads.
- What changes for existing installs: nothing to do.
