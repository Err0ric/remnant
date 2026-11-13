### Design: severity colors only for severities; states are outlined tags (2026-11-12)

- Console redesign, build row 1b, last of four changes (ADR-0052 section 3.10, D248). The tinted red, orange, and yellow boxes that marked things other than an alert severity are gone: errors, failed checks, blocked requests, and "Out of date" are outlined in the error color; warnings, "Needs attention", denied outcomes, "Changed", and sensitive-data counts are outlined in the warning color; neutral tags (success, built in, counts) sit on the plain gray tag fill, and "New agent" is a neutral outlined tag, because the accent color is kept for links and selection. Solid red and orange now always mean a Critical or High severity.
- The Health page's per-source flow lines have no filled area, like the other charts, and its header row is flat.
- The old tinted color tokens are removed from `tokens.css`.
- What you will notice: error and warning messages are a colored outline with colored text instead of a tinted box; nothing moved.
- What changes for existing installs: nothing.
