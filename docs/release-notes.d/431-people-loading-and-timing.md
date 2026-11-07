### People and devices says it is loading, and where the time goes (2026-11-06)

- While People and devices loads, its tabs show no counts (no more "Users (0)") and the table area says it is counting, with a progress bar; the counts appear when the ranking arrives.
- The page's response carries a Server-Timing header with a named time for each part of the load (signals, rule matches, the people split, enrichment, identities, audit), so the browser's network panel shows what is slow. Only fixed names and durations, never data.
- What changes for existing installs: nothing to set up.
