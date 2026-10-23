# claude_hooks fixtures

| | |
|---|---|
| Source product | Remnant hooks plugin 1.0.0 for Claude Code and Cowork (ADR-0026), `hooks/send.sh` |
| Collector shape | OTLP/HTTP JSON log records, converted by Remnant's receiver (`app/ingest/otlp.py`) with content dropped |
| Generator | `scripts/fixtures/claude_hooks.py` (seed 26) |
| Values | Synthetic `example.com` people (one with no account email, so the OS user is used), invented hosts, sessions, and paths |

Six sessions: start, prompt (hash and length only), three tool calls with their results (file paths, a web host, program names, an MCP server and tool), and stop. Pathological lines cover bad times, wrong types, a very long path, an unknown event, and broken JSON.
