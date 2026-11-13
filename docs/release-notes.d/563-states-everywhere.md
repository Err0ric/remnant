### Design: the same loading and empty states on every page (2026-11-13)

- Console redesign, build row 15, first part (ADR-0052, DESIGN.md 6.0). The pages that still showed a grey block or "Loading…" while loading now hold the place of their rows (AI usage, Agents, People & devices, Microsoft 365, Logs panels, Audit log, Settings pages). Empty lists are left-aligned at the top with at most two lines, in the same words as before.
- Two texts are shorter: Agents > Sessions says "Pick a session.", and Users no longer says the install runs without sign-in (it has not since sign-in became required).
- Not in this part: removing the paragraphs that explain a page (the help text sweeps).
- What you will notice: empty lists read from the top left instead of the middle, and pages keep their shape while loading.
- What changes for existing installs: nothing to do.
