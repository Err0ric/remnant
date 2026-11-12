### Server events keep sign-ins, changes, exports, and denials only (2026-11-10)

- The built-in `server_events` source recorded every request that was not a GET, so each search, count, facet, Ask, and Explain became an event. It now records only sign-ins, setup, user and token changes, exports and hand-offs, and admin and settings changes, plus any request that was denied or throttled (401, 403, 429) and any query the safety check blocked (for example ATTACH, read_csv, or COPY). A typo in a query is not recorded.
- Searches and other reads are still in the audit log with the user, as before; only the copy in `server_events` stops.
- A new endpoint has to be listed as recorded or read-only, or a test fails, so a change is never dropped by accident.
- What you will notice: far fewer `server.request` events in Logs for the `server_events` source; searches no longer appear there.
- What changes for existing installs: nothing to do. Events already stored stay; no settings or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
