### Agents: its own numbers in the header, a faster Sessions list, and a legend that adds up (2026-11-16)

- The Agents header now counts what the page is about: sessions, people, and tool calls for the time chosen, the same numbers as the tiles below it, instead of AI usage's count of services.
- The comparison line shows once, above the tiles; AI usage's line about new and no longer seen services is no longer repeated on Agents.
- Agents loads faster: the Sessions and Accounts tabs no longer wait on the whole AI usage answer (only the MCP servers tab reads it), and the Sessions list and session pages read only the Claude plugin's records instead of every source of the time chosen.
- On Agents, Needs attention counts not approved and unreviewed MCP servers from the same answer as the tiles, the same on every tab. The chips about services not approved and sensitive-data signals stay on AI usage, where they belong.
- In a session's timeline, the legend puts the three kinds of tool call (in the session, file access, access) under one "Tool calls" total, the same number as the Tool calls tile. Claude Code's own bookkeeping counts as Other, as it already did in the tiles.
- "Not reported" under Tokens stays on one line, and the timeline's "Access" is now called "Web or MCP access".
- The Sessions card has one line that adds its list up to the Sessions tile: listed, empty and hidden, and sessions seen only in Claude Code telemetry. With nothing in the time chosen it says so for that time, and offers the plugin download only when there are no sessions at all.
- Everything on Agents now covers exactly the time you pick: 1 hour is an hour, not a day, and a custom range is that range. The header, the tiles, Needs attention, the Sessions list, Accounts, and the MCP servers table all agree; Needs attention counts the MCP servers the table lists. Placeholder names such as "custom" are no longer counted as an unreviewed MCP server.
- For a range longer than 90 days, Agents shows its last 90 days and says so under the time control.
- When there are more than 100 sessions, the Sessions card says it shows the newest 100 of how many.
- MCP servers with the same number of calls keep the same order on every load.
- What you will notice: the Agents header shows sessions, people, and tool calls, the Sessions list loads faster and says how it adds up to the tile, every number on Agents covers the time you pick, and the timeline's Tool calls match the tile.
- What changes for existing installs: nothing to do.
