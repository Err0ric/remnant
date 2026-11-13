### Design: one page header, first on Alerts and the Dashboard (2026-11-12)

- Console redesign, build row 2 (ADR-0052 section 3.5, D246). `PageHeader` is the one header every page will use: the page's name and an optional count on the left; on the right up to two outlined buttons, a "More" menu for the rest, and at most one filled button, last. The page's tabs follow. With the keyboard the order is title, tabs, then the buttons.
- Alerts and the Dashboard use it now; the other pages follow in the next change and keep their row of text commands until then.
- Dashboard: the heading is always "Dashboard". A board's own name is in the board picker and at the right of the row under the header. "Edit layout" and "New dashboard" are buttons at the top right.
- Alerts: the sentence under the tabs ("Everything that fired and needs a decision...") is removed; the page does not explain itself in a paragraph.
- What you will notice: on the Dashboard and Alerts the title row is slimmer and the buttons sit at the top right.
- What changes for existing installs: nothing.
