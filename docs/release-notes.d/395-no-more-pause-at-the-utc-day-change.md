### No more pause at the UTC day change (2026-11-03)

- At 00:00 UTC (4 PM Pacific), while the previous day's summaries were built, every page could pause for several seconds. Signing each request in now has its own threads, so it never waits behind slow page queries.
- The server log warns (`pool.wait`) when a request waits more than 2 seconds for a worker, with the request, how long it waited, and the jobs that were keeping the workers busy at the 2-second mark. The rollup log lines now give their start time, duration, and rows read.
- What changes for existing installs: nothing to do.
