# ADR-0043: Alert grouping, a learning period for new agents, and severity per AI watch rule

Status: **Accepted** 2026-11-03 19:38 by the owner, with one change (row 8: built-in means any tool without the `mcp__` prefix, not a fixed list) and the answers below. Amends ADR-0020 row 3 (agent changes alerted once per change), ADR-0035 (AI watch items), and ADR-0037 rows 14 and 16 (close reasons, mute). Recorded as SPEC D200.

## Context

The hooks plugin is about to roll out. Today one Claude Code session produced six "AI agent changed" alerts in one minute, one per built-in tool (Agent, Bash, Write, WebSearch, ToolSearch, SubagentHandback). Three rules make that happen:

- Every new item an agent uses is its own alert item (`ref_id = agent:<agent>:<kind>:<name>`), so one session's first tools are six items.
- A new agent is reviewed once, but the tools it uses on its first days are "changes" against a baseline that does not exist yet.
- Built-in Claude Code tools count as changes the same way an MCP server does, and every agent item is medium severity.

With 50 people on the plugin, the first week would be several hundred open items that say nothing.

## Decision

### Grouping

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | What one open alert covers | One open item per **entity + rule + day**. The entity is the agent, person, device, service, or source the item names; the rule is the AI watch rule (new MCP server or tool, blocked calls, busy hour), the detection rule, the schedule, the gap, or the refusal check; the day is the install's time zone day (`schedules.timezone`, UTC by default). Standing review items (an agent, service, or MCP server waiting for a decision) and a personal account on a device stay one per subject, as before | A day is how the lead reads the queue: "dana's agent picked up two MCP tools today" is one decision | Per change (today, floods); per entity forever (hides a new problem behind an old open one) |
| 2 | A repeat while it is open | Updates that item: the count goes up, the change list gains the new line (newest first, the first 20 kept, then "and N more"), `last_seen` moves, and the severity rises if the new line is more severe. No new item, no new notification. A repeat after the condition had ended (a quiet source that sent again, then went quiet again) clears the resolved note and notifies again, with a flap guard (owner, 2026-11-03): only when the source was back at least 15 minutes (`sources.gap_renotify_min_back`), and at most 3 notifications per source per day in all (`sources.gap_max_notify_per_day`); after that the alert keeps counting and its title says "flapping" | The bell and the chat target stay quiet for the same thing on the same day | A new item per repeat |
| 3 | A repeat after it was closed the same day | A new item for that entity, rule, and day, linked to the closed one ("closed earlier today as Expected") | A closed decision is not reopened silently, and a new problem is not hidden | Reopen the closed item |
| 4 | Notifications (Slack, Teams, email, webhook) | Sent when an item is created, and again only when its severity rises. Count updates do not notify | Same reason as row 2 | Notify on every repeat |
| 5 | Existing duplicates | On upgrade, open items with the same entity, rule, and day merge into the oldest: counts summed, change lists joined, the newest severity and last seen kept, the others closed with reason `merged` and a link to the item they joined. Each merge is audited (`alert.merge`, with the item ids). Closed items are not touched | One-time cleanup of the backlog the old rule made, with a trail | Leave them (the queue stays flooded) |

### Learning period

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 6 | A new agent | "New agent" fires once per agent (as today: the standing review item) | Someone should see a new agent | Silent |
| 7 | Its first days | For the first **14 days** after an agent is first seen (setting `agents.learning_days`, 0 to 60), its "changed" alerts are silent: the changes are still recorded and shown on Agents and the person page, and still build the baseline, but raise no item and send nothing. Personal account, blocked or failed calls, and sensitive data are not silenced: they are about what happened, not about change | A baseline needs history; the first two weeks are all "new" | Silence everything (misses a personal account on day one) |
| 8 | Built-in Claude Code tools | Never raise "changed" on their own. **Built-in means any tool name without the `mcp__` prefix** (owner, 2026-11-03): Claude Code adds built-ins with its updates (ToolSearch and SubagentHandback came that way), and a fixed list would alert every user at once after each release. MCP tools (`mcp__<server>__<tool>`) and MCP servers are what raise "changed". Built-in first uses are still listed on Agents and the person page | A built-in tool is the product working; what an agent can newly reach is an MCP server or tool | A fixed list of built-ins (alerts everyone after each Claude Code release) |

