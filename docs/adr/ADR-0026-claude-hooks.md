# ADR-0026: Observe Claude agent sessions with a hooks plugin that reports to this server

Status: **Accepted** 2026-10-20 (project owner: "whatever you recommend honestly. All of that sounds good"). Recorded as SPEC D68; threat T57 added.

## Context

Claude Code telemetry (ADR-0015) gives counts, cost, and tool decisions; the MCP inventory gives what is installed. Neither gives the order of events in one agent session: the prompt, each tool call with what it touched, each result, the end. That sequence is what "agents as insiders" needs (session timeline, per-agent baselines, detections). Claude Code and Claude Desktop run hooks at session start, prompt submit, before and after each tool call, and stop. Hooks can also return allow or block; this design only observes.

## Decision

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Transport | The hook script sends each event as an OTLP/HTTP JSON log record to an existing OpenTelemetry source on this server, with that source's token | Reuses the receiver, per-source tokens, content setting, and audit (ADR-0015); no new endpoint |
| 2 | Observe or enforce | Observe only. The script never returns a block, sends in the background with a 2-second timeout, and always exits 0 | A slow or down SIEM must never stop someone's work. Blocking is a guardrail product |
| 3 | Events | Session start, prompt submit, before tool use, after tool use, stop | The five that make a session timeline |
| 4 | What is sent by default | Event name, time, session id, host, OS user, client, tool name, MCP server and tool, outcome, duration, sizes. For file tools the path; for web tools the host; for shell commands the program name only. SHA-256 of prompt and tool input | Enough for timelines, baselines, and detections without content |
| 5 | Content | Off by default. The source's existing "keep content" setting (ADR-0015 row 3) turns on prompt text, tool input, and tool output, each capped at 8 KB (first and last 4 KB) | Content is the most sensitive data the server would hold; it is a deliberate choice per source |
| 6 | Where in the session | Every record carries `role`: user, tool_call, tool_result, or session | Says where in a session each record sits |
| 7 | Destination | Server URL and token are written into the plugin's config at install from the source page; nothing in a prompt, tool output, or event can change them | No redirect by injected text |
| 8 | Packaging | A Claude plugin (hooks only, no skills, no commands) built from the source page, plus a POSIX shell script and a PowerShell script that use only `curl` or `Invoke-RestMethod`. Small enough to read in one sitting; version and SHA-256 shown on the source page | Runs on every tool call, so it must be easy to review |
| 9 | Handling on the server | Records are log content: untrusted, stored with `raw` intact, never placed in instructions (security rule 2). A new template maps them to OCSF and the agents view | Same as every source |
| 10 | Coverage | Sees only Claude Code and Claude Desktop installs with the plugin. Browser chat and other vendors' agents stay visible only through network logs and the AI service catalog; the AI usage page says so | Honest boundary |
| 11 | Build order | (a) Plugin, scripts, template, session timeline in Agents. (b) Detections: new tool or destination for an agent, sensitive paths, shell after web fetch. (c) Per-agent baselines | Thin slices |

## Consequences

- Volume: one record per tool call per user. A busy developer can send thousands a day; retention for the source applies as usual.
- Removing the plugin stops the records; the session and agent views show when a machine last reported, and the device watch (ADR-0019) can alert on silence.
- ATLAS: AML.T0051 (indirect prompt injection) through tool output stored as content: stored as data, never in a prompt as instructions. AML.T0057 (data leakage): content off by default, `local_only` by default on the source. The plugin itself is code on every endpoint: AML.T0010 (ML supply chain compromise) and ATT&CK T1546 (event triggered execution) if it were tampered with, so it is pinned, hashed, and short.
- Threats: T57 (an attacker reads or alters the agent record: per-source token, HTTPS off loopback, integrity chain over the lake files, content off by default).
