### Comparison dates, "No earlier data", and the Needs you subject column (2026-11-16)

- "Comparisons start" now gives the day the window before is first covered, from one rule on the server for the Dashboard sections, AI Watch, Agents, and Microsoft 365. Before, the page added two whole windows to the newest source's start, so the date came about 4 days late (on a 30-day window, about 57 days of data are needed, so the date can still be weeks ahead).
- Agents no longer counts the server's own events as an AI telemetry source, so the day the server first ran no longer holds back its comparisons.
- While a section's sources have no data for the window before, no number shows a change: the server sends no earlier value. The Dashboard's Failed sign-ins and Sign-ins outside approved countries tiles say "No earlier data" in its place, instead of a rise from zero. A window before that has data and counted 0 still shows the change.
- Needs you on the Dashboard gives the subject column a fixed share of the row: source ids, host names, and addresses stay on one line and are cut in the middle when long, with the full value on hover and on copy. Titles wrap between words only, never inside a device id or address.
- Top services on the Dashboard shows 0 people as 0, as the Inventory does; "·" stays only for a value that is not known.
- What you will notice: the Dashboard's comparison dates are right, a tile with nothing earlier says "No earlier data", and long names in Needs you no longer break across lines.
- What changes for existing installs: nothing to do.
