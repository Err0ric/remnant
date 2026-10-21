# AI usage: shadow AI, MCP servers, Claude usage, and the AI watch

**AI > AI usage** answers the compliance questions about AI tools in one place (ADR-0015): which AI services people use, which agents and MCP servers are installed or running, what Claude Code costs and who uses it, and whether sensitive data went to an AI tool. Everything is computed from your own logs, on this server, from the sources each viewer may read.

## What feeds each tab

| Tab | Data | How to get it |
|---|---|---|
| **Services** | DNS, firewall, and proxy logs matched by destination domain against the AI service catalog | Any DNS source (BIND, Unbound, Windows DNS), Palo Alto or FortiGate logs with URLs or host names. Nothing new to install |
| **Agents** | Claude Code per person, MCP setups per machine and client, and Anthropic API keys, each compared with its own last 30 days | [claude-code-telemetry.md](claude-code-telemetry.md), [mcp-inventory.md](mcp-inventory.md), [anthropic-admin-api.md](anthropic-admin-api.md) |
| **MCP servers** | MCP servers installed on endpoints, and MCP servers Claude Code actually called | [mcp-inventory.md](mcp-inventory.md) and [claude-code-telemetry.md](claude-code-telemetry.md) |
| **Claude usage** | Cost, tokens, sessions, tool calls, errors, sensitive-data signals per person | [claude-code-telemetry.md](claude-code-telemetry.md); the organization's usage, cost, and audit reports from [anthropic-admin-api.md](anthropic-admin-api.md) |
| **Review and alerts** (admins) | The AI watch, MCP server rules, and the service catalog | This page |

Microsoft 365 Copilot interactions (`message = 'CopilotInteraction'`) and DLP rule matches arrive with the Microsoft 365 source: [m365.md](m365.md).

## Review

Every service and MCP server is **Approved**, **Not approved**, or **Unreviewed** (the default).

- **Services:** set the status from the Services tab or the catalog. Add your own entries for internal model gateways or vendors that are not listed (name and domains). Matching uses the longest domain, so `api.openai.com` counts as OpenAI API, not ChatGPT.
- **MCP servers:** rules are an exact server name, as the config writes it (spaces are fine), or a prefix ending in `*` (`internal-*`). Exact names win over prefixes.
- Every change is in the audit log (`ai.service_change`, `ai.mcp_change`).

## AI watch

**Review and alerts > AI watch** sends one alert the first time something not approved is seen for a person or machine, for example "ChatGPT by 10.20.1.5" or "MCP paste-share by alice@example.com", and one when sensitive data is sent to Claude Code. A sighting alerts once, ever; restarts do not repeat it. Tick **Also alert on Unreviewed** to hear about everything new while you build the approved list.

Alerts go to the targets you pick (Teams, Slack, email, webhook) as summaries, never content, and are also recorded in the audit log (`ai.sighting`, `ai.sensitive`).

## Reading the numbers

- **People** comes from user names in the logs (firewall User-ID, telemetry email). DNS logs have only the client address, so for those the **Who** column lists machines.
- **Claude Code cost** is Claude Code's own estimate (`claude_code.cost.usage`, delta temporality, the default).
- Anyone who can see a source sees its AI numbers; put AI-related sources in a source group limited to the people who review them.

## Agents

**AI usage > Agents** lists Claude Code per person (with the machine it last ran on), MCP setups per machine and client, and Anthropic API keys, with their owner. Each is compared with its own last 30 days: a tool, MCP server, or model first used in the last 24 hours, or an hour more than three times busier than its usual busiest, marks it **Changed**. An agent first seen in the last 24 hours is **New agent**. To be told, turn on **Alert when an AI agent changes** under **Review and alerts**; each change, and each new agent, is alerted once.

## Allowed data

Next to each service's review status, **Allowed data** (Public, Internal, Confidential) records the most sensitive data that may go to it. Sensitive-data alerts are skipped for a service set to Confidential, so a sanctioned tool cleared for that data does not alert on every key or card number.
