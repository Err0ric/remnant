### Fewer, grouped alerts for AI agents (2026-11-03)

- One open alert per agent, rule, and day (the install's time zone). Repeats update that alert's count and list of changes instead of adding new alerts, and a message goes out only when the alert is new or gets more severe.
- A source that stops, sends again, and stops again the same day notifies again only if it was back at least 15 minutes, and at most 3 times a day; after that its alert keeps counting and its title says "flapping".
- A new agent is announced once. For its first 14 days its "changed" alerts stay quiet while it learns its usual tools; a new MCP server or MCP tool still alerts.
- Claude Code's own tools (any tool not named `mcp__...`) never raise "changed". New ones arrive with Claude Code updates and show on Agents.
- New: a personal Claude account on a company device (medium, once per account and device) and 10 or more blocked or failed tool calls in an hour for one agent (high).
- What changes for existing installs: on the first start, open duplicate alerts from before are merged into the oldest one of each group; each merge is audited and the others close as Merged. New settings: `agents.learning_days` (14), `agents.blocked_burst` (10), `sources.gap_renotify_min_back` (15 minutes), and `sources.gap_max_notify_per_day` (3).
- What changes for existing installs: on the first start, open duplicate alerts from before are merged into the oldest one of each group; each merge is audited and the others close as Merged. New settings: `agents.learning_days` (14) and `agents.blocked_burst` (10).
