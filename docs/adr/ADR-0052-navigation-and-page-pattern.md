# ADR-0052: Navigation and page pattern built around top tasks

Status: **Accepted** 2026-11-12 by the owner (decisions D246, D247, D248). Written 2026-11-11 by the design chat and checked by the owner against main 8dad512; mockups approved 2026-11-11. With the acceptance the owner set panel titles to 14px at 600, as the type scale in 3.10 says (the draft's 3.8 said 13px).

Supersedes: the Dashboard Health banner in D243 (owner decision 2026-11-11), see 3.9. The D243 restricted note stays.

Amends: ADR-0038 edit 10 (rail lists sub-pages), D199 (tree guide lines), D70 (rail order), DESIGN.md sections 2, 3, 4, 5, 6.2a, 6.2b, 6.2e, 6.3, 7, 8, 11, and CLAUDE.md section 3 (which still says "tokens.css from DESIGN.md section 9"; it becomes "sections 2 and 11").

Mockups: "Remnant console redesign: 4 key screens" design canvas, five artboards (Dashboard, Alerts list and detail, full alert page per D229 option B, person page, States). Owner approved screens 1 to 4 on 2026-11-11. Synthetic data only.

The mockup images are not in the repository (owner, 2026-11-12): the build follows this ADR and `docs/DESIGN.md`. DESIGN.md was edited to this ADR on acceptance; the app changes follow in the build's own PRs, tokens and fonts first.

## 1. Context

The rail shows about 30 links at equal weight because every page lists its sub-pages, and pages repeat structure in their own tabs (Alerts 5 tabs, Health 8). Pages show everything at once with long explanatory text, have no clear primary action, and handle tabs, filters, and empty states differently. An analyst cannot tell where to look first.

## 2. Top tasks (owner confirmed 2026-11-11)

| Rank | Job | Frequency |
|---|---|---|
| 1 | Know in 10 seconds if anything needs me | Several times a day |
| 2 | Work the alert queue | Daily |
| 3 | Investigate one alert, person, device, or address | As needed |
| 4 | See and govern AI use | Weekly, plus on alerts |
| 5 | Answer a specific question from logs | Ad hoc |
| 6 | Confirm I am not blind | Daily glance |
| 7 | Set up and tune | Rare |
| 8 | Report upward (monthly report, D67) | Monthly |

The Dashboard's Needs you list includes AI Watch items (owner, 2026-11-11).

## 3. Decision

### 3.1 Navigation rules

| Rule | Detail |
|---|---|
| The rail lists pages only | No sub-pages, no guide lines. The 2px current-page bar and weight change from D199 stay |
| Tabs are different objects | States of one object (Open, Closed, Muted; Unreviewed, Approved) are filters |
| At most 5 tabs per page | No nested tabs |
| One work queue per kind | Alerts is the only alert queue. AI usage > Inventory is the only governance queue |
| Role scoping | Rail entries, tabs, and Settings sections a role cannot use are not shown |

### 3.2 Rail (10 entries)

| Group | Page | Tabs |
|---|---|---|
| Monitor | Dashboard | none (dashboard picker in the header) |
| Monitor | Alerts (open count) | Queue, Rules, Schedules |
| Investigate | Logs | Search, Saved searches |
| Investigate | Ask AI | none |
| Investigate | People & devices | People, Devices, Saved investigations |
| AI | AI usage | Services, People, Inventory |
| AI | Agents | Sessions, MCP servers, Accounts |
| Pinned, lower weight | Health (status dot only when something is wrong) | Sources, Collectors, Delivery |
| Pinned, lower weight | Reports | none |
| Pinned, lower weight | Settings | own sub-nav (D70) plus System; only sections the role can use |

The full alert page (D229) and entity pages have no rail entry. They carry a breadcrumb and are reached from Alerts, any EntityLink, and Ctrl+K.

### 3.3 Page moves

| Current | Action | Destination |
|---|---|---|
| Alerts: Open, Closed, Muted | Merge | Alerts > Queue, State filter (default Open) |
| Alerts: Rules | Keep | Alerts > Rules |
| Alerts: Schedules | Keep | Alerts > Schedules. A schedule targets a saved search or a detection rule and has its own delivery log |
| Saved searches (rail) | Move | Logs > Saved searches, with a Scheduled column linking to Alerts > Schedules |
| "Connected apps" group | Remove | n/a |
| Microsoft 365 Overview | Move (amended by D249, owner 2026-11-13; was Remove) | The top of the Logs Sign-ins view; the headline numbers are also in the Dashboard Identity section |
| Microsoft 365 Sign-ins, Mail, Admin | Move | Logs Views menu (preset source, columns, filters) and a Microsoft 365 section on the person page |
| Microsoft 365 Apps | Move | AI usage > Inventory, Type filter |
| AI usage: Inventory | Keep | Governance register of four types (AI services, agents, MCP servers, Microsoft 365 apps), review status per item |
| AI usage: Review | Merge | Inventory, Status filter. Opens on Unreviewed; when nothing is unreviewed it opens on All with "0 to review" in the header. The "N to review" count links here |
| Agents: Overview | Remove | KPI strip above Sessions |
| Agents: Tools | Merge | Agents > MCP servers (tools in the expanded row) |
| Health: Sources, Enrichment feeds | Merge | Health > Sources, Type filter |
| Health: Endpoint agents, Watched devices | Merge | Health > Collectors |
| Health: Page rollups, Speed | Move | Settings > System |
| Reports (D67) | New | Pinned rail entry; Table template, primary action Generate report |
| Audit log | Keep | Settings > Records; an Auditor sees only this section |

Agents > MCP servers shows activity (what ran, where). Inventory shows the register (status, review history). Each row links to the other.

### 3.4 URLs

Every old address redirects to its new one with replace (not added to history), keeping filter state in the fragment, as `/search` does today (DESIGN 6.1).

### 3.5 Page layout: four zones

| Zone | Height | Contents | Rules |
|---|---|---|---|
| 1. Header | 44px | Page title, optional count. Right: one filled primary button where one exists, up to two secondary, then an overflow menu | Title is the page name, never the group name. One shared `PageHeader` component, landed first |
| 2. Tabs | 36px | That page's tabs only | Omitted when the page has none |
| 3. Filter bar | 40px | Time, State, facets, text box. Right: count, Columns | One row; extras under "More filters" |
| 4. Body | rest | One of the five templates | First data row within 200px of the top bar |

### 3.6 Body templates

| Template | Shape | Pages |
|---|---|---|
| Board | Needs you list, then sections of KPI strip plus chart and table | Dashboard |
| Table | Optional KPI strip that filters, then one table with inline row expansion | Logs, Rules, Schedules, Saved searches, People & devices, AI usage (all tabs), MCP servers, Accounts, Health, Reports |
| List-detail | List (5 parts) and sticky detail pane (7 parts) | Alerts > Queue, Agents > Sessions |
| Record | Breadcrumb, title, one-sentence summary, KPI row, main column (2 parts) and side column (1 part) | Full alert page, person, device, address, AI service |
| Form | Section list and form, sticky save bar | Settings |

Ask AI is the one exception (a thread, DESIGN 6.1).

### 3.7 Standards

| Area | Standard |
|---|---|
| Primary action | One filled button per page, only where one exists. Alerts > Queue: Close, in the detail pane. Full alert page: Close alert. Person page: Open in Logs. Reports: Generate report. Dashboard, Health, Agents > Sessions: none |
| Tabs | Different objects only. Max 5. Each has a URL. Count badge only on a queue that needs action. Last tab remembered per browser |
| Filters | Fixed order: Time, State, facets, text. State in the URL. Reset appears only when filters differ from the default. Clicking a KPI or a value adds a filter |
| Time presets | 1 hour, 24 hours, 7 days, 30 days, Custom. One time control per page |
| Counts | "N of M": M counts only rows the caller can read. Never a count of restricted items (D243) |
| Loading | Skeleton rows in the final layout, no layout shift. On refresh the old data stays visible. Spinners only inside buttons. Errors inline with Retry |
| Query cancel | "Still working" with Cancel after 10 s is a build item. The Builder confirms server-side query cancel exists; the button ships only when it does |
| Help text | Zero paragraphs on a page. What the page is: delete. How a number is counted: a popover on the label. What to do next: a button. Settings fields keep one line under the input. "Computed from" lines stay as one muted line. Allowed: one muted "what this shows" line only where a page would be unclear on a fresh install |
| State notices | Not help text and never removed: masking ("Names hidden"), the D243 restricted note, D236 pause and stop notices, ADR-0050 template missing. One line, in the body above the content it affects |

Empty states: left-aligned at the top of the body, at most two lines and one action, no illustrations.

| Kind | Example | Action |
|---|---|---|
| Not set up | "Needs a Microsoft 365 source" | Add a source |
| Filters hide everything | "No alerts match these filters." | Reset filters |
| Good zero | "No open alerts. Checked 2 min ago." in normal text | none |
| Default filter is empty | Inventory opens on All with "0 to review" | none |
| No permission | "Restricted" | never shown as zero |

### 3.8 DESIGN.md changes

| Section | Current | Change |
|---|---|---|
| 4 | Page padding 20px (Logs) or 24px (Investigation) | 20px everywhere |
| 4 | Titles `text-lg` or `text-xl` by page type | `text-lg` on every page; `text-xl` only on Record pages |
| 5 | Rail 240px, four collapsible groups, sub-pages listed on guide lines | Rail 208px, three labeled groups plus a pinned cluster, pages only, rows 32px (28px in Compact), no collapse state to remember |
| 5 | Area title ("Investigate") with tabs that repeat the rail | Title is the page; tabs are the page's own |
| 5, 7 | Command bar of text buttons, primary in accent text | Removed. Header actions with one filled primary (section 3.5) |
| 6.2e | Alerts summary strip above the list | Removed. Counts move into the State and facet filters. The restricted-sources note stays, at the foot of the list |
| 6.2e | Detail pane holds everything | Pane holds what fired, why, people and devices, the compact Triage card, next steps, and actions. Evidence pack, reasons, cited events, pivots, and history move to the full alert page (D229) |
| 6.3 | Dashboard: Health banner at the top, Sources line at the bottom | One Needs you list per 3.9. Sources healthy is a KPI tile. A Detections section is specified in DESIGN.md 6.3 |
| 2, 3, 4, 11 | Current tokens, Source Sans 3 and Source Code Pro | Replaced in full by section 3.10 (Graphite), which includes `--warn-tint` |
| 6.3 | Long per-page prose | Replaced by the template (3.6) plus a per-page table where a page needs one |
| 7 | `PanelTitle`: 12px, upper case, wide tracking | 14px, 600, sentence case |
| 7 | Severity badges all tinted | Critical and High solid; Medium, Low, Info a dot plus label; Low neutral (3.10) |
| 7 | AI status "Not approved" in the critical severity color | Hollow dot outlined in `--warn`, plus the label. Severity colors stay for severity only |
| 8 | "Labeled nav in four groups, sub-pages listed" | "Labeled nav, pages only; tabs in the page" |

Change pills keep the DESIGN arrow glyph (owner, 2026-11-11).

### 3.9 Needs you list (supersedes the D243 Health banner)

One list on the Dashboard holds everything that needs the viewer.

| Order | Rows | Look |
|---|---|---|
| 1 | Blind rows: source down, detection paused or stopped (D236), template missing (ADR-0050) | Pinned first. `--warn-tint` row with a 2px `--warn` bar on its left edge and an outlined `--warn` badge. Never visually equal to an alert row, and never a severity color |
| 2 | High and Critical alerts, newest first | Severity badge |
| 3 | Other alerts, newest first | Severity badge |
| 4 | AI review items (link to AI usage > Inventory) | Severity badge, kind "AI review" |

- Blind rows are never folded under "N more"; the cap of rows applies to orders 2 to 4.
- The D243 restricted note stays at the foot of the list, with no count.
- The separate Health banner and the bottom Sources line are removed; a blind state is said once, here, and on Health.

### 3.10 Visual direction: Graphite (owner pick, 2026-11-11)

Replaces DESIGN.md sections 2, 3, 4, and 11 and `tokens.css`. Section 9 (Accessibility baseline) is unchanged and is the bar these values were checked against. Mockups: the five step 4 artboards, restyled; the three directions compared are on the canvas page "Visual direction (step 4b)".

Direction in one line: flat, quiet, and border-led. Cards are outlined regions on the page, not filled boxes; the only filled color on a calm screen is a Critical or High badge and the tinted blind row.

Owner decisions: A Graphite; solid filled badges for Critical and High only; Medium and Low keep the dot; Low becomes neutral; Geist and Geist Mono replace Source Sans 3 and Source Code Pro (owner approval of the new dependency; the Builder confirms the OFL license, the `@fontsource` packages, and the 14-day rule before adding them); `--accent` dark is `#3A68E0`; Comfortable is the default density for every role and Compact is a per-user choice, remembered in the browser (this replaces the width-based default in ADR-0038 edit 10); Unreviewed is an accent-outlined dot.

#### Section 2 replacement: themes and palette

Dark is the default. Light is a first-class theme with its own values. Respect `prefers-color-scheme` on first load, then the user's choice.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0E1013` | `#FAFAFB` | Page background |
| `--top` | `#0A0B0E` | `#16181D` | Top bar (dark in both themes) |
| `--nav` | `#0E1013` | `#FAFAFB` | Left navigation |
| `--surface` | `#0E1013` | `#FFFFFF` | Cards, tables, panels. Same as the page in dark: borders define a card, not a fill |
| `--surface-head` | `#13161A` | `#F4F5F7` | Hover fill, header strips where one is needed |
| `--surface-expand` | `#14171C` | `#F5F8FE` | Inline row expansion, the Triage card |
| `--inset` | `#0A0B0E` | `#F1F2F4` | SQL editor, raw log blocks, text inputs |
| `--border` | `#1F242B` | `#E4E6EA` | 1px borders and row dividers |
| `--border-strong` | `#2E353F` | `#C9CDD4` | Secondary buttons, facet buttons, segmented controls (controls that carry a text label) |
| `--border-control` | `#5F6977` | `#808896` | Text inputs and checkboxes: the edge is the only cue, so it meets 3:1 on `--surface`, `--inset`, and a selected row |
| `--text` | `#E4E7EC` | `#16181D` | Primary text and data |
| `--text-secondary` | `#9BA3B0` | `#4A5160` | Labels, metadata, breadcrumbs |
| `--text-muted` | `#7F8896` | `#636D7D` | Hints, group labels, NULL glyph, the Low and Info dot |
| `--series-neutral` | `#646D7D` | `#858D9C` | Second neutral chart series |
| `--accent` | `#3A68E0` | `#2B5BD7` | Primary button fill |
| `--on-accent` | `#FFFFFF` | `#FFFFFF` | Text on the primary button |
| `--accent-text` | `#7EA2FF` | `#2452C9` | Links, current nav item, current tab underline, focus ring |
| `--focus-ring-top` | `#7EA2FF` | `#7EA2FF` | Focus ring inside the top bar, which is dark in both themes |
| `--accent-subtle` | `rgba(91,140,255,0.14)` | `#E9EFFD` | Pressed segment, selected cited ID chip |
| `--row-selected` | `rgba(91,140,255,0.09)` | `#EFF3FE` | Selected or expanded row |
| `--warn-tint` | `rgba(232,188,98,0.08)` | `#FCF5E4` | Blind row in Needs you, blind state notices. Never an alert |

Severity (alerts, Sigma levels, OCSF `severity_id` only). Always a text label, never color alone.

| Level | Form | Dark | Light | OCSF `severity_id` |
|---|---|---|---|---|
| Critical | Solid badge | `#F2647A` fill, `#1F0409` text | `#B4162F` fill, `#FFFFFF` text | 5, 6 |
| High | Solid badge | `#F08A3C` fill, `#1A0E03` text | `#B8500A` fill, `#FFFFFF` text | 4 |
| Medium | 7px square dot, then the label in `--text` | dot `#F0C46A` | dot `#8A5300` | 3 |
| Low | Dot, then the label | dot `--text-muted` (neutral, no longer blue) | dot `--text-muted` | 2 |
| Info | Dot, then the label | dot `--text-muted` | dot `--text-muted` | 1 |

Token names in `tokens.css`: `--sev-c-solid`, `--sev-c-on`, `--sev-h-solid`, `--sev-h-on`, `--sev-m-dot`. The old tinted pairs (`--sev-<level>-bg` / `-text`) are removed, including the blue Low pair. The rail and bell counts use the High solid pair.

Semantic

| Token | Dark | Light | Use |
|---|---|---|---|
| `--ok` | `#58C29A` | `#1C7656` | Healthy, passed, a good zero |
| `--warn` | `#E8BC62` | `#855100` | Blind states, partial parse, unverified citation, Not approved outline |
| `--danger` | `#F28B9B` | `#B0152E` | Destructive confirm, gate block, errors |
| `--info-bg` | `#1A1E24` | `#EDEFF2` | Event ID chip fill |
| `--info-tx` | `#9BA3B0` | `#3F4654` | Event ID chip text |
| `--local-bg` / `--local-tx` | `rgba(63,182,139,0.16)` / `#7FD3B2` | `#E3F4EF` / `#1F6B57` | Local only badge; Approved dot uses the text value |
| `--cloud-bg` / `--cloud-tx` | `rgba(167,139,250,0.16)` / `#B9A2FB` | `#F1EBFE` / `#6D28D9` | Cloud provider badge. The only purple in the app |

AI status: Approved is a dot in `--local-tx`; Unreviewed is a hollow dot outlined in `--accent-text`, so it stands apart from Low and Info; Not approved is a hollow dot outlined in `--warn`. Each with its label. Never a severity color.

#### Section 3 replacement: typography

| Role | Font | Notes |
|---|---|---|
| UI | Geist | Self-hosted via `@fontsource` (400, 500, 600, 700). Tabular numbers everywhere |
| Data | Geist Mono | 400, 500. Every log field value, IP, event ID, SQL, raw line |

| Name | Comfortable (default) | Compact | Weight | Use |
|---|---|---|---|---|
| `text-xs` | 12 / 16 | 12 / 16 | 500 | Rail group labels, table headers, axis labels, change pills |
| `text-data` | 13 / 18 | 12 / 18 | 400 | Mono data in tables and chips |
| `text-base` | 14 / 20 | 13 / 18 | 400 | Default UI text, table text, buttons, inputs; panel titles at 600; rail items at 500 (600 when current) |
| `text-md` | 15 / 22 | 14 / 20 | 600 | Alert titles in lists and the pane, empty state headings |
| `text-lg` | 20 / 26 | 20 / 26 | 600 | Page title |
| `text-xl` | 22 / 28 | 22 / 28 | 600 | Page title on Record pages |
| `text-kpi` | 28 / 36 | 24 / 30 | 600 | KPI values |
| `text-kpi-lg` | 32 / 40 | 28 / 34 | 600 | Dashboard KPI values from 1500px wide |

The time format paragraph in section 3 is unchanged.

Density (owner, 2026-11-11): Comfortable is the default for every role, because users are internal and non-technical. Compact is a per-user choice in the user menu, remembered in the browser. There is no width-based default.

#### Section 4 replacement: spacing, shape, density

- 4px grid. Allowed: 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32.
- Radius: 6px cards, 5px controls, 3px solid badges, 2px dots. Nothing larger.
- Comfortable (default): table rows 34px, controls 32px (28px in the filter bar), rail rows 32px, tabs 36px. Compact: table rows 30px, controls 28px (26px in the filter bar), rail rows 28px, tabs 34px.
- Page padding 20px on every page. Card padding 12 to 14px.
- Surfaces are flat: 1px `--border`, no fills in dark, white on `--bg` in light. No drop shadows except the command palette.
- Table headers have no fill: 12px at 500 in `--text-secondary` over a 1px divider.
- Charts: 1.5px lines, no area fill; the window before as a dashed `--text-muted` line. Stacked parts are separate lines with a printed legend. Top values stay horizontal bars.
- Transitions 120ms ease-out. `prefers-reduced-motion` disables them.

#### Section 11 replacement: token mapping

```css
:root, :root[data-theme="dark"] {
  --bg: #0E1013; --top: #0A0B0E; --nav: #0E1013; --surface: #0E1013; --surface-head: #13161A;
  --surface-expand: #14171C; --inset: #0A0B0E; --border: #1F242B; --border-strong: #2E353F;
  --border-control: #5F6977; --text: #E4E7EC; --text-secondary: #9BA3B0; --text-muted: #7F8896;
  --series-neutral: #646D7D; --accent: #3A68E0; --on-accent: #FFFFFF; --accent-text: #7EA2FF;
  --accent-subtle: rgba(91,140,255,0.14); --row-selected: rgba(91,140,255,0.09);
  --warn-tint: rgba(232,188,98,0.08); --ok: #58C29A; --warn: #E8BC62; --danger: #F28B9B;
  --info-bg: #1A1E24; --info-tx: #9BA3B0; --sev-c-solid: #F2647A; --sev-c-on: #1F0409;
  --sev-h-solid: #F08A3C; --sev-h-on: #1A0E03; --sev-m-dot: #F0C46A;
  --local-bg: rgba(63,182,139,0.16); --local-tx: #7FD3B2; --cloud-bg: rgba(167,139,250,0.16);
  --cloud-tx: #B9A2FB; --focus-ring-top: #7EA2FF;
}
:root[data-theme="light"] {
  --bg: #FAFAFB; --top: #16181D; --nav: #FAFAFB; --surface: #FFFFFF; --surface-head: #F4F5F7;
  --surface-expand: #F5F8FE; --inset: #F1F2F4; --border: #E4E6EA; --border-strong: #C9CDD4;
  --border-control: #808896; --text: #16181D; --text-secondary: #4A5160; --text-muted: #636D7D;
  --series-neutral: #858D9C; --accent: #2B5BD7; --on-accent: #FFFFFF; --accent-text: #2452C9;
  --accent-subtle: #E9EFFD; --row-selected: #EFF3FE; --warn-tint: #FCF5E4; --ok: #1C7656;
  --warn: #855100; --danger: #B0152E; --info-bg: #EDEFF2; --info-tx: #3F4654;
  --sev-c-solid: #B4162F; --sev-c-on: #FFFFFF; --sev-h-solid: #B8500A; --sev-h-on: #FFFFFF;
  --sev-m-dot: #8A5300; --local-bg: #E3F4EF; --local-tx: #1F6B57; --cloud-bg: #F1EBFE;
  --cloud-tx: #6D28D9; --focus-ring-top: #7EA2FF;
}
```

Aliases kept so existing components do not break: `--focus-ring` is `--accent-text`; `--panel-title` and `--section-text` are `--text`; `--section-bg` is `rgba(148,163,184,0.12)` dark and `#E6E9EE` light.

#### Contrast check against section 9 (WCAG AA)

160 pairs checked across both themes: every text token on every surface (page, card, hover, expansion, rail, inset, selected row, blind row), the accent on each, state colors, both solid badges, every dot, chips, the top bar, and chart series. Translucent tokens were composited over the surface first. Text needs 4.5:1; marks, dots, and control edges need 3:1. All 160 pass after these adjustments:

| Adjusted | From | To | Why |
|---|---|---|---|
| `--text-muted` dark | `#7C8593` | `#7F8896` | 4.48 on the blind row |
| `--text-muted` light | `#667080` | `#636D7D` | 4.47 on `--inset` |
| `--series-neutral` light | `#878F9E` | `#858D9C` | 2.98 on `--surface-head` |
| `--accent` dark | `#3F6FE8` | `#3A68E0` | White text on `#3F6FE8` is 4.52: a pass with no margin. Now 4.96. Accepted by the owner |
| New `--border-control` | n/a | `#5F6977` / `#808896` | `--border-strong` is about 1.5:1, too faint for a text input or checkbox edge. The same gap exists in today's tokens. Light was `#868E9B` when accepted: 2.95 on `--inset` and 2.98 on a selected row (owner, 2026-11-12) |
| New `--focus-ring-top` | n/a | `#7EA2FF` in both themes | The light theme's focus ring `#2452C9` is 2.64 on the dark top bar. Focus inside the top bar uses this token: 7.96 dark, 7.19 light (owner, 2026-11-12) |

| Pair | Needs | Dark | Light |
|---|---|---|---|
| text-muted on surface | 4.5 | 5.32 | 5.23 |
| text-muted on warn-tint | 4.5 | 4.66 | 4.81 |
| text-secondary on warn-tint | 4.5 | 6.57 | 7.33 |
| accent-text on surface | 4.5 | 7.71 | 6.72 |
| accent-text on warn-tint | 4.5 | 6.76 | 6.18 |
| warn on warn-tint | 4.5 | 9.38 | 6.09 |
| button text on accent fill | 4.5 | 4.96 | 5.87 |
| Critical badge text on Critical badge | 4.5 | 6.37 | 6.78 |
| High badge text on High badge | 4.5 | 7.59 | 5.01 |
| Medium dot on surface | 3.0 | 11.62 | 6.33 |
| Low dot on surface | 3.0 | 5.32 | 5.23 |
| Unreviewed dot outline (accent-text) on surface | 3.0 | 7.71 | 6.72 |
| input and checkbox edge on surface | 3.0 | 3.42 | 3.57 |
| input and checkbox edge on inset | 3.0 | 3.54 | 3.19 |
| input and checkbox edge on a selected row | 3.0 | 3.09 | 3.22 |
| focus ring on the top bar | 3.0 | 7.96 | 7.19 |
| event ID chip text on chip | 4.5 | 6.58 | 8.23 |

The Builder ports the check to `scripts/check-contrast.py` so CI fails when a token change breaks a pair. Built with redesign build row 1: the script holds the list of pairs, which now includes the two rows the owner added on 2026-11-12, and it also fails when `tokens.css` differs from DESIGN.md section 11. On the pressed fill (`--accent-subtle`) muted text is 4.47 in dark, so `globals.css` gives anything on that fill `--text-secondary` instead.

## 4. Consequences

| Good | Cost |
|---|---|
| Rail fits any screen without scrolling; the first two entries are jobs 1 and 2 | Sub-pages lose one-click access from the rail. Mitigation: last tab remembered per browser; Ctrl+K lists every tab under Navigate |
| New connectors (Okta, Google Workspace, CloudTrail) add Logs views, not nav groups | Microsoft 365 has no landing page; its summary exists only while the Dashboard Identity section is shown |
| Two queues with clear names | The Inventory Status filter and the Alerts State and Category filters are load-bearing and need tests |
| Every page reads the same way | Every page header is touched once, by the shared `PageHeader` PR |
| Less text on screen | A fresh install has less guidance. Mitigation: the "Not set up" empty state, Settings > Start here, and the one allowed "what this shows" line |

## 5. Security notes

- Role scoping of nav is display only. Every page and API keeps its own server-side permission check (no change).
- Redirects must not carry SQL or identifiers the viewer cannot read; they reuse the existing fragment rules.
- Counts never reveal restricted rows (D243).
- The full alert page shows model output. Existing rules hold: every statement cites event IDs, statements whose citation fails the check are removed and the removal is shown, log content is rendered as text (AML.T0051.001), and the model badge shows Local or Cloud (AML.T0057).
- No new AI path, so no new ATLAS or ATT&CK mapping.

## 6. Acceptance checks

- Rail shows at most 10 entries for an admin, fewer for other roles; no entry has children.
- No page has more than 5 tabs; the CI layout check counts them.
- Every page renders through `PageHeader`; at most one filled button per page.
- Every address in section 3.3 redirects and keeps its filters.
- An Auditor sees Reports and Settings > Records and nothing they cannot open.
- State notices in 3.7 still render on every page that had them.
- `scripts/check-contrast.py` passes all pairs in both themes; no component uses a hex value; no request for a Source font remains.
- A new user of any role sees Comfortable; choosing Compact survives a reload and applies on every page.
- Time presets are the same five on every page with a time control.
- With a source down and three High alerts open, the first Needs you row is the blind row, tinted, and it stays first at any row cap.
- Every state on the States artboard exists as a shared component and is used wherever that state occurs.
