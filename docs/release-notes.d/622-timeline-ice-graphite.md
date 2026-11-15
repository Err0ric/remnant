### Calmer colors for the session timeline (2026-11-14)

- The timeline bar on Agents > Sessions now uses two quiet colors and gray: prompts in ice (a light cyan), tool calls in graphite, tool results in gray.
- File access and access (web and MCP) are drawn with stripes, in graphite and ice: these are the steps that reach outside the session (a file, the web, or an MCP server). The stripes read without any color.
- A small tick under the bar marks every place where a step reached outside the session, also in a very long session where several steps share one part of the bar; the legend explains it.
- No color on the bar is one used elsewhere for health, warnings, severities, links, or the Cloud badge.
- What you will notice: the session timeline bar is ice, graphite, and gray, with stripes on file and web steps and a tick under the bar wherever a step reached outside the session.
- What changes for existing installs: nothing to do.
