### Design: AI usage has no Review tab; its settings are under Settings (2026-11-13)

- Console redesign (ADR-0052 section 3.3; owner, 2026-11-13). Reviewing AI services and MCP servers is done in AI usage > Inventory, with its Status filter. The Review tab is gone, and its old address opens the Inventory, on Unreviewed while something waits for a review.
- What the tab held is under Settings > AI > AI watch and catalog, for administrators as before: what AI Watch alerts on, the MCP server rules, and the catalog of AI services.
- What you will notice: AI usage has three tabs (Services, People, Inventory); administrators find the AI watch settings under Settings.
- What changes for existing installs: nothing to do.
