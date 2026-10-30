# DESIGN BRIEF: Remnant

Product name is a working codename and is rendered from the `PRODUCT_NAME` constant (see `CLAUDE.md` section 2). Never typeset it by hand in a component.

**Direction (D24): "Workspace."** A polished commercial security console, closer to Microsoft Sentinel and Splunk in structure and to the best commercial consoles in readability than to a developer side project. Dark theme first with a complete light theme. Labeled navigation, clear page hierarchy, consistent components, inline detail. If a screen looks like a chat app, a marketing site, or a weekend project, it is wrong.

Reference mockups: the "Remnant Design Directions" canvas, second row (Search dark, Search light, Investigation view).

Tokens below are the contract. They land in `frontend/src/styles/tokens.css` and Tailwind reads from them. No component uses a hex value directly.

---

## 1. Principles

| Principle | In practice |
|---|---|
| Enterprise, not app-like | Full app chrome (top bar, labeled nav, area tabs, command bar). No floating gimmicks, no oversized hero text |
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
| `text-kpi-lg` | 34 / 40 | 700 | Dashboard KPI values from 1500px wide (ADR-0038 edit 10) |

---

## 4. Spacing, shape, density

- 4px grid. Allowed: 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32.
- Radius: 4px on controls and tables, 6px on cards, 3px on badges, 12px only on filter chips. Nothing larger.
- Table row: 36px "comfortable", 30px "compact". Density is a per-user choice in the user menu, remembered in the browser; with no choice, comfortable from 1440px wide and compact below (ADR-0038 edit 10). Search results keep their own table toggle.
- Page padding 20px (Search) or 24px (Investigation). Card padding 14 to 16px.
- Borders 1px. No drop shadows in dark theme except the command palette. Light theme cards use border only.
- Transitions 120ms ease-out. `prefers-reduced-motion` disables them.

---

## 5. Application shell

```
+--------------------------------------------------------------------------------------------------+
| [logo] Remnant  [install]   [ Search pages, saved searches, sources      Ctrl K ]   Updated 1 min ago  Refresh  [bell 9]  (sun)  user v |  48px
+------------------------+-------------------------------------------------------------------------+
| Monitor              v | Investigate                                              (area title)   |
|   Dashboard            | Search | People & devices | Saved searches 17              (tabs)         |
|   Alerts             9 |-------------------------------------------------------------------------|
|   | Open               | Run query  Save  Schedule  Export  Columns                              |
|   | Closed  Muted ...  |-------------------------------------------------------------------------|
| Investigate          v | [Last 24 hours] [Source: linux_sshd] + Filter  (o 9 sources)            |
|   Search               | +---------------------------------------------------------------------+ |
|   People & devices     | | Results  23 items                                                   | |
|   Saved searches       | | > row                                                               | |
| AI                   v | +---------------------------------------------------------------------+ |
|   AI usage / Agents    |                                                                         |
| System               > |                                                                         |
+------------------------+-------------------------------------------------------------------------+
```

