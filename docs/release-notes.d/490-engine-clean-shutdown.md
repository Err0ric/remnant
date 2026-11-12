### The server stops its running queries before it exits (2026-11-10)

- When the server stops, it now stops any query still running and waits for it to close before the process exits. Before, a query left running after another one ran out of memory could make the process end with an abort on the way out (about 1 exit in 10 in a test loop), so a normal stop or restart could be reported as a failure.
- Queries that arrive while the server is stopping are refused with "The server is shutting down".
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do; no data or settings change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
