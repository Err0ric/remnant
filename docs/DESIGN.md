# DESIGN BRIEF: Remnant

Product name is a working codename and is rendered from the `PRODUCT_NAME` constant (see `CLAUDE.md` section 2). Never typeset it by hand in a component.

**Direction (D24): "Workspace."** A polished commercial security console, closer to Microsoft Sentinel and Splunk in structure and to the best commercial consoles in readability than to a developer side project. Dark theme first with a complete light theme. Labeled navigation, clear page hierarchy, consistent components, inline detail. If a screen looks like a chat app, a marketing site, or a weekend project, it is wrong.

Reference mockups: the "Remnant Design Directions" canvas, second row (Search dark, Search light, Investigation view).

Tokens below are the contract. They land in `frontend/src/styles/tokens.css` and Tailwind reads from them. No component uses a hex value directly.

---

## 1. Principles

| Principle | In practice |
|---|---|
| Enterprise, not app-like | Full app chrome (top bar, labeled nav, breadcrumbs, command bar). No floating gimmicks, no oversized hero text |
| Readable first, dense second | 14px UI text, 13px data. Density toggles exist, but the default is comfortable to read for a whole shift |
| One accent | Blue marks interaction and selection. Severity colors only mean severity |
| Show the work | SQL, filters, time range, source scope, and "computed from" lines are always visible |
| Detail in place | Expanding a row reveals its detail directly under it. No side panels for reading events, no modals for data |
| Two page types | **Search** for open-ended querying, **Investigation** for a focused summary of one entity (an IP, user, host, or alert) |

---

## 2. Themes and palette

Dark is the default. Light is a first-class theme with its own values, not an inversion. Respect `prefers-color-scheme` on first load, then the user's choice.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#0F1115` | `#F3F4F6` | Page background |
| `--top` | `#0A0C10` | `#1D2330` | Top bar (dark in both themes) |
| `--nav` | `#13161C` | `#FFFFFF` | Left navigation |
| `--surface` | `#161A21` | `#FFFFFF` | Cards, tables, panels |
| `--surface-head` | `#1A1F27` | `#F8F9FB` | Table header rows |
| `--surface-expand` | `#1B212B` | `#F6F9FE` | Inline row expansion |
| `--inset` | `#0B0D11` | `#F3F5F8` | SQL editor, raw log blocks |
| `--border` | `#272D38` | `#E1E4EA` | Default 1px borders and row dividers |
| `--border-strong` | `#3A4250` | `#C3C9D4` | Inputs, secondary buttons |
| `--text` | `#E6E9EF` | `#1D2330` | Primary text and data |
| `--text-secondary` | `#A3ACBA` | `#4B5263` | Labels, breadcrumbs, metadata |
| `--text-muted` | `#838D9C` | `#646D7E` | Section labels, hints, NULL glyph |
| `--accent` | `#2F6FE0` | `#1F5FBF` | Primary buttons (fill) |
| `--accent-text` | `#7AAEFA` | `#1F5FBF` | Links, active nav text, command bar primary |
| `--accent-subtle` | `rgba(76,141,246,0.16)` | `#E8F0FB` | Active nav item, filter chips |
| `--row-selected` | `rgba(76,141,246,0.10)` | `#EEF4FD` | Expanded or selected row |
| `--focus-ring` | `#7AAEFA` | `#1F5FBF` | 2px outline, 1px offset |

### Severity (reserved for alerts, Sigma levels, and OCSF `severity_id` only)

Shown as a filled badge with a text label, never color alone.

| Level | Dark badge (bg / text) | Light badge (bg / text) | OCSF `severity_id` |
|---|---|---|---|
| Critical | `rgba(244,63,94,0.18)` / `#F7899B` | `#FDE7EA` / `#B4162F` | 5, 6 |
| High | `rgba(249,115,22,0.18)` / `#F9A66B` | `#FEEBDD` / `#A34A08` | 4 |
| Medium | `rgba(224,169,59,0.18)` / `#F0C46A` | `#FDF1DC` / `#8A5300` | 3 |
| Low | `rgba(76,141,246,0.16)` / `#9CC2FA` | `#E8F0FB` / `#174A96` | 2 |
| Info | `#232A35` / `#A3ACBA` | `#EEF0F4` / `#3D4555` | 1 |

### Semantic