- **Top bar** is dark in both themes, 48px, and stays in view on scroll. Three columns: product mark and the optional install name (set by an admin; signed-in people only; nothing when unset) on the left; a wide **search** in the center (up to 680px, ADR-0038 edit 10) with the shortcut, which opens the command palette's list; on the right an optional environment label (`server.environment_label`, for example "Lab"; hidden when unset, never the raw host or IP), **Updated N min ago** and **Refresh** (refetches everything on the page; the only freshness line, pages do not repeat it), the bell with the open alert count, the theme toggle as a sun or moon icon with a tooltip, and the user menu (account, **Density**, sign out).
- **Left nav** (ADR-0038 edit 10) is 240px from 1100px up, in four collapsible groups: **Monitor** (Dashboard, Alerts with the open count, Microsoft 365 once built), **Investigate** (Search, People & devices, Saved searches), **AI** (AI usage, Agents), **System** (Health, Settings). Page rows are 34px at 15px semibold with an 18px icon; every page with sub-pages lists them under it on a hairline (30px rows, 14px), the current one on the accent tint. Each group's open or closed state is remembered in the browser. Settings keeps its own sub-nav on its pages (Start here, Data, Access, AI, Alerts, Records; D70); its sub-pages are not listed in the rail, so the rail fits a 1080px tall screen. Between 768 and 1100px the rail shows icons only, with the label as a tooltip, and hovering or focusing a page shows a menu of its sub-pages; on phones it opens from the Menu button. Items hidden by role. One label per meaning: **Agents** is the AI agents area; the Health tab for log collectors is **Endpoint agents**.
- **Page header**: the area title, then the area's **tabs** (a tab row with counts; each tab has its own URL, `/<area>/<tab>`), then a command bar of text buttons. No breadcrumb, except on entity pages. The primary command is in accent text; destructive commands are never in the command bar.

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
| Charts | Trends over time: a short area chart (`TrendChart`), at most 160 px tall (140 px by default), smooth monotone curves that never dip below zero, values on hover or with the arrow keys, a stack for parts of a whole, and the window before as a faint dashed line where there is one. Top values: horizontal bars. Any vertical bar is at most 20 px wide. One line of dashed gridline at half, no printed values on the plot |
| Evidence | Compact events table with the same row and expansion behavior as Search, plus "View all in Search" |

### 6.3 Health, Dashboards, Ask, Settings

