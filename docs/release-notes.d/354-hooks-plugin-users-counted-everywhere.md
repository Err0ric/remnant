### Hooks plugin users counted everywhere (2026-11-02)

- A person seen only through the Claude hooks plugin (a session start is enough) now appears on **Agents**, on **AI usage > People**, and in the "Claude Code users" count in the page header. Sessions that telemetry also reports are counted once.
- A session with no end record and nothing for 2 hours reads **Ended (no end event)**, with its last-seen time, instead of "still open". Set `agents.session_idle_minutes` in config/app.yaml to change the 2 hours.
- **Sessions** hides sessions with no tool calls or prompts by default; untick **Hide sessions with no tool calls or prompts** to see test and empty sessions.
- **AI usage > People** has a **Seen through** column: Plugin (telemetry or hooks), Network (DNS, firewall, or proxy logs to Claude), or Both. People seen only on the network are listed and counted as "Seen on the network but no plugin", so a Claude Code user missing the plugin stands out from a browser-only user. The Claude row on Services shows the same three counts.
- What changes for existing installs: nothing to do. The counts include hooks records already stored.
