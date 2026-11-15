### How long a source has been quiet counts from its newest event (2026-11-14)

- "Quiet", "Idle", and "No events for" on Health, Sources, and the Sources healthy line now count from the newest event's own time, the same time the status is judged from.
- Before, they counted from when a record last arrived, so old events delivered now (a Claude plugin's offline queue, a history import) read "Quiet 7 s" for a source with nothing newer than two days. "Last received" still shows when a record last arrived.
- What you will notice: a source that just received old events reads "Quiet 2 d" (or "Idle, No events for 2 d"), not a few seconds.
- What changes for existing installs: nothing to do.