- **Health** holds what Overview used to (F55, ADR-0034 rows 11 to 16), answering "am I blind?". Top: four KPI tiles in the Dashboard card grammar, each a button that opens its detail: Events (24 h total; compared with a usual day only after 7 full days of history and only over sources that have them, otherwise "Not enough history yet (N of 7 days)"), Sources (N of N healthy in `--warn` when not all, gaps, longest wait), Needs attention (flagged dashboard panels, newest named), and for admins Alert delivery (`--danger` when anything failed). Then the status line: one sentence when there are no detections, paused schedules, or failed deliveries; otherwise a three-column card listing them (detections grouped by rule or search with their total and runs). Under the tabs, a **Show** filter row counts the open tab's rows by level. **Sources** is one row per source that brings events (files, syslog, OpenTelemetry, Loki, Microsoft 365, the Anthropic admin API), problems first; enrichment feeds have their own tab, judged by each feed's update interval (F59): name, a status dot and word ("Flowing", "Gap", "No events in 24 hours"), an area sparkline of events per hour on a shared hour axis in local time (UTC in tooltips, the zone named under the list), each line scaled to its own busiest hour with that peak printed, gap hours shaded in `--danger` at low opacity, then the 24 h total, the rate per minute, and last received, all printed. Each gap is a sentence under its row in `--danger`: "No events 2:00 to 7:00 AM (5 h). Other sources kept flowing." `/overview` opens Health > Sources; Home without a Dashboard panel opens Health. The product mark in the top bar links Home.
- **Dashboards** use the Investigation card grammar (cards, KPIs, simple bars) for scheduled-search panels (SPEC 5.5). First in the nav and the landing page when the viewer has a panel (ADR-0031); a one-line Health strip from Overview sits above the panels. Panels are a **tile** (a sixth: name, headline number, label, trend, flag; no table), a third, a half, or full width; a label-and-count result can show as bars (D82). Order on the page: dashboard picker and Edit layout, Health strip, **Needs attention** (one row per flagged panel: a `--sev-high-text` bar, name, flag reason, headline, relative time with UTC in a tooltip, Show panel, Acknowledge; hidden when empty), then sections, each with a plain heading and its count over a hairline. The headline is `text-kpi`, tabular, and links to the rows behind it; a zero on a panel with a flag set is `--ok`. Labels say what is counted ("3 addresses"), from the owner's label or the result's first column, never "rows". Flags read in plain words ("3 addresses over threshold (0)") in `--warn`, with an outlined `--warn` **Flagged** badge; severity colors only when the panel carries a severity. Tiles sit in their own row of the section (two per row on phones, six on wide screens) with one line each for name, number and label, and flag state, so nothing wraps and nothing floats. The trend line shows from the third run. A section with one card gives it the full row. The page header carries the page's time window (ADR-0038 edit 10): **24 hours**, **7 days**, **30 days** (remembered in the browser) with its dates; freshness is only in the top bar. An empty cell in a user column says "No user parsed" on hover. Layout controls appear only in Edit layout: panels drag within and between sections (the drop place shows as an accent outline), each panel has a **Section** list and **Earlier** / **Later** for the keyboard, and each section heading has Rename, Move up, Move down, and Delete (its panels go to No section). An empty section shows a dashed drop area. Section order is stored, not derived from panels (D100). Panels never show developer text: when columns are hidden, the button reads **View all** (ADR-0034).
- **Dashboard order** (F62, replaces the morning answer box): a compact header row (title, dashboard picker, New dashboard, Edit layout, and "Updated N min ago" at the right; no band under the title); the **Needs you** banner only when something needs the viewer (open alerts, runs of one search, rule, or source as one line, and sources with errors or that stopped with no alert about it), one line each with a severity badge first (High, Source, Medium, Alert), the newest first within a severity, five lines then "N more on Alerts", each a link to the alert or the Health row, hidden entirely when nothing needs the viewer; then AI Watch; then the panels; then one **Sources** line at the bottom ("4 of 4 flowing, longest wait 3 min (m365), no gaps") linking to Health. On a quiet day the first screen is AI Watch and the start of the panels.
- **Default sections** (ADR-0038 edit 10), after AI Watch and before the panels, each shown only when the viewer has its source, in the page grammar: a header with what it is from and, once, "Changes against the previous 7 days"; a KPI strip of 4 to 6 cards (`text-kpi`, `text-kpi-lg` from 1500px; the change as a neutral pill beside the value; a two-line context; a card that needs a setting says so, "Set approved countries", instead of a number); then a chart and a top-N table side by side (3fr / 2fr from 1500px, halves from 1024px, stacked below). **Identity** (Microsoft 365): failed sign-ins, sign-ins outside approved countries, inbox rules and forwarding, app consents (blocked as context), admin role grants, Conditional Access edits; failed sign-ins as one `--warn` area, hourly for 24 hours and 7 days and daily for 30 days, with the window before as a dashed line and the failure rate in the caption; top failing users. **Attacks and access**: sign-in failures from external addresses (not in Internal networks), attacking addresses, countries, VPN logins outside approved countries; failures by host as small multiples (one row of bars per host on its own scale, bars at most 20 px wide, peak and total printed); top sources by country and network. A note asks for company egress while none is listed. Top sources with no country say why instead of "Unknown": Not an address (the field holds something else), Not a public address, Not in GeoIP file (the file's install date in the tooltip, and a note under the table with Update GeoIP for admins), or No GeoIP file. **Detections**: rule matches, rules that matched (of N enabled), hosts and users involved; matches by rule as small multiples; the hosts and users involved. With 24 hours the charts go by hour. **Every number opens its rows** (ADR-0039): a KPI value, its change pill (the window before), a chart point (that hour or day), a small-multiples row, a sub-line such as "2 blocked", and a top-N row (an entity page when there is one, else Search) each open Search with the query behind it, already run, with a line above the editor saying where it came from ("From Dashboard > Identity > Failed sign-ins, Oct 24, 12:00 AM to Oct 30, 11:37 AM UTC"). They show a pointer and "Open 12 events in Search" on hover; a zero still opens its (empty) search. Back returns to the Dashboard at the same window and scroll position. **No comparison without history** (owner 2026-10-30): a section, and AI Watch, compares only when every source that counts toward it has data for at least 90% of the window before; otherwise the header reads "No comparison yet: data starts Oct 21", each card shows "Not enough history for comparison" in place of the change pill, and the failed sign-ins chart drops its dashed line.
- **AI Watch** (ADR-0035 Part 2) sits under the Needs you banner (or at the top when there is none) on the Dashboard when there is AI use or anything to count: a header that says what it is compared against and Open AI usage (it follows the page window; with 24 hours the chart still shows 7 days, since use is counted by day); the KPI cards whose source is set up in one row from 1024 px (a card whose source the install lacks takes no card: one muted "Not set up: ... (needs ...)" line with Add a source, under the cards; F62) (people are counted as people only; devices or addresses with no person matched get their own line under the value, "3 more devices not matched to a person", linked to the list, never added in: D115) (two per row below, the fifth spanning the row; labels one line, full on hover): value in `text-kpi` (`--ok` for a zero), the change against the previous period of the same length as a neutral pill beside the value ("↑ 1", "same"; the full sentence in its tooltip), and one context line. A card the viewer cannot read says Restricted, never zero. Under the cards, **New in 24 hours** lists what was first seen in the data (never a review decision: D116), each linking to its alert. **AI use, last 30 days** (with less than 7 days of data, "AI use since Oct 21" over the days that exist): a stacked area with daily points, approved at the bottom, then unreviewed, then not approved, in the status badges' colors (`--local-text`, `--text-muted`, `--sev-critical-text`), values and the total on hover, a printed legend with totals, and an `aria-label` summary. **Top services**: service (entity link), status badge, people ("·" with a tooltip when the events name no person), devices, last seen; **View all** opens AI usage. AI Watch review items are on Alerts with a High or Medium badge (severity tokens) and, for admins, Approve and Not approved.
- **Entity page** (product pass step 2, DESIGN 6.2): Investigations on an address, person, or machine leads with one sentence ("2,619 failed sign-ins against ftp-01 over the last 7 days, 0 succeeded. From Netherlands, AS64500."), then KPI cards (sign-in attempts, succeeded, users tried, hosts targeted, first and last seen, country and network for addresses), then **What it did**: activities grouped by outcome, each with a real example line (values intact, never the number-masked pattern), its user and target as links, and View in Search; then hosts and users it touched. The lane graph sits below, open and foldable. Times use `components/When.tsx`: local, UTC on hover.
- **Pivot rule** (product pass step 2): every IP address, user, host, and AI service value anywhere (search results, expanded rows, dashboard panel tables and bars, AI usage, Health) is an `EntityLink` to its page in Investigations (`/investigations#ip=203.0.113.9`, `#user=`, `#host=`, `#service=`), with View in Search from there. One component, `components/EntityLink.tsx`; a column is an entity by name (`lib/entity.ts`). Links are `--accent-text`, monospace with the data, and real links (middle-click works). A link inside a clickable row opens the entity, not the row. Placeholders (`-`, empty) stay text.
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
| Command palette | `Ctrl+K` / `Cmd+K` and the top bar search; opens under the search at its width (680px), `--surface`, 6px radius. Sections: Recent (empty query), then Addresses, People, Hosts, AI services (found by the server in the viewer's own sources, last 30 days; ADR-0038 edit 10), Navigate, Actions, Saved searches, Sources, and **Search events for "..."** last. An entity opens its page. Addresses and hosts in the data font, with country, network, and event count. Flavor names (Séance, Grimoire, Ossuary) resolve as aliases only |
| Toasts | Only for background job completion. Errors appear inline where they happened |

Icons: Lucide, 16px in nav and buttons, 14px in tables, 1.5px stroke. No emoji anywhere.

---

## 8. Do / Don't

| Do | Don't |
|---|---|
| Labeled nav in four groups, sub-pages listed, tabs in the page header | Icon-only navigation as the default (icons only on a collapsed rail) |
| An area title and its tabs on every page | Pages without a clear "where am I" |
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
