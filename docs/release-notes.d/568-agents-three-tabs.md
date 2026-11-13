### Design: Agents has three tabs (2026-11-13)

- Console redesign, build row 11 (ADR-0052 section 3.3; owner, 2026-11-13). Agents has Sessions, MCP servers, and Accounts. The numbers of the old Overview tab (sessions, people, tool calls, failed calls, not-approved MCP servers in use, devices delivering late) are a strip at the top of Sessions.
- The Tools tab is gone: on MCP servers every server's row opens to its figures (people, devices, calls, failures, first and last seen), and one Built-in row opens to the tools Claude Code has built in (Bash, Read, Edit and others), one by one.
- The strip, the sessions list, and the tool rows follow the page's time choice in whole days back from now: 1 hour and 24 hours show the last day, and Custom the days since its start (30 at most).
- Old addresses still open: Overview opens Sessions, and Tools opens MCP servers.
- What you will notice: two fewer tabs on Agents, the numbers above the sessions, and an arrow on each MCP server row.
- What changes for existing installs: nothing to do.
