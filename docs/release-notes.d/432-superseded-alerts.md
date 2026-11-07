### Alerts that current rules no longer raise close on upgrade (2026-11-06)

- On the first start after this upgrade, the server checks every open alert against the current rules and closes the ones they would no longer raise, with the reason "Superseded by rule change". Today that is two kinds: "AI agent changed" alerts about built-in Claude Code tools only (built-in tools no longer raise "changed", ADR-0043), and source gap alerts for a source that was removed or whose Alert if quiet is off.
- Alerts the current rules would still raise stay open, and so does any alert someone already acted on (reopened, or with a note). The check runs once per version and never again on its own.
- To see which alerts were closed: Alerts > Closed shows the reason "Superseded by rule change" on each, with the closing in its history; Audit lists one `alert.close` row per alert with reason `superseded` and no user. Any of them can be reopened.
- What changes for existing installs: on the next start, open alerts from retired rules close by themselves, each with an audit row; nothing to do unless you want to reopen one.
