### Stopping the server stops a query that was just starting (2026-11-11)

- When the server stops, it interrupts running queries and waits for them (#490). A query that was just starting could miss that interrupt and keep the stop waiting for up to 10 seconds. The server now repeats the interrupt until every query has stopped.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
