### Auditors run no SQL until an admin allows it (2026-11-08)

- An Auditor reviews the audit log, dashboards, and reports. Logs (SQL, live search, and the field counts), export of query results, saved-search runs, Ask, the CLI `query`, and the MCP server now refuse an Auditor with a plain message (D220).
- New setting **Let Auditors run SQL** in Settings > Users and access, admins only, off by default. Each change is recorded in the audit log as `settings.auditor_sql` with who made it. When on, an Auditor searches only the sources their groups grant, through the same guard as anyone.
- For an Auditor with the setting off, Logs shows the reason instead of the editor, Ask is hidden, and Run is turned off on Saved searches.
- What you will notice: an Auditor no longer sees the SQL editor, Ask, or Run on saved searches until an admin turns on Let Auditors run SQL.
- What changes for existing installs: Auditors lose SQL until an admin turns the setting on.
