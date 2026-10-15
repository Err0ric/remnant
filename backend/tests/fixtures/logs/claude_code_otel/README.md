# claude_code_otel fixtures

| | |
|---|---|
| Source product | Claude Code 2.x OpenTelemetry export (logs and metrics) |
| Collector shape | OTLP/HTTP JSON as sent with `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`, converted by Remnant's receiver (`app/ingest/otlp.py`) with content dropped |
| Generator | `scripts/fixtures/ai_telemetry.py` (seed 42) |
| Values | Synthetic `example.com` users, invented hosts and sessions |

Sessions mix user_prompt (text dropped, length kept), api_request, tool_decision and tool_result for built-in tools and MCP servers (server and tool names kept from tool_parameters, arguments dropped), api_error, and cost and token metric points. Pathological lines cover bad times, wrong types, huge values, and broken JSON.
