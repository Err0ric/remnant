### Sign-ins and changes to this server are searchable in Logs (2026-11-08)

- The built-in `server_events` source now also records successful sign-ins (password and single sign-on) and every request that changes something or exports data: the time, user id and name, client address (through trusted proxies), method, route, status, and duration. Searching an address in Logs answers "who is this", not only the server journal.
- Never recorded: page reads, health polling, static files, ingest pushes, query strings, request bodies, headers, cookies, passwords, or tokens.
- Records are capped at 300 a minute for requests and 300 for sign-ins and refusals together, so a flood cannot fill the disk or crowd out a refused sign-in. The refused-credentials alert still counts refusals only.
- The source stays local-only and admin-only unless an admin adds it to a group. Health and the Dashboard still never call it quiet on a day nobody signs in. In GET /api/sources and GET /api/overview, the `events_on_failure` flag is now `quiet_expected`.
- What you will notice: sign-ins and admin changes to this server can be searched in Logs under the `server_events` source, for example by an address.
- What changes for existing installs: nothing to do; records start with the first sign-in after the update. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version stops writing these records and the ones already stored stay searchable.
