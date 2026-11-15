### Design: the page pattern is checked on every change (2026-11-13)

- Console redesign, build row 24 (ADR-0052, DESIGN.md 6.0). The layout check that opens every page in both themes at 1280px now also fails when a page has more than 10 rail entries, more than 5 tabs, or more than one filled button. It opens every tab at its own address and a person, address, and host page.
- Three pages had more than one filled button and now have none: the Save buttons on Settings > About, Download plugin on Settings > Plugins, and Add domain and Add alias on Settings > Identities are outlined buttons. They do the same thing.
- What you will notice: a few Settings buttons are outlined instead of filled.
- What changes for existing installs: nothing to do.
