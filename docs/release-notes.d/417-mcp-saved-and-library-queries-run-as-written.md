### MCP: saved and library queries run as written (2026-11-04)

- `run_query` on the MCP server fills `{{start}}`, `{{end}}`, `{{org_domains}}`, and `{{person:...}}` the way Logs, saved searches, schedules, and Ask do, so "Who uses Claude Code" gives the same people there. Any other `{{name}}` is refused with a reason.
- `local_only` still applies: with the MCP endpoint not marked local, the Claude Code rows, and so the people and accounts, are withheld.
- What changes for existing installs: nothing to do.
