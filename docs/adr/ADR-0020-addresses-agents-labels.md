# ADR-0020: People behind addresses, agent identities, and allowed-data labels

Status: **Accepted** 2026-10-16 (project owner, after comparing a commercial AI security console). Recorded as SPEC D50; threats T45 to T47.

## Context

Shadow AI found in network logs often stops at an address: "10.20.1.5 used DeepSeek". The logs to answer "who was that" are usually already collected: domain controller logons, firewall User-ID, VPN sessions. Agents (Claude Code sessions, MCP clients, API keys) appear in the AI flow but are not identities with an owner or a normal pattern, so a change in what an agent does goes unnoticed. And a service's review status (Approved, Unreviewed, Not approved) says nothing about what data may go to it.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Address to person and machine | Read at query time from events already in the lake: successful OCSF Authentication events (Windows 4624 and the like: client address, user, workstation; machine accounts name the machine), Palo Alto User-ID logins, and GlobalProtect sessions (private address, user, machine). For an address in an hour, the newest mapping seen up to the end of that hour and at most 12 hours before it wins. Used by AI usage, the AI flow (including one person's flow), the IP entity in Investigations, and a line in Search's event detail. `GET /api/addresses/{ip}?at=` answers directly, audited `address.lookup`. Each viewer sees only mappings from sources they may read | Turns addresses into people without a new collector or agent; deterministic and explainable ("from logon and User-ID events") | A stored IP table built at ingest (faster, but stale after access changes and hard to explain); DHCP logs (no starter template yet, added when one exists) |
| 2 | Agents as identities | An agent is a person's Claude Code, an MCP client's setup on a machine, or an API key in the Anthropic usage reports, with an owner (the person it runs as). Listed on AI usage, Agents tab | The question "whose agent is this and what does it normally do" needs both | Separate agent pages |
| 3 | Agent deviation | Per agent, a 30-day baseline of tools, MCP servers, destinations, and hourly volume. A new tool, MCP server, or destination, or volume over 3 times its usual peak, is a deviation: shown on the Agents tab and, if enabled in AI watch, alerted once per change (summary only, checked hourly, audited `ai.agent_change`) | Same first-seen idea as AI watch (ADR-0015 row 9), per agent | Model-based anomaly scoring (hard to explain, against the deterministic core) |
| 4 | Allowed-data labels | Each AI service can carry an allowed data level (Public, Internal, Confidential) set in the same review list where it is approved. Sensitive-data alerts (ADR-0015 row 13) are kept for services not set to Confidential and dropped for those that are; today the signals come from Claude Code telemetry, which goes to the Anthropic API service. Changes audited `ai.service_change` | Labels where discovery happens; uses signals already computed, no prompt content | Policy-document rule extraction by a model (later: needs prompt content) |
| 5 | Browser extension | Not now. If built, metadata only (service, user, time, prompt length, sensitive-type counts computed in the browser), never prompt text | A prompt-reading extension is a DLP product with a large privacy footprint | |

Row 1 shipped first; rows 2 to 4 in the next pull request.

## Consequences

- Row 1 adds one scan of logon and User-ID events to AI queries; at 14 million events AI usage went from about 5 s to 7 s, inside the 20 s limit.
- A mapping is a statement about the past ("had this address at the time"), shown with its source, never written onto events: `raw` and stored columns are unchanged.
- ATLAS: rows 2 and 3 help detect misuse of AI agents and tools, and row 4 data leakage to AI services (AML.T0057). ATT&CK: row 1 helps attribute T1567 Exfiltration Over Web Service and T1071 Application Layer Protocol use to a person.
- Threats: T45, a wrong mapping blames the wrong person (shown as "at that time", with the source and a 12-hour limit, and a mapping only from successful logons); T46, a viewer learns who had an address from sources they cannot read (mappings are computed in the viewer's scope); T47, an attacker logs on with stolen credentials and so is shown under the victim's name (the mapping says what the logs say; investigations still read the logon itself).
