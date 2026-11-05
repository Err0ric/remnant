### Faster today-so-far build for quiet sources (2026-11-03)

- The 5-minute build of today's AI use now skips a source whose files have not changed since the last build, and carries its last result over. Busy sources build as before, so the results are the same.
- The server log line `ai_rollup.today` now says how many sources were carried over (`reused`).
- What changes for existing installs: nothing to do. The first build after updating is a full one.
