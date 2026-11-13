### Design: flat table headers, clearer edges on inputs and checkboxes (2026-11-12)

- Console redesign, build row 1b, second of four changes (ADR-0052 section 3.10, D248). Every table header is the same: no fill, small text in the secondary color over a thin divider.
- Text inputs, selects, and checkboxes have a darker edge (`--border-control`, at least 3:1 against what they sit on), so a field is visible before you click it. Checkboxes are drawn by the app in both themes and fill with the accent color when ticked. Buttons with a text label keep their lighter edge.
- What you will notice: quieter table headers, and input boxes and checkboxes that are easier to see, mostly in the light theme.
- What changes for existing installs: nothing.
