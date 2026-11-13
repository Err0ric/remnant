### Design: one filter bar, first on Alerts (2026-11-12)

- Console redesign, build row 6 (ADR-0052, DESIGN.md 6.0). A shared filter bar in a fixed order: Time, State, the other filters, the text box, with the count on the right. Alerts uses it: State is three buttons (Open with its count, Closed, Muted), Severity and Category read as "Severity High", and the count says how many alerts are listed ("2 alerts", "1 of 2 alerts"). The count is only of alerts you can read.
- Filters are in the address (`/alerts#state=closed&sev=high`), so a filtered list can be bookmarked or sent, and Back undoes a filter. Reset appears only while a filter is off its default.
- The Alerts queue has no Time filter yet: every open alert is listed, as before.
- What you will notice: the Alerts filters look like one bar, with a Reset link when something is filtered.
- What changes for existing installs: nothing to do.
