### A timeline bar for each agent session (2026-11-14)

- An open session on Agents > Sessions now shows a bar of its steps from start to end, one segment per step in order, colored by kind: prompt, tool call, tool result, file access, and access (web and MCP). A failed step has a small red mark above it.
- The legend under the bar names each kind with its count for the whole session. Choosing a segment takes you to that step in the list below. With Flagged only, steps that are not flagged are dimmed on the bar.
- For a very long session the bar draws the first 2,000 steps and says so; the counts still cover the whole session.
- Charts gain five calm series colors, checked for contrast in both themes; they are never used for severity or warnings.
- What you will notice: an open session on Agents > Sessions has a colored bar of its steps under its numbers, with a legend you can read without the colors.
- What changes for existing installs: nothing to do.
