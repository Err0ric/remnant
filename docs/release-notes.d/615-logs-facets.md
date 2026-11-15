### Logs counts its fields in one pass (2026-11-14)

- The Fields panel beside Logs results (top values of source, host, user, addresses, severity, status, class, and parse status) now counts every field in one pass over only the columns it needs. Before, it ran the search once per field over every column and sorted the rows first. A text search over 7 days at the work install's rate took 12 seconds and timed out at 10; it now takes about 1.3 seconds, and 5 seconds over 30 days. The counts are the same.
- If counting ever takes too long, the panel says so in plain words with a Retry button; the results stay on the page.
- What you will notice: the Fields panel fills in quickly on long time ranges instead of showing a timeout.
- What changes for existing installs: nothing to do.