| Token | Dark | Light | Use |
|---|---|---|---|
| `--ok` | `#5FC9A0` | `#1F7A5A` | Healthy, passed, "0 successful after failures" |
| `--warn` | `#F0C46A` | `#8A5300` | Partial parse, unverified citation |
| `--danger` | `#F7899B` | `#B4162F` | Destructive confirm, gate block, errors |
| `--local` | `#7FD3B2` on `rgba(63,182,139,0.16)` | `#1F6B57` on `#E3F4EF` | "Local only" classification badge |
| `--cloud` | `#B9A2FB` on `rgba(167,139,250,0.16)` | `#6D28D9` on `#F1EBFE` | Cloud provider badge. SPEC D12: the only purple in the app |

---

## 3. Typography

| Role | Font | Notes |
|---|---|---|
| UI | Source Sans 3 | Self-hosted via `@fontsource`. Tabular numbers in tables and KPIs |
| Data | Source Code Pro | Every log field value, IP, event id, SQL, raw line |

| Name | Size / line | Weight | Use |
|---|---|---|---|
| `text-xs` | 12 / 16 | 600 | Nav section labels, badges |
| `text-sm` | 13 / 18 | 400 | Data cells, metadata, breadcrumbs, chips |
| `text-base` | 14 / 20 | 400 | Default UI text, buttons, inputs, table text |
| `text-md` | 15 / 22 | 600 | Card titles, expanded-row title |
| `text-lg` | 22 / 28 | 600 | Page title (Search pages) |
| `text-xl` | 24 / 32 | 700 | Page title (Investigation pages) |
| `text-kpi` | 28 / 36 | 700 | KPI card values only |

---

## 4. Spacing, shape, density

- 4px grid. Allowed: 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32.
- Radius: 4px on controls and tables, 6px on cards, 3px on badges, 12px only on filter chips. Nothing larger.
- Table row: 36px default ("comfortable"), 30px compact. User toggle per table.
- Page padding 20px (Search) or 24px (Investigation). Card padding 14 to 16px.
- Borders 1px. No drop shadows in dark theme except the command palette. Light theme cards use border only.
- Transitions 120ms ease-out. `prefers-reduced-motion` disables them.

---

## 5. Application shell

```
+-------------------------------------------------------------------------------+
| [logo] Remnant | Security workspace  [ Jump to  Ctrl K ]     env  theme  user  sign out |  48px top bar
+------------------+------------------------------------------------------------+
| General          | Home > Investigate > Search                                |
|   Dashboard      | Search                                       (page title)  |
|   Search         | Run query  Save  Schedule  Export  Columns   Last run ...  |  command bar
| Investigate      |------------------------------------------------------------|
| > Search         | [Time range: Last 24h] [Source: linux_sshd] + Add filter   |  filter chips
|   Investigations | Simple | Ask in plain English | SQL     (tabs)            |
|   Saved searches | +--------------------------------------------------------+ |
| Detect           | | Results  23 items                                      | |
|   Detection rules| | > row                                                  | |
|   Schedules      | | v row (expanded: fields | raw, actions)                | |
| AI               | | > row                                                  | |
|   AI usage       | | 1 to 10 of 23                    Previous  Next         | |
| System           | +--------------------------------------------------------+ |
|   Health         |                                                            |
|                  |                                                            |
| ---------------- |                                                            |
|   Settings       |  (pinned to the foot; opens its own sub-nav)               |
+------------------+------------------------------------------------------------+
```

- **Top bar** is dark in both themes, 48px, and stays in view on scroll. Contains product mark, workspace label, a compact **Jump to** button with the shortcut (it opens the command palette, so it is styled as a button, not a text field), an optional environment label (`server.environment_label`, for example "Lab"; hidden when unset, never the raw host or IP), theme toggle, and user menu.
- **Left nav** is 220px, labeled, grouped by section in order of daily use (F48): General (Dashboard), Investigate, Detect, AI, System (Health, also reached from the Dashboard health strip). One label per meaning: **Agents** is the AI agents tab of AI usage; the Health tab for log collectors is **Endpoint agents**. Configuration lives under **Settings**, which has its own sub-nav (Start here, Data, Access, AI, Alerts, Records; D70). Items hidden by role (an Auditor sees no Settings items they cannot use). Settings stays in view on short screens: the section list scrolls, the pinned entry does not. Collapses to an icon rail below 1100px and stacks on phones. From tablet width up it stays in view under the top bar, and **Settings** is pinned to its foot below a divider, out of the way of daily work. A page with tabs (AI usage, Health) always lists them under its nav item, indented on a hairline, so every tab is one click away; only the open page marks its current tab; the tab lives in the URL (`/ai#agents`) so nav links, Back, and the command palette (`AI usage › Agents`) all reach it.
- **Page header**: breadcrumb, title, then a command bar of text buttons. The primary command is in accent text; destructive commands are never in the command bar.

