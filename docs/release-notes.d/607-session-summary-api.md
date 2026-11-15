### One agent session in numbers, from the server (2026-11-14)

- New `GET /api/ai/sessions/{session_id}/summary`: for one Claude Code or Cowork session, its prompts, tool calls with how many failed or got no result, tokens in and out when Claude Code telemetry reported them for the session (otherwise empty, never 0), files touched and how many were written outside the session's folder, what the session's flags are read from, the length, and a count per step type. It counts the whole session, also past the 2,000 steps the steps list shows, and says when that list is cut.
- Each step of `GET /api/ai/sessions/{session_id}` now says its type: prompt, tool call, tool result, file access, access (web and MCP), or other. The server works it out from the hook record when it is read; nothing new is stored.
- Metadata only, as before. Without View people in AI usage the machine stands in for the person and the account, and each answer writes an audit row as opening a session does.
- What you will notice: nothing visible yet; the session page that uses it follows.
- What changes for existing installs: nothing to do.