### Severity per AI watch rule

| # | Rule | Severity | Alerts |
|---|---|---|---|
| 9 | Built-in tool first used | info | No item (row 8); listed on Agents |
| 10 | New MCP server or MCP tool | medium | Yes |
| 11 | Personal Claude account on a company device (an account email outside the organization domains in Identities) | medium | Yes, once per account and device |
| 12 | Bulk blocked or failed tool calls (10 or more in an hour for one agent by default; setting `agents.blocked_burst`) | high | Yes |
| 13 | Sensitive data to AI | high | Yes (as today) |
| 14 | Busy hour (3 times the usual peak) | medium | Yes, outside the learning period |
| 15 | Source gap | as set on the source (today medium) | Yes; the Alerts list shows its severity badge like every other item |

### Closing and muting

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 16 | Close reasons | **Expected**, **Approved**, **False positive**, **Resolved**. Note required for False positive; optional otherwise. Stored items keep their old reason; they are shown as Resolved (true positive), Expected (benign or expected), False positive, and Resolved with the note (needs follow-up) | Plain words for the decisions people make on AI items | Keep ADR-0037's four |
| 17 | Approved | Also marks what the item is about as reviewed: the agent (its standing review item closes), the MCP server (allowlist, Approved), or the AI service (catalog, Approved). The extra change is audited as its own action (`ai.review`) next to `alert.close` | One click for the common case: "yes, that is fine" | Two steps |
| 18 | Mute similar | 7 or 30 days (was 1 to 30), admins only (unchanged). New items with the same entity and rule close themselves with reason "Muted until <date>" and are audited | Two choices cover the cases seen | Free number of days |
| 19 | Bulk close | Select several items, one reason (and note when required) for all; each item is closed and audited on its own (`alert.close`, `bulk: true`) | Clearing a backlog without losing the trail | No bulk |

### What does not change

- Access: an item shows only to viewers who may read every source behind it (ADR-0037 row 19).
- Detection rules and schedules group the same way (row 1) but keep their own severities.
- Nothing is deleted: merged and closed items stay, with history.

## Consequences

- `alert_items` gains `entity`, `rule`, `day`, `last_seen`, and `changes` (JSON list) and a unique open index on (kind, entity, rule, day); additive migration. The `merged` close reason is added to the check constraint.
- AI watch raises with the entity and rule instead of a per-change `ref_id`; agent changes check the learning period and the built-in list first.
- Notifications drop from one per change to one per entity, rule, and day, plus severity rises.
- The Alerts page gets the summary strip, filters, and detail pane described in DESIGN.md (built after this ADR), using the full page width.
- Risk: a real change on a new agent's first days raises nothing. Mitigation: rows 7 and 11 to 13 keep the alerts that matter firing, and every change is still listed on Agents and the person page.

## Threats

| ID | Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|---|
| T-new1 | An attacker adds an MCP server or tool on a new agent's first days to hide in the learning period | AML.T0053 (LLM plugin compromise), AML.T0051 (follow-on prompt injection through the tool) | T1176 | With Q3 answered as proposed, new MCP servers and tools still alert while an agent is learning; only built-in tools and busy hours are silent. Every change is still listed on Agents and the person page |
| T-new2 | Alert fatigue hides a real event among repeats | n/a | n/a | Rows 1 to 4: one item per entity, rule, and day; a severity rise notifies again; mute is admins only and time-limited |
| T-new3 | "Approved" used to clear a risky agent or service in one click | n/a | T1562 (impair defenses) | Approved is audited as `alert.close` and `ai.review` with the user id; Auditors can read both; reopen is allowed |

## Owner answers (2026-11-03 19:38)

1. Day boundary: the install's time zone, UTC when unset.
2. Built-in tools: no fixed list; any tool without the `mcp__` prefix is built-in (row 8).
3. A new MCP server or MCP tool still alerts during a new agent's learning period. Only built-in tools and busy hours are silent while learning.
4. "Needs follow-up" is dropped; stored items with it show as Resolved with their note.
5. Bulk blocked calls: 10 per hour per agent by default, configurable (`agents.blocked_burst`).
