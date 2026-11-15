### Logs results: a pager you cannot miss, and a table that fits (2026-11-13)

- A results table with more than 50 rows has Previous and Next as buttons right beside the count ("1 to 50 of 10,000"), above the rows and again below them, and a Rows per page choice of 50, 100, or 500 that the browser remembers. Before, Previous and Next were two small links at the far right under row 50, easy to miss; they were never removed, and nothing in the redesign changed them.
- The results table is as wide as its box. Message takes the width the other columns leave and is cut with the full text on hover and in the expanded row. Before, a long message made the table wider than its box, so Message ran off the right edge and the table scrolled sideways. It still scrolls sideways inside its box when the chosen columns alone need more room.
- The same table is used by the Microsoft 365 views, a person's Microsoft 365 list, and saved search runs, so they get both changes.
- The smoke test now fails when a results list of more than one page has no pager, a pager whose Next button is off screen or disabled, or a Next that does not show other rows.
- What you will notice: Previous, Next, and Rows per page at the top left of the results, and no sideways scrolling for long messages.
- What changes for existing installs: nothing to do.
