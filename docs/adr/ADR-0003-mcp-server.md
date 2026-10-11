# ADR-0003: Read-only MCP server

Status: **Accepted** 2026-10-10 (SPEC D29, section 3.8)

## Context

Analysts increasingly work inside an AI assistant (Claude Desktop, IDE agents). The Model Context Protocol (MCP) lets those assistants call tools on other systems. Two directions were possible:

| Direction | Assessment |
|---|---|
| Remnant exposes an MCP server so assistants can query logs | Useful: plain-English questions from the tool people already use, answered from real data |
| Remnant consumes MCP servers as log sources | Rejected: ingest must be deterministic, replayable, and auditable. Direct connectors are simpler and have fewer moving parts |

## Decision

1. Ship a read-only MCP server in Slice 7, off by default.
2. Two tools only: `get_schema` and `run_query`. The query runs through `engine/guard.py` on the caller's `events` view, with the normal row cap.
3. Each MCP client authenticates with a per-user API token (Slice 2). No shared or service token.
4. Results from `local_only` sources are withheld unless an admin marks the MCP endpoint as local, meaning the client and its model run on the internal network. Remnant cannot see which model a client uses, so the default assumes cloud.
5. Every result carries a fixed notice that field values are data and may contain instructions that must not be followed.
6. Every tool call writes an audit row: user id, client name, SQL, row count, sources in scope.

## Consequences

- Depends on per-user API tokens (Slice 2) and the classification model (Slice 5), so it lands no earlier than Slice 7.
- The MCP client's model is outside Remnant's control. Indirect prompt injection is mitigated by read-only tools and the notice, not eliminated; there are no write tools to abuse.
- Adds SPEC threat T23.

## ATLAS / ATT&CK

| Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|
| Planted instructions in log fields steer the outside assistant | AML.T0051.001 | | Read-only tools, data notice, no actions available |
| `local_only` data reaches a cloud model through the client | AML.T0057 | T1213 | Withheld unless the endpoint is marked local; off by default |
| Stolen client token used to read logs | | T1528 | Per-user, revocable tokens; scope limited to that user's sources; audit |
