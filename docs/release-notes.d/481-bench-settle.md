### The speed check no longer waits on its own requests (2026-11-10)

- The speed check waits for each server's event count to hold still before timing. Since #469 the server records every changing request in its built-in `server_events` source, and the count query is itself such a request, so on a lake built after #469 the count rose by one every read and never held still. The check now leaves `server_events` out of that count.
- It also never waits silently: a copied lake that is still adding events after 10 minutes (a new lake: 60 minutes) stops the check with the last counts, and while it waits it prints the count once a minute.
- Stopping the check (a timeout or a kill) now stops its two servers too; before, they kept running and took CPU from whatever ran next.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Only a developer script changes; no data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
