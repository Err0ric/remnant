### Design: the Agents sessions filters use the shared filter bar (2026-11-13)

- Console redesign, build row 7, first part (ADR-0052, DESIGN.md 6.0). On Agents > Sessions the Person, Machine, and Tool filters and the "Has flags" box are now one filter bar like the one on Alerts: each reads "Machine ws-0042", Flags is Any or Flagged, the count of sessions is on the right, and Reset appears while something is filtered.
- The filters are in the address, next to the open session, so a filtered list can be bookmarked or sent.
- Not in this part: the time controls of Logs, AI usage, Agents, Health, and People & devices. They keep today's choices until the owner decides what Custom and "All time" become.
- What you will notice: the session filters look like the Alerts filters, with a Reset link.
- What changes for existing installs: nothing to do.
