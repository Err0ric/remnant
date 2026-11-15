### The Dashboard's Detections and Agents read less on large installs (2026-11-14)

- Detections on the Dashboard looks up the person and host of each matched event in the sources those matches came from, from the first match on, instead of in every source over the window and the window before. On 30 days of synthetic data at the work install's rate that lookup took 1.7 seconds and now takes a few milliseconds, with the same events.
- Agents (on the Dashboard's AI Watch and on Agents) reads only the sources whose files can hold Claude Code telemetry, hook records, MCP inventories, or usage reports, decided by each file's own statistics, so a new or custom source that receives such records is still read. The answers are the same.
- What you will notice: the Dashboard and Agents open faster on large installs.
- What changes for existing installs: nothing to do.
