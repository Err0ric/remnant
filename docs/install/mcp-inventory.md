# MCP server inventory from endpoints

Lists every MCP server configured in Claude Desktop, Claude Code, Cursor, VS Code, and Windsurf on a machine, including ones nobody has used yet (ADR-0015 row 6). Pair it with Claude Code telemetry, which shows the servers that were actually called.

**Names only.** The scripts report the server name, client, transport, the launcher (npx, uvx, docker), the package a launcher runs, and the host of a remote server's URL. They never read or send arguments, environment variables, headers, or full URLs, because those often hold tokens.

## Run it

| OS | Command |
|---|---|
| Windows (PowerShell 5.1+) | `.\mcp-inventory.ps1 -Endpoint https://siem.example.internal:8080/api/otlp -TokenFile C:\ProgramData\Remnant\token.txt` |
| Linux, macOS (Python 3.8+) | `python3 mcp_inventory.py --endpoint https://siem.example.internal:8080/api/otlp --token-file /etc/remnant/token` |
| To a file instead | `-OutFile C:\ProgramData\Remnant\mcp-inventory.jsonl` / `--out /var/log/mcp-inventory.jsonl` (then read that file with any source) |

Run as SYSTEM or root to cover every user profile on the machine; as a normal user it covers that user only. Schedule it daily from an RMM tool, Intune, a scheduled task, or cron. The token can be the endpoint agent group's token or a dedicated OTLP source's; the token is read from a file so it never appears in process lists.

The PowerShell version is written to the same rules as the Python one, which is tested; run it once on a Windows machine and check the output before scheduling it widely.

## See it

Search `class_uid:5020` or the source you sent it to. Each server is one event: `message` is the server name, `device_hostname` the machine, `actor_user_name` the profile, `actor_process_name` the launcher, `dst_endpoint_hostname` a remote server's host.

Servers not on your approved list show as **Unreviewed** or **Not approved** on the **AI usage** page, and the AI watch can alert the first time one appears on a machine.
