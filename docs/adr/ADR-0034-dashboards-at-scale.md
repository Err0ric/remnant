# ADR-0034: Dashboards that scale past a handful of panels

Status: **Accepted** 2026-10-22 (project owner), with Overview option (b). From install finding F47. Recorded as SPEC D96.

## Context

A real install with Microsoft 365, endpoint agents, and AI usage will have 20 or more schedules. Today (SPEC 5.5, D82, D89):

| Part | Today |
|---|---|
| Panel | One per visible schedule; width a third, half, or full; table or bars |
| Headline | Row count of the last run |
| Layout | One flat grid, ordered by schedule |
| Dashboards | One per viewer: their own schedules, shared ones, all for admins. No dashboard object |
| Flags | A badge on the panel; nothing collects them |

Twenty panels of row counts in one grid is a list, not a dashboard: the flagged ones are lost, a detection-style search wastes a third of the width on an empty table, and "rows" is rarely the number anyone wants ("devices", "failed sign-ins").

## Decision (proposed)

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | Headline value | Per panel: **row count** (default), **sum of** a column, **count distinct** of a column, or **first row** column; plus a label ("devices", "failed sign-ins"). Computed at run time over the full result (like today's `count(*)`), not the 500-row sample, and stored with the run so the sparkline can use it | The number on the card should be the answer, not the row count | Computing from the sample (wrong when results are larger) |
| 2 | Tile size | New size **tile**: headline, label, flag state, sparkline. No table. Zero with a flag set shows in `--ok` as a good zero ("0 password sprays") | Detection-style searches are mostly zero; zero is the good news | Table panels for everything |
| 3 | Needs attention | A strip at the top: panels whose latest run is flagged, newest first, with the flag reason and the headline. Hidden when nothing is flagged. **Acknowledge** clears an item until the next flagged run (per viewer for personal dashboards, per dashboard for shared ones), audited `dashboard.acknowledge` | Flags must be collected where people look first | A separate alerts page (another place to check) |
| 4 | Sections | Panels carry a **section** (free text, for example Identity, AI usage, Access) and an **order** number. The dashboard groups by section with headers, sections in order of their lowest panel order. Drag to reorder writes the order numbers | Twenty panels need structure; free text keeps it the owner's | Fixed categories |
| 5 | Dashboard object | New table `dashboards` (id, name, owner, visibility personal or shared, created and updated) and `dashboard_panels` (dashboard, schedule, section, order, size, view, headline, label). Panel settings move from `schedules` (D82 columns) to `dashboard_panels`; migration creates one dashboard per existing owner, "My dashboard", holding their schedules with today's settings | A panel can appear on more than one dashboard with different sizes; this changes SPEC 5.5's "no separate dashboard object" | Keeping settings on the schedule (one layout only) |
| 6 | Named dashboards | A viewer has any number ("Daily", "AI governance"); a picker in the page header; the last opened is remembered per user. Shared dashboards are visible to everyone, editable by the owner and admins | Different jobs, different screens | One dashboard per person |
| 7 | Landing | ADR-0031 unchanged: the landing page is the viewer's default dashboard (their first, or one they pick) when it has a panel | | |
| 8 | Query library | ADR-0033 "Add a pack" creates panels with section = the pack group, size from the query (`tile` when it has a flag and returns few rows, else `third`), and headline and label from the pack | A pack produces a ready layout | |
| 9 | Access | Unchanged rule: a panel the viewer cannot fully read (every source in the run's `sources_in_scope`) shows **Restricted** with no data, tiles and Needs attention items included. A shared dashboard can list panels a viewer may not read; they show Restricted rather than disappearing, so the layout is the same for everyone | SPEC 5.5 access rule | Hiding them (layouts that differ per viewer confuse shared review) |
| 10 | Audit | `dashboard.create`, `.update`, `.delete`, `.panel_add`, `.panel_update`, `.panel_remove`, `.acknowledge`, each with the user id | Rule 14 | |

### Overview's nav slot (owner question in F48)

| Option | What | Cost |
|---|---|---|
| (a) Keep Overview | As today: health cards, volume by source, recent detections | None; two places show health |
| (b) Fold into Health and the Dashboard (recommended, after this ADR) | Volume and last-seen by source move to Health > Sources (they are health). Recent detections are what row 3's Needs attention strip shows. The Dashboard's health strip (ADR-0031) links to Health. `/overview` redirects to Health > Sources. A new install with no panels lands on an empty Dashboard whose empty state offers Add a pack and the setup checklist | One page and one nav slot fewer; the empty-state work in `docs/ux-next-click.md` (d) |
| (c) Merged Home page | ADR-0031 option (b) | Superseded by (b) once dashboards have sections |

Accepted: (b), in the PR after the dashboard object lands, so nothing Overview shows is lost in between.

## Implementation notes (2026-10-22)

- The headline (kind, column, label) is a setting of the **schedule**, not of each panel: it says what the search measures, and each run stores one value, so a schedule on two dashboards shows the same number on both. Size, view, section, and position are per panel.
- Ordering is by **Earlier** and **Later** buttons in Edit layout (keyboard friendly), which write positions; drag is not built.
- The Overview fold (option b) is the next PR.

## Consequences

- One migration moves the D82 panel columns; schedules keep running unchanged.
- Runs store the headline value next to the row count; the sparkline uses it.
- Panel settings and the Needs attention strip are per dashboard; acknowledging on a shared dashboard clears it for its viewers, and that is audited.
- Work: about three PRs (dashboard object and migration; headline, tile, sections; Needs attention and acknowledge), then ADR-0035 builds on it.

## ATLAS / ATT&CK

No AI surface change: no model call on the dashboard, and headline values are deterministic SQL over the caller's view.
