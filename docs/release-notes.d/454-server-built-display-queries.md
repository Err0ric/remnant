### The app's own lists are built on the server (2026-11-08)

- The person page's sign-ins, the Microsoft 365 Sign-ins, Mail, Apps, and Admin lists, and the Sources page's event counts and parser mix no longer send SQL from the browser to the query endpoint. They call their own endpoints (`/api/people/{person}/signins`, `/api/m365/list`, `/api/sources/event-counts`, `/api/sources/parser-mix`), which build the SQL on the server and run it on your own sources, through the same guard, and audited as `query.view` with the list's name.
- These lists are display, like the dashboards, so they keep working for Auditors whatever the SQL setting for Auditors says.
- What you will notice: nothing visible.
- What changes for existing installs: the audit log shows `query.view` rows with a view name for these lists instead of `query.run` rows with their SQL. No data or settings change.