---

## 6. Page patterns

### 6.1 Search

Order: filter chips, the tab strip (**Simple**, **Ask in plain English**, **SQL**; ADR-0008, ADR-0009), the active tab's panel, results card. One results card serves all three tabs.

| Tab | Spec |
|---|---|
| Simple | One monospace search box with a filled Search button; example searches as clickable chips; "Show SQL" reveals the compiled SQL and its bound values in an `--inset` block; "Edit as SQL" opens it in the SQL tab with values written in; notes (such as a field read from `unmapped`) in secondary text. First-time default |
| Ask in plain English | Model picker with Local or Cloud badge, earlier questions as a numbered list, prompt box, then the generated SQL read-only in an `--inset` block, an outlined Run, and the model explanation. Run copies the SQL to the SQL tab and runs it. Hidden from auditors; with no provider, one line saying Simple and SQL still work. Never chat bubbles |
| SQL | The CodeMirror editor and Run, as below |

The tab last used is remembered per browser. Panels stay mounted, so switching tabs keeps a question and its turns.

| Element | Spec |
|---|---|
| Filter chips | Pill chips in `--accent-subtle`. Click to edit, `x` to remove, "+ Add filter" link. Chips and SQL stay in sync |
| SQL editor | CodeMirror 6 in `--inset`, Source Code Pro 13px, 4 lines default, resizable. `Ctrl+Enter` runs. Guard rejections show inline under the editor in `--danger` |
| Results card | Header with count and timing, column header row in `--surface-head`, rows, pagination footer with totals |
| Row | Chevron, time, severity badge, key columns, message (ellipsis). Hover tints row. Click or Enter toggles expansion |
| Expanded row | Directly under the row, full width, `--surface-expand`. Title + category badge + classification badge + actions on one line; below it, a two-column field list on the left and the raw event on the right. Actions: **Investigate** (primary), Explain, Copy as JSON. Each text or number field shows small **+** (Filter for), **−** (Filter out), and **Top** (Top values) buttons on hover or focus; they add to the Simple search and run it. One row expanded at a time by default |
| Empty / no results | Heading, one sentence, one action ("Widen time range") |

### 6.2 Investigation

A focused, saved page about one entity. Reached from an expanded row's **Investigate** action, a detection, or the Investigations list.

| Section | Spec |
|---|---|
| Header | Breadcrumb, entity title ("Failed SSH logins from 203.0.113.9"), owner and timestamp, status, actions (time range, Export report, Save investigation) |
| KPI cards | 3 to 5 cards: label, big value (`text-kpi`), one-line context. Values are computed from the evidence; color only for meaning (`--ok` for a good zero) |
| Finding | One card: icon in severity tint, a one-line headline, two sentences of plain-language summary, and a "Computed from the events below" line with a link to the query. AI-written findings carry event-id citations and the "unverified" label rules from SPEC 7 |
| Charts | Simple bars: over time and top values. One accent color, labeled values, no gridlines |
| Evidence | Compact events table with the same row and expansion behavior as Search, plus "View all in Search" |

### 6.3 Health, Dashboards, Ask, Settings

