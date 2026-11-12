### Tests no longer fail on a slow test machine (2026-11-11)

- Tests that measured elapsed time with tight limits failed on busy CI machines and cost extra runs. Each now checks the shape of the work (how many queries, no list written into the SQL), waits for the event it needs with a generous ceiling, or uses a fixed clock; real slowdowns are caught by the speed check on every app change.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Tests only.
