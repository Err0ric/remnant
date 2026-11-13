### Design: every page uses the one page header; the command bar is gone (2026-11-12)

- Console redesign, build row 3 (ADR-0052 section 3.5, D246). Every page now has the same header: its name and a short count or status on the left, and its buttons at the top right, with at most one filled button. The row of text commands under the title is removed everywhere.
- Logs: Save and Open are buttons at the top right; New search, Library, Schedule, Add to dashboard, and Export CSV are under the "More" button next to them. Run stays beside the search box and the SQL editor, where it already was, and is the page's one filled button.
- Alerts > Rules: "Enable selected", "Disable selected", and "Schedule selected" sit directly above the rule list they act on.
- Audit log: Export CSV is an outlined button at the top right; the "Append-only" sentence under the title is removed.
- Logs: while an export from the More menu runs, "Exporting…" shows beside the page title.
- On a phone the header's buttons take their own row under the title and tabs.
- `scripts/check-layout.py` also fails when a page has no `h1` or more than one.
- What you will notice: buttons moved from a row under the page title to the top right of the page, and on Logs five less-used commands are behind "More".
- What changes for existing installs: nothing.
