### Design: charts as lines, one change pill, one cited ID chip (2026-11-12)

- Console redesign, build row 1b, third of four changes (ADR-0052 section 3.10, D248). Trend charts are thin lines with no filled area. Where a chart used to stack its parts into bands (AI use by review status on the Dashboard, failed sign-ins by class on Microsoft 365), each part is now its own line at its own value; the legend names them and the hover still gives the total.
- The change beside a headline number ("↑ 53", "same") is one neutral pill everywhere, and a cited event ID in an explanation or an Ask summary is one chip. A cited ID that was not among the events sent is outlined in the error color instead of filled.
- `scripts/check-layout.py` waits for the app's fonts and fails when Geist or Geist Mono is not the font in use, so pages are measured as users see them.
- `docs/BACKLOG.md`: a 2027 item for company-wide local AI through one gateway (nothing built).
- What you will notice: the Dashboard charts are lines, not filled bands; on the AI use chart and the Microsoft 365 failed sign-ins chart the lines no longer sit on top of each other, so read each line against the scale by itself.
- What changes for existing installs: nothing.
