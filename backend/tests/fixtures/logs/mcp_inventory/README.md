# mcp_inventory fixtures

| | |
|---|---|
| Source product | MCP client configuration on endpoints (Claude Desktop, Claude Code, Cursor, VS Code) |
| Collector shape | JSON lines written by `scripts/endpoint/mcp-inventory.ps1` / `.sh` |
| Generator | `scripts/fixtures/ai_telemetry.py` (seed 42) |
| Values | Invented hosts, users, and server names; remote servers use `.example` hosts |

Pathological lines cover wrong types, a huge server name, truncated JSON, and unrelated events.
