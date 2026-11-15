### Clearer quiet alerts, and AI Watch's "no data after" follows the events' dates (2026-11-15)

- When a source's newest event is much older than its last delivery (an offline queue, an import), its quiet alert now reads "No new events for 7 d. Newest event dated ... UTC; last data arrived ... UTC." In the ordinary case it still reads "No events received for 7 d".
- AI Watch's chart on the Dashboard says "no data after" the newest event's own date, so old events that arrived just now no longer make it look complete up to today.
- What you will notice: clearer quiet alert text in that case, and AI Watch's chart marks the days with no data yet correctly.
- What changes for existing installs: nothing to do.
