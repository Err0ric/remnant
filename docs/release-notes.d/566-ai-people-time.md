### Design: AI usage, Agents, and People & devices use the same five time choices (2026-11-13)

- Console redesign, build row 7, time controls, part 3 (ADR-0052 section 3.7; owner, 2026-11-13). The time filter of AI usage, Agents (all tabs but Overview), and People & devices is 1 hour, 24 hours, 7 days, 30 days, or Custom with a start and an end in your own time zone. "All time" is gone: Custom with no dates is everything kept.
- On AI usage and Agents the choice is in the address (`#time=30d`), so it can be bookmarked, with a Reset link when it is not the usual 7 days. A Custom range is compared against the period of the same length before it.
- On People & devices the choice stays with the page while you move from one person or device to the next. A person's AI activity and devices count whole days back from now, so with Custom they cover the days since its start (30 at most).
- Choosing Custom starts from the window you were looking at, with its start filled in. Clear the start to see everything kept.
- The time you chose stays when you move between the tabs of AI usage or Agents.
- The Alerts address now writes a Custom range as UTC times, as Logs does, so a link opens on the same moments for a reader in another time zone.
- What you will notice: five time buttons on these pages, and two date boxes for Custom.
- What changes for existing installs: nothing to do.
