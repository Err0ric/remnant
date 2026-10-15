# ADR-0016: Investigation: one search bar, facets, suspicious presets, entity risk, investigator

Status: **Accepted** 2026-10-14 (project owner asked for all of it to be built). Recorded as SPEC D42; threats T37 and T38.

## Context

Search has three tabs (Simple, Ask in plain English, SQL). Analysts coming from Datadog, Splunk, or Sentinel expect one bar that takes either syntax or plain English, a field sidebar with counts to click, ready-made "show me the suspicious stuff" filters, a ranked list of risky users and addresses, and a picture of how one entity connects to everything it touched. All of it can be built on the deterministic engine; none of it needs a model to run.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Search bar | Tabs become **Search** and **SQL**. The Search bar has an **AI** toggle (a sparkle icon, accent color, labelled "Ask in plain English" for screen readers). Off: Simple syntax, runs on Enter. On: the text goes to Ask; the generated SQL is shown with **Run**; nothing runs until clicked (CLAUDE.md rule 4). Auditors get no toggle. The last mode is remembered per browser | One place to type; the AI path stays visibly separate and approve-to-run | Auto-run like some vendors (breaks rule 4) |
| 2 | Facets | A sidebar beside results: source, host (`device_hostname`), user, source IP, destination host, severity, status, class, parse status; top 10 values with counts for the current search and range. `POST /api/search/facets` wraps the already-guarded query as a subquery in one `UNION ALL` of fixed `GROUP BY`s, on the caller's `events` view, 10 s timeout, audited `query.facets`. In Search mode a click adds `field:"value"` (Alt-click excludes); in SQL mode counts are read-only | The fastest way to narrow down; same guard and scope as the query itself | Client-side counts (only the page of rows, misleading) |
| 3 | Suspicious presets | `backend/app/content/presets/suspicious.yaml`: named Simple-syntax searches (failed sign-ins, lockouts, privileged group changes, new admin accounts, sudo to root, off-hours sign-ins, firewall denies, AI service not approved, MCP tool errors). Shown as a **Suspicious** menu on Search; picking one fills the bar (editable, visible) | Transparent and editable, unlike an opaque "risk" filter | Hidden heuristics |
| 4 | Entity risk | **Investigate** page (nav, Investigate group, replacing the "Investigations: Later" placeholder): users, source IPs, and hosts ranked by rule matches in the range. Score = 10 per critical, 5 high, 2 medium, 1 low or informational match, plus 3 per flagged schedule run that names them in its sample. Computed per request from `rule_matches` joined to events in the caller's view | Datadog-style "most active entities", explainable (the score shows its parts) | Stored, background-computed scores (stale, harder to scope per user) |
| 5 | Investigator graph | Lanes, not a free-form graph (the data-access lane layout the owner preferred): labeled columns of cards, left to right. Entity mode: **Entity** → **Sources** → **Activities** (OCSF class plus `message`) → **Targets** (destination hosts and IPs, target users). AI flow mode for a user or an MCP server: **People** → **AI clients** → **Tools and MCP servers** → **Destinations** (AI services, URL hosts). Each card shows event count and matched rule count, with badges (Not approved, sensitive data, high or critical matches). Clicking a card highlights its connected path and opens a detail panel with a link to Search. At most 60 cards (largest first, "N more" per lane) | Readable at a glance, stable positions, every card one click from its events | A force-directed graph (moves around, harder to read) |
| 6 | Rendering | Plain SVG laid out in columns by depth, text nodes only, no graph library | Small, predictable, CSP-safe; values are attacker-controlled strings | A canvas graph library |
| 7 | Access | Every number on these surfaces comes from the caller's per-session `events` view (rule 13); rule matches outside it are not counted | Same rule as everywhere else | |

## Consequences

- New API: `/api/search/facets`, `/api/entities/risk`, `/api/entities/graph`. New UI: AI toggle, facet sidebar, Suspicious menu, Investigate page.
- The Ask tab disappears as a tab; `/ask` still opens Search with the toggle on.
- Facets cost one extra query per search; it runs after the results and can be collapsed (the choice is remembered).
- Not a model feature: no ATLAS impact beyond Ask, which is unchanged behind the toggle.

## Threats

| ID | Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|---|
| T37 | Facet, risk, or graph queries used to read sources outside the caller's groups, or to slow the engine | n/a | T1213, T1499 | Server-built SQL over the caller's `events` view only; guarded subquery; fixed columns; timeouts and node caps |
| T38 | Attacker-controlled values in node labels or facet values inject markup | n/a | T1189 (analogous) | Text nodes only, SVG `<text>` content set as text; CSP unchanged |

## Revision 2026-10-15

After owner review, row 5 is drawn closer to the data-access lane layout the owner preferred: each lane holds titled group boxes (cards carry a `group`), links are right-angled and share a trunk between lanes, the canvas is dotted, cards off the selected path fade, and the selected card opens in a side panel. Investigations opens on an Investigate picker and a Most active table; picking an entity gives the graph the full width. See SPEC D48.