- **Health** holds what Overview used to (F55, ADR-0034 rows 11 to 16), answering "am I blind?". Top: four KPI tiles in the Dashboard card grammar, each a button that opens its detail: Events (24 h total, change against a usual day), Sources (N of N healthy in `--warn` when not all, gaps, longest wait), Needs attention (flagged dashboard panels, newest named), and for admins Alert delivery (`--danger` when anything failed). Then the status line: one sentence when there are no detections, paused schedules, or failed deliveries; otherwise a three-column card listing them (detections grouped by rule or search with their total and runs). Under the tabs, a **Show** filter row counts the open tab's rows by level. **Sources** is one row per source, problems first: name, a status dot and word ("Flowing", "Gap", "No events in 24 hours"), an area sparkline of events per hour on a shared hour axis in local time (UTC in tooltips, the zone named under the list), each line scaled to its own busiest hour with that peak printed, gap hours shaded in `--danger` at low opacity, then the 24 h total, the rate per minute, and last received, all printed. Each gap is a sentence under its row in `--danger`: "No events 2:00 to 7:00 AM (5 h). Other sources kept flowing." `/overview` opens Health > Sources; Home without a Dashboard panel opens Health. The product mark in the top bar links Home.
- **Dashboards** use the Investigation card grammar (cards, KPIs, simple bars) for scheduled-search panels (SPEC 5.5). First in the nav and the landing page when the viewer has a panel (ADR-0031); a one-line Health strip from Overview sits above the panels. Panels are a **tile** (a sixth: name, headline number, label, trend, flag; no table), a third, a half, or full width; a label-and-count result can show as bars (D82). Order on the page: dashboard picker and Edit layout, Health strip, **Needs attention** (one row per flagged panel: a `--sev-high-text` bar, name, flag reason, headline, relative time with UTC in a tooltip, Show panel, Acknowledge; hidden when empty), then sections, each with a plain heading and its count over a hairline. The headline is `text-kpi`, tabular, and links to the rows behind it; a zero on a panel with a flag set is `--ok`. Labels say what is counted ("3 addresses"), from the owner's label or the result's first column, never "rows". Flags read in plain words ("3 addresses over threshold (0)") in `--warn`, with an outlined `--warn` **Flagged** badge; severity colors only when the panel carries a severity. Tiles sit in their own row of the section (two per row on phones, six on wide screens) with one line each for name, number and label, and flag state, so nothing wraps and nothing floats. The trend line shows from the third run. A section with one card gives it the full row. The page header carries the range and "Updated N min ago" (UTC in the tooltip). An empty cell in a user column says "No user parsed" on hover. Layout controls appear only in Edit layout: panels drag within and between sections (the drop place shows as an accent outline), each panel has a **Section** list and **Earlier** / **Later** for the keyboard, and each section heading has Rename, Move up, Move down, and Delete (its panels go to No section). An empty section shows a dashed drop area. Section order is stored, not derived from panels (D100). Panels never show developer text: when columns are hidden, the button reads **View all** (ADR-0034).
- **No sideways scrolling** (F54): at desktop widths no page, card, or table scrolls sideways. Flex and grid children that hold text or tables get `min-width: 0`; long identifiers and paths wrap anywhere (`overflow-wrap: anywhere`); times in tables are relative with the UTC time in a tooltip. Only the search results grid, whose columns the user picks, may scroll (`data-scroll-x`). CI opens every page and tab at 1280px with the demo lab's data and fails on any sideways scroll (`scripts/check-layout.py`).
- **Data attribution** (F52): a license credit such as "IP Geolocation by DB-IP" is `--text-muted` small text, once per page (below the results table), never in the accent color and never repeated per row. **About and licenses** (Settings > Records) lists each outside data source, its use, license, and attribution in one table.
- **Ask** is a tab of Search (6.1), not a page of its own; `/ask` opens Search on that tab.
- **Audit log** has Activity and AI calls tabs over a dense table, filters in one row, rows that expand to show detail as text, Load older entries at the foot, and Export CSV as the primary command.
- **Settings** pages (Users and access, Sources, AI providers) are list + detail forms with labels above inputs, help text below, and a sticky save bar.

---

## 7. Components

| Component | Spec |
|---|---|
| Primary button | `--accent` fill, white text, 32 to 36px tall, 4px radius. One per view |
| Secondary button | Transparent, 1px `--border-strong`, `--text` |
| Command bar button | Text only, no border; primary command in `--accent-text` and 600 weight |
| Badge | 3px radius, 12px semibold text, tinted background per section 2 |
| Filter chip | 12px radius pill, `--accent-subtle` background |
| Card | `--surface`, 1px `--border`, 6px radius, title in `text-md` |
| Table header | `--surface-head`, 13px semibold `--text-secondary`, sortable on click |
| NULL value | `·` in `--text-muted`, never blank, never "null" |
| Command palette | `Ctrl+K` / `Cmd+K` and the top bar search. 560px, `--surface`, 6px radius. Sections: Navigate, Saved searches, Sources, Actions, Recent. Flavor names (Séance, Grimoire, Ossuary) resolve as aliases only |
| Toasts | Only for background job completion. Errors appear inline where they happened |

