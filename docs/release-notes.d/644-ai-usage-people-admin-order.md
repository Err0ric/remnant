### AI usage People rows, the Admin view's lists, and one order on every load (2026-11-16)

- AI usage > People: a person seen only on the network keeps each value in its own column. What the network saw is under Network, "Unmatched" and Link in Identities are under the name, cost and tokens say "Not reported", and sessions, tool calls, and errors are empty, with the reason said once above the table; no sentence runs across the columns. "No cost data" is now "None received": Claude Code telemetry reports cost and tokens, and none arrived.
- Logs > Views > Microsoft 365 admin, Sign-ins, and Mail: each list counts its rows in its own words ("1 app consent", "3 sign-ins") and its columns have plain headers ("Person", "App ID") instead of column names.
- AI usage lists keep one order on every load: services and people with equal counts are listed by name, and Inventory items seen at the same time are listed by type, then by name.
- "N new, N no longer seen" beside the time control counts AI services only on AI usage (MCP servers were counted too), so it matches the New badges and the No longer seen card.
- What you will notice: AI usage People rows stay inside their columns, the Admin view says "1 app consent" with plain headers, and AI usage lists no longer change order between loads.
- What changes for existing installs: nothing to do.
