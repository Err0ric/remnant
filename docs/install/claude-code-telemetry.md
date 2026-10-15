# Claude Code usage, cost, MCP servers, and sensitive-data signals

Claude Code exports OpenTelemetry logs and metrics on every plan. Remnant receives them directly (no collector, no cloud service in between) and shows who used it, tokens and cost, which tools and MCP servers ran, and whether anyone sent keys, card numbers, or SSNs to it (ADR-0015).

## What is stored

| Arrives from Claude Code | Stored in Remnant |
|---|---|
| User email, session, terminal, model, tokens, cost, durations | Yes |
| Tool name, accept or reject, success | Yes |
| MCP server and tool names | Yes (needs `OTEL_LOG_TOOL_DETAILS=1`, see below) |
| Prompt text, tool input and arguments | **No.** Scanned for sensitive data, then dropped; only the categories and counts are kept (`attr.sensitive`) |

An administrator can choose **Keep prompt and tool content** on the source. Leave it off unless you have a reason and a policy for storing what people type.

## 1. Create the source (Remnant admin)

**Settings > Sources and connectors > Add source**, Source ID `claude_code`, **Reads from: OpenTelemetry**, Parser **Automatic**. Copy the token from the panel that appears (it is shown once) and the managed-settings block.

## 2. Push the settings to Claude Code (IT)

Put the `env` block in Claude Code's **managed settings** so users cannot turn it off: the Claude Admin Console (server-managed settings), MDM (Intune, Jamf), or the managed settings file. Example:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "https://siem.example.internal:8080/api/otlp",
    "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer rmt_...",
    "OTEL_LOG_TOOL_DETAILS": "1",
    "OTEL_LOG_USER_PROMPTS": "1",
    "NODE_EXTRA_CA_CERTS": "C:\\ProgramData\\Remnant\\remnant-ca.pem"
  }
}
```

| Line | Why |
|---|---|
| `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` | Remnant takes OTLP over HTTP with JSON; protobuf and gRPC are refused with a clear message |
| `OTEL_LOG_TOOL_DETAILS=1` | Without it, user-configured MCP servers show as `custom`. Remnant keeps the server and tool names and drops the arguments |
| `OTEL_LOG_USER_PROMPTS=1` | Lets Remnant flag sensitive data in prompts. The text is dropped after the scan. Remove it to send no prompt text at all |
| `NODE_EXTRA_CA_CERTS` | Only when Remnant uses its self-signed certificate: the path to that certificate on each machine |

The token can only send data into this one source. If it leaks, **New token** on the source replaces it at once.

## 3. Check it

Run anything in Claude Code, wait a minute, then **Search**: `source:claude_code`. Each event's `message` is the event or metric name (`claude_code.tool_result`, `claude_code.cost.usage`, ...); details are under `unmapped`.

Useful searches:

| Question | Search (SQL tab) |
|---|---|
| Cost per person, last 7 days | `SELECT actor_user_name, round(sum(TRY_CAST(json_extract_string(raw, '$.value') AS DOUBLE)), 2) AS usd FROM events WHERE message = 'claude_code.cost.usage' GROUP BY 1 ORDER BY 2 DESC` |
| MCP servers in use | `SELECT json_extract_string(raw, '$.attr.mcp_server_name') AS server, count(DISTINCT actor_user_name) AS people, count(*) AS calls FROM events WHERE message = 'claude_code.tool_result' AND server IS NOT NULL GROUP BY 1 ORDER BY 3 DESC` |
| Sensitive data sent | Simple search: `source:claude_code attr.sensitive_total:>0` |

## Limits

- The sensitive-data scan finds patterns (keys, tokens, card numbers that pass the Luhn check, US SSNs, private keys, `password=` lines). It is a detective control, not a block. To stop data reaching AI tools, use an inline control (Microsoft Purview Endpoint DLP, firewall DLP) and send its events to Remnant too.
- Built against the documented telemetry format; confirm with one machine before rolling out.