Icons: Lucide, 16px in nav and buttons, 14px in tables, 1.5px stroke. No emoji anywhere.

---

## 8. Do / Don't

| Do | Don't |
|---|---|
| Labeled nav grouped by task | Icon-only navigation as the default |
| Breadcrumbs and a page title on every page | Pages without a clear "where am I" |
| Expand detail inline under the row | Side drawers or modals for reading an event |
| Show SQL, filters, scope, and timing | Hide the query behind "AI magic" |
| Severity only for severity, always with a label | Red buttons for emphasis, color-only status |
| Monospace for log data | Proportional font in data cells |
| Plain English copy: "Run query", "Save", "Blocked" | "Let's go", exclamation marks, emoji |
| "Computed from the events below" on summaries | Unsourced numbers or AI claims without citations |
| Purple only for the cloud badge | Purple accents, gradients, glow effects |
| Plain labels in nav and buttons | Flavor names anywhere a new user has to guess |

---

## 9. Accessibility baseline

- WCAG AA contrast (4.5:1 text, 3:1 large text and UI) in both themes; checked per token change.
- Every interactive element is a real `button`, `a`, or input; visible focus ring; `Esc` closes any layer.
- Tables support arrow-key row movement and `Enter` to expand; expanded rows set `aria-expanded`.
- Charts carry an `aria-label` summary of their values.

---

## 10. Terminal (CLI and TUI)

The CLI (`remnant`) and the Slice 6 terminal UI follow the same rules as the web console.

| Rule | CLI now | TUI (Slice 6) |
|---|---|---|
| Data first | Plain aligned columns; `json`, `csv`, `raw` for piping | Same table grammar as Search: rows, expand inline with `Enter` |
| Status on stderr | Row count and timing go to stderr so stdout stays pipe-clean | Status bar at the bottom: rows, timing, source scope, server |
| Color | None by default in piped output. When a TTY: severity labels and errors only, honoring `NO_COLOR` | Same palette roles as section 2 mapped to 256-color: accent blue for focus, severity tints for badges |
| Safety | Log content stripped of control sequences before printing | Same; raw view renders text only |
| Layout | Truncate the last column to the terminal width with `…` | Left pane (sources, saved searches), main results table, bottom detail pane, `?` for keys |

The TUI gets its own mockups on the design canvas before it is built.

---

## 11. Token mapping (reference)

```css
:root, :root[data-theme="dark"] {
  --bg: #0F1115; --top: #0A0C10; --nav: #13161C; --surface: #161A21;
  --surface-head: #1A1F27; --surface-expand: #1B212B; --inset: #0B0D11;
  --border: #272D38; --border-strong: #3A4250;
  --text: #E6E9EF; --text-secondary: #A3ACBA; --text-muted: #838D9C;
  --accent: #2F6FE0; --accent-text: #7AAEFA; --accent-subtle: rgba(76,141,246,0.16);
  --row-selected: rgba(76,141,246,0.10); --focus-ring: #7AAEFA;
  --ok: #5FC9A0; --warn: #F0C46A; --danger: #F7899B;
}
:root[data-theme="light"] {
  --bg: #F3F4F6; --top: #1D2330; --nav: #FFFFFF; --surface: #FFFFFF;
  --surface-head: #F8F9FB; --surface-expand: #F6F9FE; --inset: #F3F5F8;
  --border: #E1E4EA; --border-strong: #C3C9D4;
  --text: #1D2330; --text-secondary: #4B5263; --text-muted: #646D7E;
  --accent: #1F5FBF; --accent-text: #1F5FBF; --accent-subtle: #E8F0FB;
  --row-selected: #EEF4FD; --focus-ring: #1F5FBF;
  --ok: #1F7A5A; --warn: #8A5300; --danger: #B4162F;
}
```

Severity, local, and cloud badge pairs are defined in `tokens.css` as `--sev-<level>-bg` / `--sev-<level>-text`, `--local-bg` / `--local-text`, `--cloud-bg` / `--cloud-text`, per section 2.
