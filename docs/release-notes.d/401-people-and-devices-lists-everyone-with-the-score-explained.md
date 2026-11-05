### People and devices lists everyone, with the score explained (2026-11-03)

- **Investigate > People & devices** lists every user, IP address, and host seen in the range, not only those a detection rule matched. Ties go to the busier one, so the list is never empty while there is data.
- The score now also counts failed sign-ins, risky inbox rules and app consents (Microsoft 365), AI watch flags (personal Claude account, unreviewed AI service, new MCP server, blocked tool calls), attack hits from outside, and alerts about them. Each has its own column; hover a score to see its parts.
- What changes for existing installs: nothing to do. Rankings may change order now that more signals count.
