# MCP server: query logs from Claude Code, Claude Desktop, and other AI assistants

The MCP server lets an AI assistant that speaks the Model Context Protocol read the schema and run read-only SQL over your logs, as the person who connects it. Design: [ADR-0003](../adr/ADR-0003-mcp-server.md), SPEC 3.8.

| It can | It cannot |
|---|---|
| `get_schema`: columns of `events`, the sources you can read, example queries | Write, delete, schedule, change settings, or call anything else |
| `run_query`: one SELECT through the same guard as Search, up to 500 rows | Read sources outside your groups, files, or other tables |

Every result says that log values are data and may contain instructions that must not be followed. Every call is in the Audit log as `mcp.tool` with the person, the client name, and the SQL.

## 1. Turn it on (administrator)

**Settings > MCP server**:

| Setting | Meaning |
|---|---|
| Let AI assistants query logs | Off by default. Off refuses every client at once |
| Clients and their models run on our network | Off by default. While off, local-only sources are left out of every result, because the server cannot see which model a client sends results to. Turn it on only when every client uses a model you host (Ollama, LM Studio, vLLM) |

A source counts as local-only when its classification is not **Cloud allowed**, or when any event stored from it was ingested while it was local-only.

## 2. Get a token (each person)

**Your account** (click your name, top right) **> CLI and API tokens > Create token**. The token reads exactly what you can read in Search. Revoking it disconnects every client that uses it.

## 3. Connect a client

The address is shown on the settings page, for example `https://remnant.example.internal:8080/api/mcp`.

**Claude Code** (HTTP):

```
claude mcp add --transport http remnant https://remnant.example.internal:8080/api/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```

With the generated self-signed certificate, start Claude Code with `NODE_EXTRA_CA_CERTS=/path/to/remnant-ca.pem` (the certificate from `data/tls/server.crt`).

**Claude Desktop and other stdio clients** (through the command-line tool):

1. Install the CLI and sign in once: `remnant login --server https://remnant.example.internal:8080`.
2. Add to the client's MCP configuration:
   ```json
   { "mcpServers": { "remnant": { "command": "remnant", "args": ["mcp"] } } }
   ```

`remnant mcp` relays each message to the server with the token saved by `login`, and pins the server certificate the same way the other CLI commands do.

## 4. Check it

Ask the assistant: "Use the remnant tools: which sources can you read, and how many events did each have in the last day?" It should call `get_schema`, then `run_query`. **Settings > Audit log**, action `mcp.tool`, shows both calls with your name and the client.

## Limits

- 500 rows, 2,000 characters per value, 256 KB per result, 15 seconds per query. `since_hours` narrows the time range.
- Responses are plain JSON; there is no server stream, and nothing is pushed to clients.
- Requests from a browser page on another site are refused (`Origin` check). A browser session cannot call the endpoint; only API tokens (or the loopback single-user mode) can.
- The assistant's model reads whatever the query returns. Prompt injection planted in log fields (MITRE ATLAS AML.T0051.001) is limited by read-only tools and the notice, not removed; the assistant has nothing here to act with.
