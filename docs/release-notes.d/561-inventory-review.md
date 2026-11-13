### Design: review AI items in the Inventory (2026-11-13)

- Console redesign, build row 10 (ADR-0052 section 3.3). AI usage > Inventory has one filter bar: Active or Excluded, Type (AI services, Agents, MCP servers, Microsoft 365 apps), and Status. It opens on Unreviewed while something waits for a review, and on All when nothing does. The page header says how many wait ("3 to review").
- An administrator sets Approved or Not approved in the Status column of an AI service or MCP server. It is the same audited change as on the Services and MCP server lists; everyone else sees the status as text.
- The filters are in the address, and Export CSV and Export JSON now export what the Status filter shows (the export's audit row records it).
- The Review tab is unchanged for now.
- What you will notice: the Inventory opens on what still needs a review, with a Status filter.
- What changes for existing installs: nothing to do.
