### A clearer page for one agent session (2026-11-14)

- Agents > Sessions keeps the list on the left and opens the chosen session beside it. On a small window the session takes the page, with Back to sessions.
- The open session starts with its numbers for the whole session: requests, tool calls with how many failed or were blocked, tokens in and out (or "Not reported" when Claude Code telemetry sent none), files with how many were written outside the session's folder, and flags.
- Its steps show as Execution (every step in order, with its type: prompt, tool call, tool result, file access, or access) or Conversation (by turn, as before, with a line for what each prompt led to), all steps or only the flagged ones. The page says when a very long session shows only its first steps, and Show events in Logs opens the session's records.
- One line says that content is not collected: the page shows sizes and names only, as before.
- What you will notice: opening a session on Agents > Sessions shows it beside the list with its numbers at the top, and you can switch between every step in order and the session by turn.
- What changes for existing installs: nothing to do.
