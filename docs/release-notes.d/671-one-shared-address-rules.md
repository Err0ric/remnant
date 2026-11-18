### One outcome rule for the access card and the entity pages (2026-11-18)

- The address page's "Sign-ins and access" card and the person, address, and host pages' "What it did" and lanes now read an event's outcome (allowed, denied, signed out, succeeded, failed, not counted, other) from one SQL function, `access_outcome`, that every query defines, instead of two copies of the rule.
- The library query "Sign-ins and access for one address" (Addresses pack 1.0.1) calls that function, so its SQL is shorter; its rows and counts are the same, and it reads the Microsoft 365 error code only on Microsoft 365 sign-ins, as the entity pages do.
- Each row of What it did opens exactly its own events in Logs: a sign-in with no outcome recorded (Other) no longer opens the person's other sign-ins to the same target as well, and a row with no user or no target opens only the events without one, not those of every user or target.
- What you will notice: an Other row, or a row with no user or no target, in What it did opens only its own events; the SQL of that library query is shorter in Library and Logs.
- What changes for existing installs: nothing to do. A copy of the Addresses pack's query saved before the update keeps its own SQL and shows as updated in Library. To go back, install the previous version as in `docs/install/` (`update-systemd.sh --rollback`).
