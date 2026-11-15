# DESIGN BRIEF: Remnant

Product name is a working codename and is rendered from the `PRODUCT_NAME` constant (see `CLAUDE.md` section 2). Never typeset it by hand in a component.

**Direction (D24): "Workspace."** A polished commercial security console, closer to Microsoft Sentinel and Splunk in structure and to the best commercial consoles in readability than to a developer side project. Dark theme first with a complete light theme. Labeled navigation, clear page hierarchy, consistent components, inline detail. If a screen looks like a chat app, a marketing site, or a weekend project, it is wrong.

Reference mockups: the "Remnant Design Directions" canvas, second row (Search dark, Search light, Investigation view), and for navigation, the page pattern, and the Graphite visual direction, the "Remnant console redesign: 4 key screens" canvas (ADR-0052, accepted 2026-11-12). The mockup images are not in the repository.

**Build status (2026-11-12).** Sections 1 to 8 and 11 were edited to ADR-0052 when it was accepted. Built so far: the tokens, fonts, type scale, and density default (sections 2, 3, 4, 11). The rest follows in that ADR's build; until each part lands, the app shows the layout and components it replaces.

Tokens below are the contract. They land in `frontend/src/styles/tokens.css` and Tailwind reads from them. No component uses a hex value directly.

---

## 1. Principles

| Principle | In practice |
|---|---|
| Enterprise, not app-like | Full app chrome (top bar, labeled nav, page header, page tabs). No floating gimmicks, no oversized hero text |
| Readable first, dense second | 14px UI text, 13px data, 34px rows by default (Comfortable) for every role. Compact (13px, 12px, 30px rows) is a per-user choice, remembered |
| One accent | Blue marks interaction and selection. Severity colors only mean severity. Low severity is neutral, so nothing but a link or a selection is blue |
| Show the work | SQL, filters, time range, source scope, and "computed from" lines are always visible |
| Detail in place | Expanding a row reveals its detail directly under it. No side panels for reading events, no modals for data |
| One page pattern | Every page has the same four zones and one of five body templates: Board, Table, List-detail, Record, Form (6.0). **Logs** is for open-ended querying; a Record page is a focused summary of one entity (an address, person, device, or alert) |

---

## 2. Themes and palette

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
| `--series-neutral` | `#646D7D` | `#858D9C` | Second neutral chart series; the third series of the set below |
| `--series-ice` | `#81DAEF` | `#0D6A7C` | Chart series: ice, a cyan (never the accent blue) |
| `--series-graphite` | `#929CAB` | `#262E3A` | Chart series: graphite, a cool steel or slate |
| `--accent` | `#3A68E0` | `#2B5BD7` | Primary button fill |
| `--on-accent` | `#FFFFFF` | `#FFFFFF` | Text on the primary button |
| `--accent-text` | `#7EA2FF` | `#2452C9` | Links, current nav item, current tab underline, focus ring |
| `--focus-ring-top` | `#7EA2FF` | `#7EA2FF` | Focus ring inside the top bar, which is dark in both themes |
| `--accent-subtle` | `rgba(91,140,255,0.14)` | `#E9EFFD` | Pressed segment, selected cited ID chip |
| `--row-selected` | `rgba(91,140,255,0.09)` | `#EFF3FE` | Selected or expanded row |
| `--warn-tint` | `rgba(232,188,98,0.08)` | `#FCF5E4` | Blind row in Needs you, blind state notices. Never an alert |

### Severity (reserved for alerts, Sigma levels, and OCSF `severity_id` only)

Always a text label, never color alone.

| Level | Form | Dark | Light | OCSF `severity_id` |
|---|---|---|---|---|
| Critical | Solid badge | `#F2647A` fill, `#1F0409` text | `#B4162F` fill, `#FFFFFF` text | 5, 6 |
| High | Solid badge | `#F08A3C` fill, `#1A0E03` text | `#B8500A` fill, `#FFFFFF` text | 4 |
| Medium | 7px square dot, then the label in `--text` | dot `#F0C46A` | dot `#8A5300` | 3 |
| Low | Dot, then the label | dot `--text-muted` (neutral, no longer blue) | dot `--text-muted` | 2 |
| Info | Dot, then the label | dot `--text-muted` | dot `--text-muted` | 1 |

**Chart series** (D263, D264). `--series-ice`, `--series-graphite`, and `--series-neutral` are the series, ice and graphite (a security console's restraint, not a set of bright hues): for things that are only different kinds (the step types of an agent session), never for good or bad, a severity, a state, a link, or a selection, and never as text (labels and values stay in the text tokens, with the mark beside them). No series color uses a hue that a state, a severity, the accent, or the Cloud badge owns: no green, red, orange, amber, yellow, accent blue, or purple. Ice is a cyan (OKLCH hue 215) at least ΔE 15 from `--accent` and `--accent-text` in both themes. Each series is at least 3:1 on `--surface` and `--surface-head` in both themes (`scripts/check-contrast.py`). The three were checked against each other for common color-vision deficiencies with an OKLab model (worst pair ΔE 15.0 dark, 13.5 light; with full color vision 15.7 and 17.2). A chart that needs more kinds than three adds a pattern, never a fourth hue: the session timeline hatches a step that reached outside the session.

Token names in `tokens.css`: `--sev-c-solid`, `--sev-c-on`, `--sev-h-solid`, `--sev-h-on`, `--sev-m-dot`. The old tinted pairs (`--sev-<level>-bg` / `-text`) are removed, including the blue Low pair. The rail and bell counts use the High solid pair.

### Semantic

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

---

## 3. Typography

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

**Time format** (owner, 2026-11-08): every time reads in the app's local format, in the viewer's time zone, "Nov 8, 7:19 AM" (`components/When.tsx`, `localStamp` where text cannot hold an element), with the UTC time on hover. Seconds only in log and event tables ("Nov 8, 7:19:52 AM", `When seconds`), so events in one minute read apart. Never a raw ISO or UTC stamp as the visible text. The zone is added only in an hour that happens twice. KPI labels wrap to at most two lines, full text on hover, never cut off in one.

Density (owner, 2026-11-11): Comfortable is the default for every role, because users are internal and non-technical. Compact is a per-user choice in the user menu, remembered in the browser. There is no width-based default.

---

## 4. Spacing, shape, density

- 4px grid. Allowed: 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32.
- Radius: 6px cards, 5px controls, 3px solid badges, 2px dots. Nothing larger.
- Density is a per-user choice in the user menu, remembered in the browser; Comfortable for everyone until they choose (section 3). Search results keep their own table toggle.
- Comfortable (default): table rows 34px, controls 32px (28px in the filter bar), rail rows 32px, tabs 36px. Compact: table rows 30px, controls 28px (26px in the filter bar), rail rows 28px, tabs 34px.
- Page padding 20px on every page. Card padding 12 to 14px.
- Surfaces are flat: 1px `--border`, no fills in dark, white on `--bg` in light. No drop shadows except the command palette.
- Table headers have no fill: 12px at 500 in `--text-secondary` over a 1px divider.
- Charts: 1.5px lines, no area fill; the window before as a dashed `--text-muted` line. Stacked parts are separate lines with a printed legend. Top values stay horizontal bars.
- Transitions 120ms ease-out. `prefers-reduced-motion` disables them.

---

## 5. Application shell

```
+----------------------------------------------------------------------------------------------+
| Remnant [install]   [ Search pages, people, addresses, saved searches   Ctrl K ]  Updated 1 min ago  Refresh  [bell 7]  user v |  48px
+--------------------+-------------------------------------------------------------------------+
| Monitor            | Alerts  7 open                                    [secondary] [Primary] |  header 44px
|   Dashboard        | Queue | Rules | Schedules                                               |  tabs 36px
| | Alerts         7 | [Time] [State] [facets] [text box]                         7 alerts     |  filter bar 40px
| Investigate        |-------------------------------------------------------------------------|
|   Logs             | body: Board, Table, List-detail, Record, or Form                        |
|   Ask AI           |                                                                         |
|   People & devices |                                                                         |
| AI                 |                                                                         |
|   AI usage       1 |                                                                         |
|   Agents           |                                                                         |
| Pinned             |                                                                         |
|   Failed sign-ins  |                                                                         |
| Recent             |                                                                         |
|   alice            |                                                                         |
|   ws-0042          |                                                                         |
| ------------------ |                                                                         |
|   Health         7 |                                                                         |
|   Reports          |                                                                         |
|   Settings         |                                                                         |
+--------------------+-------------------------------------------------------------------------+
```

- **Top bar** is dark in both themes, 48px, and stays in view on scroll. Three columns: product mark and the optional install name (set by an admin; signed-in people only; nothing when unset) on the left; a wide **search** in the center (up to 680px, ADR-0038 edit 10) with the shortcut, which opens the command palette's list; on the right an optional environment label (`server.environment_label`, for example "Lab"; hidden when unset, never the raw host or IP), **Updated N min ago** and **Refresh** (refetches everything on the page; the only freshness line, pages do not repeat it), the bell with the open alert count, the theme toggle as a sun or moon icon with a tooltip, and the user menu (account, **Density**, sign out).
- **Left nav** (ADR-0052) is 208px from 1100px up. Three labeled groups: **Monitor** (Dashboard, Alerts with the open count), **Investigate** (Logs, Ask AI, People & devices), **AI** (AI usage, Agents). A pinned cluster at the bottom under a hairline: **Health**, **Reports**, **Settings**. Counts, each only above zero and never a zero (D258): Alerts the open alerts, solid on the High pair; AI usage the Inventory items still to review, outlined and neutral (`--border-strong`, `--text-secondary`), and AI usage then opens its Inventory; Health the sources needing attention, outlined in `--warn`, with "N sources need attention" as its tooltip and for screen readers. The counts follow a page's own data while it shows it and otherwise read numbers-only counts every five minutes (`/api/alerts/count`, `/api/ai/inventory/count`, `/api/health/count`, none audited). Rows are 32px, 14px at 500 with a 16px icon (28px, 13px in Compact); pinned rows are 400. The rail's entries are pages only, never sub-pages. Under the page groups, in a `nav` region of its own named Recent (not part of the Primary nav), the rail lists the last 5 entities the viewer opened (people, hosts, addresses), newest first, under a "Recent" label like a group label; hidden when empty. Its rows are 400 in `--text-secondary` with a 14px icon by kind and the value in mono, so they never read as pages. Recent is kept in the browser per signed-in user, never on the server; without View people in AI usage (D242) it holds no people. It shrinks first on short windows (5 rows from 700px tall, 3 from 620px, none below) so the rail never scrolls, and is hidden in the icon-only rail. Above Recent, in a `nav` region of its own named Pinned, the viewer's pinned saved searches and dashboards (D259), oldest first, at most 5, with Recent's row anatomy (a 14px search or grid icon, the name cut by `Truncate`); hidden when empty and in the icon-only rail. Pins are kept on the server per user, so they follow the person; **Pin** and **Unpin** sit on a saved search's row and runner and beside the Dashboard's picker. On a short window Recent gives way first (its thresholds rise with each pin), then Pinned (5 rows from 700px tall, 3 from 620px, none below). Groups do not collapse. Group labels are `text-xs` (12px at 500) in `--text-muted`, sentence case. Entries a role cannot use are not shown. Between 768 and 1100px the rail shows icons only with the label as a tooltip; on phones it opens from the Menu button. Settings keeps its own sub-nav on its pages (D70). One label per meaning: **Agents** is the AI agents area; log collectors are **Collectors** on Health.
- **Where you are.** The current page has a 2px bar in `--accent-text` on its left edge and its label in `--accent-text` at 600. No fill. Hover keeps the `--surface-head` fill. The current link keeps `aria-current="page"`. A Record page marks the rail entry it was reached from (an alert page marks Alerts; a person page marks People & devices). Color is never the only cue: the bar is a shape and the label changes weight.
- **Page header** (`PageHeader`, one shared component): the page title (`text-lg`) and an optional count on the left; on the right, up to two secondary buttons, an overflow menu, and at most one filled primary button, last. The title is the page's name, never the group's. Then the page's own tabs (max 5, each with a URL `/<page>/<tab>`), then the filter bar. Record pages add a breadcrumb above the title. There is no command bar. Destructive actions are never the primary.

---

## 6. Page patterns

### 6.0 Page pattern

Every page has the same four zones and one of five body templates (ADR-0052 sections 3.5 to 3.7).

| Zone | Height | Contents | Rules |
|---|---|---|---|
| 1. Header | 44px | Page title, optional count. Right: up to two secondary buttons, an overflow menu, then one filled primary button where one exists, last | Title is the page name, never the group name. One shared `PageHeader` component, landed first |
| 2. Tabs | 36px | That page's tabs only | Omitted when the page has none |
| 3. Filter bar | 40px | Time, State, facets, text box. Right: count, Columns | One row; extras under "More filters" |
| 4. Body | rest | One of the five templates | First data row within 200px of the top bar |

| Template | Shape | Pages |
|---|---|---|
| Board | Needs you list, then sections of KPI strip plus chart and table | Dashboard |
| Table | Optional KPI strip that filters, then one table with inline row expansion | Logs, Rules, Schedules, Saved searches, People & devices, AI usage (all tabs), MCP servers, Accounts, Health, Reports |
| List-detail | List (5 parts) and sticky detail pane (7 parts) | Alerts > Queue, Agents > Sessions |
| Record | Breadcrumb, title, one-sentence summary, KPI row, main column (2 parts) and side column (1 part) | Full alert page, person, device, address, AI service |
| Form | Section list and form, sticky save bar | Settings |

Ask AI is the one exception (a thread, DESIGN 6.1).

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

Every card on the Dashboard, AI usage, Agents, and the Record pages uses the one card anatomy of section 7 (D254): one title row with the title, an optional (i), an optional muted note, and one action at the top right.

Empty states: left-aligned at the top of the body, at most two lines and one action, no illustrations.

| Kind | Example | Action |
|---|---|---|
| Not set up | "Needs a Microsoft 365 source" | Add a source |
| Filters hide everything | "No alerts match these filters." | Reset filters |
| Good zero | "No open alerts. Checked 2 min ago." in normal text | none |
| Default filter is empty | Inventory opens on All with "0 to review" | none |
| No permission | "Restricted" | never shown as zero |

- **Filter bar** (`FilterBar`): fixed order Time, State, facets, text box; count and Columns on the right. Time is a segmented control: 1 hour, 24 hours, 7 days, 30 days, Custom. State is a segmented control with counts. Facets are buttons that read "Name **Value**". Filter state lives in the URL fragment. **Reset** shows only when the filters differ from the page default.
- **States**: the States artboard on the design canvas is the reference for `Skeleton`, `StillWorking`, `InlineError`, `EmptyState` (five kinds), and `StateNotice` (names hidden, restricted, no model, detection paused, template missing).

### 6.1 Logs and Ask AI

One name per thing (owner, 2026-11-04; SPEC D206). "Search" stays a verb and is no longer the name of a page or a mode.

| Thing | Label | Path |
|---|---|---|
| Manual search page (rail row) | **Logs** | `/investigate/logs` |
| Its modes | **Filters** (the Simple syntax), **SQL** | same page; the address fragment keeps `tab=simple` or `tab=sql` |
| Plain-English questions (rail row; hidden from auditors) | **Ask AI** | `/ask-ai` |
| The Ctrl+K panel over any page | **Ask AI** | none (a panel) |
| An answer's SQL handed to Logs | **Open in Logs** | `/investigate/logs`, SQL mode |
| Older addresses | `/search`, `/investigate/search` open Logs; `/ask` opens Ask AI | replaced, not added to history; search state in the fragment is kept |

**Logs.** Order: filter chips, the mode strip (**Filters**, **SQL**; ADR-0008, ADR-0009), the active mode's panel, results card. One results card serves both modes. The mode last used is remembered per browser (a browser that last used the former Ask tab opens Filters). Panels stay mounted, so switching modes keeps the text in each.

| Mode | Spec |
|---|---|
| Filters | One monospace search box with a filled **Run** button; example searches as clickable chips; "Show SQL" reveals the compiled SQL and its bound values in an `--inset` block; "Edit as SQL" opens it in SQL mode with values written in; notes (such as a field read from `unmapped`) in secondary text. First-time default |
| SQL | The CodeMirror editor and Run, as below |

**Ask AI** is its own page, search first (D256), left-aligned: the prompt is the first thing under the title, at most 880px wide, on the `--inset` fill with a `--border-control` edge, `text-md`, two lines growing to six, the accent ring only on focus, placeholder "Ask about your logs" (a tooltip says a KQL or SPL query works too, and one muted line says so when the text reads as one), and **Ask** inside the box at its right edge, the page's one filled button once there is text (outlined while empty). Under it one 28px row of three facet chips in the `FilterBar` style: **Time** (the five presets of 6.0, the one time control), **Sources** ("All N" or the chosen ones, a list of checkboxes), and **Model** (the provider's name with its Local or Cloud badge; "None" with no provider). With a cloud model, one muted line "Your question is sent to <provider>" under the chips. Then the suggestions (before the first question only), then the answers at full content width, newest first, each separated by a hairline. **New question** is a secondary button in the page header. Each turn is a block, never a chat bubble: the question as a heading with its time and the Local or Cloud badge at the right of the heading line, progress steps while it works, the answer (a semibold headline written by code from the rows, then up to five statements as bullets, each followed by the short event ids it cites as mono badges, and a muted line naming the model; a muted note when statements were removed or there is no summary), the results table (entities as links, times in the viewer's zone with UTC on hover (D204); for a library answer with group keys, a last column with a **Show events** link per row that opens Logs on that row's events), **Open in Logs** (the answer's SQL in the Logs SQL mode, with the page's time range and sources, where it can be changed, saved with the question as its origin, or scheduled), and a collapsed **How I got this** (where the query came from, what the model said about its query labeled as about the query and not the rows, the SQL, the check, sources read, time, model). Statements never appear without a citation (ADR-0042 C1). A follow-up typed in the prompt refines the newest answer, the one directly under the prompt; the turns still go to the server in the order asked. New question starts over. The query runs at once when it passes the guard; with `ask.auto_run` off the block shows an outlined **Run query** instead (ADR-0042). A line under the question says how it was routed: "From the query library: <name>, today, 1 filter", or "Treated as a question about your data"; a question routed as general guidance says "Treated as general guidance. **Check your data instead?**" and the link asks again as a data question in the same block. With no provider, the Model chip reads "Model None", one line says "No AI provider is set up. Logs works without one." with **Add a provider** for admins, and Ask AI lists up to three library queries matching the words, each opening in the Logs SQL mode. Hidden from auditors (an auditor opening `/ask-ai` lands on Logs).

| Element | Spec |
|---|---|
| Filter chips | Pill chips in `--accent-subtle`. Click to edit, `x` to remove, "+ Add filter" link. Chips and SQL stay in sync |
| SQL editor | CodeMirror 6 in `--inset`, Geist Mono 13px, 4 lines default, resizable. `Ctrl+Enter` runs. Guard rejections show inline under the editor in `--danger` |
| Results card | Header with count and timing, column header row (no fill, section 4), rows, pagination footer with totals |
| Row | Chevron, time, severity badge, key columns, message (ellipsis). Hover tints row. Click or Enter toggles expansion |
| Expanded row | Directly under the row, full width, `--surface-expand`. Title + category badge + classification badge + actions on one line; below it, a two-column field list on the left and the raw event on the right. Actions: **Investigate** (primary), Explain, Copy as JSON. The raw event has a **Copy** beside its label that copies the stored line byte for byte, shown once the full event has loaded. Each text or number field shows small **+** (Filter for), **−** (Filter out), and **Top** (Top values) buttons on hover or focus; they add to the Filters search and run it. One row expanded at a time by default |
| Empty / no results | Heading, one sentence, one action ("Widen time range") |

### 6.2 Investigation

A focused, saved page about one entity. Reached from an expanded row's **Investigate** action, a detection, or the Investigations list.

| Section | Spec |
|---|---|
| Header | Breadcrumb, entity title ("Failed SSH logins from 203.0.113.9"), owner and timestamp, status, actions (time range, Export report, Save investigation) |
| KPI cards | 3 to 5 cards: label, big value (`text-kpi`), one-line context. Values are computed from the evidence; color only for meaning (`--ok` for a good zero) |
| Finding | One card: the severity badge, a one-line headline, two sentences of plain-language summary, and a "Computed from the events below" line with a link to the query. AI-written findings carry event-id citations and the "unverified" label rules from SPEC 7 |
| Charts | Trends over time: a short line chart (`TrendChart`), at most 160 px tall (140 px by default), 1.5px lines with no area fill, smooth monotone curves that never dip below zero, values on hover or with the arrow keys, parts of a whole as separate lines with a printed legend, and the window before as a dashed `--text-muted` line where there is one (at least 3:1 on both surfaces in both themes; D179), named by what it is ("Same hour yesterday", "Same hour last week", "Same day 30 days earlier") with its own date in the tooltip. Top values: horizontal bars. Any vertical bar is at most 20 px wide. One line of dashed gridline at half, no printed values on the plot |
| Evidence | Compact events table with the same row and expansion behavior as Logs, plus "View all in Logs" |

### 6.2a Microsoft 365

Microsoft 365 has no area of its own (ADR-0052). Sign-ins, Mail, and Admin are **Logs views** (the Views menu sets the source, columns, and filters). Apps is a Type filter in AI usage > Inventory. The headline KPIs live in the Dashboard Identity section, and the Overview's charts and lists are the top of the Sign-ins view (D249). The person page has a Microsoft 365 section. Interrupted is still not a failure: Entra asked for more (MFA, register a method, stay signed in, an external challenge), and the Dashboard's failed sign-ins use the same split. Every number opens its rows in Logs (ADR-0039). With no Microsoft 365 source a view says "Needs a Microsoft 365 source" with **Add a source**.

### 6.2b Agents

Under AI, at `/agents` with tabs **Sessions**, **MCP servers**, **Accounts** (ADR-0038 section 6).

- **Sessions** is list and detail (6.0), with a KPI strip above the list (what Overview held): the list card (person, device, last activity, open or ended, tool calls, failed in `--warn`, its filters) on the left (5 parts), the open session in a sticky pane on the right (7 parts; its id in the address as `#session=<id>`). Below 1024px the open session takes the page with **Back to sessions**, and focus returns to its row. The pane: **Session on <machine>** (`text-md`), the person (the machine when names are hidden, D242), the account's tier badge, start and length, the session id in mono; the state notice "Content is not collected. Sizes and names only."; a strip of five `KpiTile`s counted by the server over the whole session (Requests; Tool calls with "N failed or blocked"; Tokens with in and out, or "Not reported" muted when telemetry sent none, never 0; Files with "N outside the folder"; Flags as on the row), zeros muted. Then the **timeline bar**: the steps loaded, one equal-width segment per step in order (by order, not time: tool calls are instants and idle gaps would hide them), drawn by the step type (D264): prompt `--series-ice`, tool call `--series-graphite`, tool result `--series-neutral`, file access hatched graphite, access (web and MCP) hatched ice, other a hollow `--text-muted` outline. The hatch marks the two types that reach outside the session (a file, the web, or an MCP server) and reads with no color at all. Two rules for a segment (owner, 2026-11-14): it is drawn exactly as the legend shows its type, and for a slice of a long session that is its majority type (ties by order), nothing else; and a tick below the bar, a third thin row in `--text-secondary` aligned with the segments by the same width rule as the notch row above, marks every segment that holds at least one step that reached outside, whatever its majority type, a single file access or access included, so the tick always means "something here reached outside". A slice's hover text gives its counts per type, then "N of these steps reached outside the session" when any did. The legend shows the hatch with a line and the tick with its own mark and a line, and the bar's spoken summary says how many steps reached outside. Every mark is filled inline from its series variable, never from a generated class; `print-color-adjust: exact` keeps the fills when printed; on a forced-colors display the series become `CanvasText`, so the marks keep system contrast and types differ by the hatch and the tick. A hatched mark is solid in its top half and diagonal stripes in its bottom half, in the bar and in the legend alike: below about 6px the stripes cannot draw, and the half-solid shape still sets it apart from its solid sibling at every width. A failed call is marked by a `--danger` notch above it (by the server's count: Claude Code bookkeeping never, D186); runs of one type are one segment, and past 280 segments the steps are cut into 280 equal slices, each in the type most of its steps have. The start and end times at its ends; a legend naming each type with the whole session's count from the server and the failed count; "The bar shows the first N steps; the counts are for the whole session." when the list is cut. A segment opens a step the view below lists (scrolled to, focused, marked for a moment): its first listed step, or for a step Conversation does not list (a second session start) the next one; with Flagged only its first flagged step, and a segment with none is dimmed, does nothing, and says "not flagged" on hover. The bar is one image with a spoken summary of the counts and adds no tab stops: the steps are reached in the list. Then **View** (Execution, Conversation) and **Show** (All, Flagged only), both in the fragment with their defaults left out (`#session=<id>&view=conversation&show=flagged`). Execution is one row per step: time with seconds, the type in words (Prompt, Tool call, Tool result, File access, Access), the tool in mono, what it touched in mono, the size, "Failed" in `--warn`, "Flagged". Conversation is by turn: the prompt with what it led to ("5 tool calls: Read 3, Bash 2"), its calls with their results, how the turn ended. When the steps list is cut, one line says how many of the session's steps show. **Show events in Logs** at the foot opens the session's records with its window. Execution rows name the type in words, so color is never the only cue.
- **MCP servers** shows activity (what ran, where); a server's tools show in its expanded row. Each row links to its entry in AI usage > Inventory.
- **Accounts**: Claude accounts the hooks plugin reported in the last 30 days, counted by tier (Company, confirmed; Company, reported; Company, not confirmed; Personal; Not checked), then one row per account with its tier, the evidence (the Entra sign-in that confirmed it, or what was looked for and not found), where the email came from, devices, sessions, and last seen. Tiers are text badges, Personal and not confirmed in `--warn`, never severity colors: nothing acts on a tier (ADR-0030 T5). With no organization email domains set, a note links to setting them.

### 6.2g AI usage

Under AI, with tabs **Services**, **People**, **Inventory** (ADR-0052). Inventory is the governance register of four types (AI services, agents, MCP servers, Microsoft 365 apps) with a Type filter and a Status filter that opens on Unreviewed, or on All with "0 to review" when nothing is unreviewed. Approve and Not approved are row actions here (admins, audited). Each row links to its activity on Agents where there is one.

### 6.2c Settings > Claude plugins

Admin only (D127). The package settings (source when there are several, deployment token: a new one by name or an existing one, server address, pilot users), then one card per platform (version, script SHA-256 in mono, devices and lost records in 24 hours with lost in `--warn` when above zero, **Download plugin** and **Download managed bundle**), then **Deployment tokens** (name, first 8 characters with an ellipsis, source, created, last used, devices with the host names on hover, **Revoke** with an inline confirm that says how many devices stop sending), then the four checks for a deployment.

### 6.2d Settings > Single sign-on

Admin only (F64, ADR-0013). Read only: status (On in `--ok`, Off, Not working in `--warn` with the reason), what the server uses (issuer, client ID, required groups, the redirect URI with **Copy**; the secret is "Set in the environment; never shown"), the variables to set, **Test sign-in** with its result in a `role="status"` line, and the people bound to an identity. Users and access links here.

### 6.2e Alerts

The queue of everything that fired (ADR-0037, ADR-0043), across the full content width; no narrow centered column.

- **Tabs**: Queue, Handling, Rules, Schedules.
- **Filter bar**: Time; State (Open with its count, Closed, Muted; default Open); Severity; Category (Detections, Saved searches, AI Watch, Source gaps); a text box for a person, device, or source (matches the title, subject, people, and devices). The count on the right is rows the caller can read.
- **No summary strip.** The restricted-sources note ("Some alerts are in sources you can't read. Ask an admin for access.") sits at the foot of the list, with no count (D243).
- **List and detail**: the list on the left (5 parts), the open alert on the right (7 parts, sticky under the top bar); stacked below 1024px. Rows: checkbox (deciders, open alerts), severity badge, title, then category, the number of changes and the count ("3 times today", "14 blocked or failed calls"), the end note in `--ok` when the condition ended, and last seen at the right. High first, then newest. The current row is on `--row-selected`. `#item=<id>` opens that alert in the pane, closed ones included.
- **Detail pane**: severity, kind, state, and the alert ID in mono; the title (`text-md`); What fired; Why it matters; Person, Devices, Address as entity links; When with the event count and source; the **Triage card** (verdict, confidence, the adjusted-by-check line in `--warn`, a one-sentence summary with cited ID chips, the model name with its Local or Cloud badge, **Open full investigation**, Run triage again); Next steps (numbered); then the action row: Reason, **Close** (the page's primary), Mute similar, and Show N events in Logs.
- Changes today, the evidence, the history, and Approve or Not approved move to the full alert page (6.2f) and AI usage > Inventory.
- **Bulk close**: selecting rows shows a bar above the list: "N selected", one reason, a note (required for False positive), **Close N**, Clear. Each alert is closed and audited on its own.
- Severity badges follow section 2 (Critical and High solid, Medium a dot and its label); gaps carry Medium.
- **Handling** (D261): whether alerts are being handled, for the alerts the Queue shows the viewer. The filter bar holds Time only (30 days by default). A strip of four `KpiTile`s: Time to close, median and 90th percentile (in plain words, "2 d 4 h"; "None closed" muted when none; each opens Alerts > Closed for the same window), Overdue now (`--warn` when any, the severities past their days as the context line), and Open now (every open alert; opens the Queue). Then **Opened and closed**, a `TrendChart` by day in the install time zone (Opened in `--text-secondary`, Closed in `--ok`, never a severity or the accent color), beside **Open by kind** (the Category labels, each count opening the Queue with that Category; View all); then **By severity**, one row each for High, Medium, and None: open now (opening the Queue with that Severity), the overdue days, overdue now, closed by a person, median, and 90th percentile. Zeros are plain muted text, never links. While loading, tiles and cards keep their shape with `Skeleton`; a failed read shows `InlineError` with Retry and "Could not load" in the tiles; restricted alerts show the D243 note, never a count.

### 6.2f Full alert page

Record template at `/alerts/<id>` (D229 option B, ADR-0052). The rail marks Alerts.

| Part | Spec |
|---|---|
| Header | Breadcrumb (Alerts / ID), title (`text-xl`), a line of severity badge, state, kind, first seen, last seen, source. Actions: Copy link, Mute similar, **Close alert** (primary) |
| Summary | One sentence written by code from the events, entities as links, then "Computed from the N events below." |
| KPI row | Up to 5: Events, People, Devices, Addresses, and one rule-specific figure |
| Triage card (main) | Verdict, confidence, who ran it and when, model name and badge, Run again. The adjusted-by-check notice when the check removed a statement. Then two columns: **Reasons** (each a sentence followed by its cited ID chips) and **Cited events** (ID, time with seconds, event, key values in mono). Selecting a chip highlights its row (`--row-selected`, chip in `--accent-subtle`). With no model: one line, "No model is set up, so there is no verdict. The evidence pack below is computed from the events and works without one.", and Add a provider |
| Evidence pack (main) | Table: Check, Window, Result, Events. Each Events count opens its rows in Logs. A result that counts against the alert is `--warn` text; never a severity color |
| All events (main) | Compact events table, first 6, Show N more, View all in Logs |
| Pivots (side) | One row per person, device, and address: entity link and one line of context |
| Next steps (side) | Numbered, per rule |
| Details (side) | Rule (link to Alerts > Rules), ATT&CK IDs, source, grouping |
| History (side) | Newest first |

Model output rules are unchanged: every statement cites event IDs, failed citations are removed and the removal is shown, log content renders as text.

### 6.3 Health, Dashboards, Ask, Settings

- **Health** holds what Overview used to (F55, ADR-0034 rows 11 to 16), answering "am I blind?" (layout: D255). Tabs (ADR-0052): **Sources** (Type: Events, Enrichment feeds), **Collectors** (endpoint agents and watched devices), **Delivery**; a tab carries only a problem count (Unhealthy plus Needs attention on any of its types), outlined in `--warn`, and nothing at zero; no totals. Under the tabs, one `FilterBar` row: **Status** as the segmented control with counts (All, Problems, Paused, Healthy; Problems is Unhealthy and Needs attention), **Type** as a facet, and the count at the right ("8 sources", "2 of 8 sources"); both in the fragment (`#type=enrichment&status=problems`, defaults left out). The damaged-files notice (quarantined files) counts under Problems and stays listed under every Status. A tab with nothing listed shows no Status row. Then four KPI tiles in one strip with hairline dividers, the Dashboard's `KpiTile` (label as `PanelTitle` with its (i), value in `text-kpi`, one context line, the value opens its detail): Events, last 24 hours (compared with a usual day only after 7 full days of history and only over sources that have them, otherwise "Not enough history yet (N of 7 days)"), Sources healthy ("N of N", in `--warn` as a whole value when not all, the same count as the Dashboard's tile; the quiet sources, gaps, longest wait as its context line), Open alerts (the newest named), and for admins Alert delivery ("0 failed" with "All delivered" or the failing targets as context). Every value is a number in `--text` except that warn case. While a tile's own data loads its value and context line are `Skeleton` bars of their final height; tabs and filter counts show no number until their data is there; nothing reads zero or all-clear before it is known. A read that fails shows "Could not load" with Retry in the tiles it feeds, the error above, and no counts that depend on it. A three-column card lists detections (grouped by rule or search with their total and runs), paused schedules, and failed deliveries, shown only when one of them has something; there is no all-clear sentence. The list is a `Card` titled by its type. **Sources** is one row per source that brings events (files, syslog, OpenTelemetry, Loki, Microsoft 365, the Anthropic admin API), problems first; enrichment feeds are judged by each feed's update interval (F59). Columns: Source, Status (a dot and word: "Flowing", "Gap", "Quiet 85 min", the time since its newest dated event, the same time "Idle" and "No events for" use), a line sparkline of events per hour on a shared hour axis in local time (UTC in tooltips, the zone named under the list) scaled to its own busiest hour with gap hours shaded in `--danger` at low opacity, Peak ("25/h", right-aligned mono; nothing is printed on the line), 24 hours, Per minute, and Last received (`When`: local time, UTC on hover, the age muted beside it from 1400px). A row is one line high unless it has a sentence. Each gap is a sentence under its row in `--danger`: "No events 2:00 to 7:00 AM (5 h). Other sources kept flowing."; the quiet sentence is not repeated under it. A source that is only quiet (no gap hours, not in error) is drawn greyed: dot `--text-muted`, name and numbers `--text-secondary`, the line `--series-neutral`, at most one sentence ("No events for over 1 h"). An idle source (marked Quiet is normal and silent inside its days, D260) is drawn the same way with the word "Idle" and one sentence ("No events for 2 d (normal for this source)"), no gap shading or gap sentence, and counts as healthy; Sources healthy names them in its context line ("1 idle (normal)"). An error stays `--danger`. Drawing only: what counts as quiet, a problem, or healthy is the server's. `/overview` opens Health > Sources; Home always opens the Dashboard (owner, 2026-11-12). The product mark in the top bar links Home. Page rollups, Backups, and Speed are in Settings > System, the same page with its Type (Backups, Page rollups, Speed) in the same one-row bar and no KPI strip.
- **Dashboards** use the Investigation card grammar (cards, KPIs, simple bars) for scheduled-search panels (SPEC 5.5). First in the nav and always the landing page (owner, 2026-11-12, replacing ADR-0031's Health without a panel). A blind state is said once, in the Needs you list (ADR-0052 section 3.9), and on Health. Panels are a **tile** (a sixth: name, headline number, label, trend, flag; no table), a third, a half, or full width; a label-and-count result can show as bars (D82). Order on the page: see **Dashboard order** below. There is no separate list of flagged panels: a flagged panel's alert is a row of the Needs you list like any other alert, and the panel itself carries its flag. Sections each have a plain heading and their count over a hairline. The headline is `text-kpi`, tabular, and links to the rows behind it; a zero on a panel with a flag set is `--ok`. Labels say what is counted ("3 addresses"), from the owner's label or the result's first column, never "rows". Flags read in plain words ("3 addresses over threshold (0)") in `--warn`, with an outlined `--warn` **Flagged** badge; severity colors only when the panel carries a severity. Tiles sit in their own row of the section (two per row on phones, six on wide screens) with one line each for name, number and label, and flag state, so nothing wraps and nothing floats. The trend line shows from the third run. A section with one card gives it the full row. The page header carries the page's time window, the five presets of 6.0 (**1 hour**, **24 hours**, **7 days**, **30 days**, **Custom**; remembered in the browser) with its dates; freshness is only in the top bar. An empty cell in a user column says "No user parsed" on hover. Layout controls appear only in Edit layout: panels drag within and between sections (the drop place shows as an accent outline), each panel has a **Section** list and **Earlier** / **Later** for the keyboard, and each section heading has Rename, Move up, Move down, and Delete (its panels go to No section). An empty section shows a dashed drop area. Section order is stored, not derived from panels (D100). Panels never show developer text: when columns are hidden, the button reads **View all** (ADR-0034).
- **Dashboard order** (ADR-0052). Header (title, dashboard picker, time range, Edit layout; no primary). **Needs you** (blind rows pinned first on `--warn-tint`, then High and Critical alerts, then other alerts, then AI review items; columns badge, kind (its content's width), subject as an entity link (at most 220px, cut by `Truncate`), title (the rest of the row, two lines at most), time (D257); five rows after the blind rows, the rest behind **View all** at the top right of the card, which opens Alerts (D254); the restricted note at the foot with no count; hidden entirely when empty). A **KPI strip** for the window (Open alerts, Failed sign-ins, Sign-ins outside approved countries, AI services in use with "N to review", Sources healthy in `--warn` when not all; the same server count, `source_summary` on GET /api/overview, as the Health Sources tile). Then the sections, each shown only when the viewer has its source: **AI Watch**, **Identity**, **Attacks and access**, **Detections**. Then the owner's panels.
- **Needs you list** (ADR-0052 section 3.9, replacing the Health banner of D243; the D243 restricted note stays):

  One list on the Dashboard holds everything that needs the viewer.

  | Order | Rows | Look |
  |---|---|---|
  | 1 | Blind rows: source down, detection paused or stopped (D236), template missing (ADR-0050) | Pinned first. `--warn-tint` row with a 2px `--warn` bar on its left edge and an outlined `--warn` badge. Never visually equal to an alert row, and never a severity color |
  | 2 | High and Critical alerts, newest first | Severity badge |
  | 3 | Other alerts, newest first | Severity badge |
  | 4 | AI review items (link to AI usage > Inventory) | Severity badge, kind "AI review" |

  - Blind rows are never folded under "N more"; the cap of rows applies to orders 2 to 4.
  - The D243 restricted note stays at the foot of the list, with no count.
  - There is no separate Health banner and no Sources line at the bottom; a blind state is said once, here, and on Health.
- **Default sections** (ADR-0038 edit 10), after AI Watch and before the panels, each shown only when the viewer has its source, in the page grammar: a header with what it is from and, once, "Changes against the previous 7 days"; a KPI strip of 4 to 6 cards (`text-kpi`, `text-kpi-lg` from 1500px; the change as a neutral pill beside the value; a two-line context; a card that needs a setting says so, "Set approved countries", instead of a number); then a chart and a top-N table side by side (3fr / 2fr from 1500px, halves from 1024px, stacked below). **Identity** (Microsoft 365): failed sign-ins, sign-ins outside approved countries, inbox rules and forwarding, app consents (blocked as context), admin role grants, Conditional Access edits; failed sign-ins as one `--warn` line, hourly for 24 hours and 7 days and daily for 30 days, with the window before as a dashed line and the failure rate in the caption; top failing users. **Attacks and access**: sign-in failures from external addresses (not in Internal networks), attacking addresses, countries, VPN logins outside approved countries; failures by host as small multiples (one row of bars per host on its own scale, bars at most 20 px wide, peak and total printed); top sources by country and network. A note asks for company egress while none is listed. Top sources with no country say why instead of "Unknown": Not an address (the field holds something else), Not a public address, Not in GeoIP file (the file's install date in the tooltip, and a note under the table with Update GeoIP for admins), or No GeoIP file. **Detections**: matched events (distinct events, with rule matches as the context line, D221), rules that matched (of N enabled), hosts and users involved; matches by rule as small multiples; the hosts and users involved. With 24 hours the charts go by hour. **Every number opens its rows** (ADR-0039): a KPI value, its change pill (the window before), a chart point (that hour or day), a small-multiples row, a sub-line such as "2 blocked", and a top-N row (an entity page when there is one, else Logs) each open Logs with the query behind it, already run, with a line above the editor saying where it came from ("From Dashboard > Identity > Failed sign-ins, Oct 24, 12:00 AM to Oct 30, 11:37 AM UTC"). They show a pointer and "Open 12 events in Logs" on hover; a zero still opens its (empty) search. Back returns to the Dashboard at the same window and scroll position. **No comparison without history** (owner 2026-10-30): a section, and AI Watch, compares only when every source that counts toward it has data for at least 90% of the window before; otherwise the header reads "No comparison yet: data starts Oct 21", each card shows "Not enough history for comparison" in place of the change pill, and the failed sign-ins chart drops its dashed line.
- **Detections section** (ADR-0052):

  | Part | Spec |
  |---|---|
  | Shown when | At least one rule is enabled and the viewer can read a source it runs on |
  | Header | "Detections", the window, and "Changes against the window before" once |
  | KPI strip | Matched events (distinct events; rule matches as the context line, D221), Rules that matched (of N enabled), Hosts involved, People involved |
  | Chart | Matches by rule as small multiples: one row of bars per rule on its own scale, bars at most 20px wide, peak and total printed; hourly for 1 hour and 24 hours, daily for 7 and 30 days |
  | Table | Top hosts and people involved: entity link, matches, rules, last match |
  | Links | Every number opens its rows in Logs (ADR-0039). A rule name opens Alerts > Rules on that rule |
  | Blind state | When detection is paused or stopped on any source the section's header carries the `StateNotice` and the affected figures read "Not running", never zero |
  | Empty | No rules enabled: "No rules are enabled." with **Enable rules** (opens Alerts > Rules) |
- **AI Watch** (ADR-0035 Part 2) sits under the Needs you list and the KPI strip on the Dashboard when there is AI use or anything to count: a header that says what it is compared against and Open AI usage (it follows the page window; with 24 hours the chart still shows 7 days, since use is counted by day); the KPI cards whose source is set up in one row from 1024 px (a card whose source the install lacks takes no card: one muted "Not set up: ... (needs ...)" line with Add a source, under the cards; F62) (people are counted as people only; devices or addresses with no person matched get their own line under the value, "3 more devices not matched to a person", linked to the list, never added in: D115) (two per row below, the fifth spanning the row; labels at most two lines, full on hover): value in `text-kpi` (`--ok` for a zero), the change against the previous period of the same length as a neutral pill beside the value ("↑ 1", "same"; the full sentence in its tooltip), and one context line. A card the viewer cannot read says Restricted, never zero. Under the cards, **New in 24 hours** lists what was first seen in the data (never a review decision: D116), each linking to its alert. **AI use, last 30 days** (with less than 7 days of data, "AI use since Oct 21" over the days that exist): one line each with daily points for approved, unreviewed, and not approved, in the AI status colors of section 2 (never a severity color), values and the total on hover, a printed legend with totals, and an `aria-label` summary. **Top services**: service (entity link), status badge, people ("·" with a tooltip when the events name no person), devices, last seen; **View all** opens AI usage. Every AI Watch number opens its rows in Logs the same way as the sections (ADR-0039); new agents and MCP servers open AI usage > Inventory. AI Watch review items are on Alerts with a High or Medium badge (severity tokens); Approve and Not approved are row actions in AI usage > Inventory (admins).
- **Entity page** (product pass step 2, DESIGN 6.2): Investigations on an address, person, or machine leads with one sentence ("2,619 failed sign-ins against ftp-01 over the last 7 days, 0 succeeded. From Netherlands, AS64500."), then KPI cards (sign-in attempts, succeeded, users tried, hosts targeted, first and last seen, country and network for addresses), then **What it did**: activities grouped by outcome, each with a real example line (values intact, never the number-masked pattern), its user and target as links, and View in Logs; then hosts and users it touched. The lane graph sits below, open and foldable. Times use `components/When.tsx`: local, UTC on hover. A person page leads with one sentence and a KPI row (Open alerts, Sign-ins, Devices, Addresses, AI services), then in the main column Open alerts, Activity per day, **Microsoft 365** (one table with a Sign-ins, Mail, Admin switch and Open in Logs; shown only with a Microsoft 365 source), and AI use; in the side column Accounts, Devices, Addresses. Primary action: **Open in Logs**. With names masked the title reads as the masked label and a Names hidden notice sits above the summary.
- **Pivot rule** (product pass step 2): every IP address, user, host, and AI service value anywhere (search results, expanded rows, dashboard panel tables and bars, AI usage, Health) is an `EntityLink` to its page in Investigations (`/investigations#ip=203.0.113.9`, `#user=`, `#host=`, `#service=`), with View in Logs from there. One component, `components/EntityLink.tsx`; a column is an entity by name (`lib/entity.ts`). Links are `--accent-text`, monospace with the data, and real links (middle-click works). A link inside a clickable row opens the entity, not the row. Placeholders (`-`, empty) stay text.
- **No sideways scrolling** (F54): at desktop widths no page, card, or table scrolls sideways. Flex and grid children that hold text or tables get `min-width: 0`; long identifiers and paths wrap anywhere (`overflow-wrap: anywhere`); times in tables follow the time format in section 3. Only the search results grid, whose columns the user picks, may scroll (`data-scroll-x`). CI opens every page and tab at 1280px with the demo lab's data and fails on any sideways scroll (`scripts/check-layout.py`).
- **Data attribution** (F52): a license credit such as "IP Geolocation by DB-IP" is `--text-muted` small text, once per page (below the results table), never in the accent color and never repeated per row. **About and licenses** (Settings > Records) lists each outside data source, its use, license, and attribution in one table.
- **Reports** (D67) is a pinned rail entry: the Table template, with **Generate report** as its primary button; visible to roles that can read reports.
- **Ask AI** is its own page under Investigate, right below Logs (D206, replacing D180's Ask tab of Search; 6.1). Auditors do not see it. Before the first question, **Try one of these on your data** lists up to six example questions as outlined buttons, from the library queries the viewer's sources support (D182); one click asks it.
- **Audit log** (Settings > Records) has Activity and AI calls tabs over a dense table, filters in one row, rows that expand to show detail as text, Load older entries at the foot, and Export CSV as the primary button.
- **Settings** pages (Users and access, Sources, AI providers) are list + detail forms with labels above inputs, help text below, and a sticky save bar. Only the sections a role can use are shown. An Auditor sees Records.

---

## 7. Components

| Component | Spec |
|---|---|
| Primary button | `--accent` fill, `--on-accent` text, 32px tall, 5px radius. One per page, only where one exists. In the `PageHeader`, last on the right. A List-detail page puts it in the detail pane |
| Secondary button | Transparent, 1px `--border-strong`, `--text` |
| Badge | Severity: Critical and High are solid (3px radius, 12px at 600). Medium, Low, and Info are a 7px square dot and the label in `--text`; Low and Info dots are `--text-muted` |
| AI status badge | A dot and the label. Approved: `--local-tx`. Unreviewed: hollow, outlined in `--accent-text`. Not approved: hollow, outlined in `--warn`. Never a severity color |
| Filter chip | 12px radius pill, `--accent-subtle` background (Logs, until the `FilterBar` replaces chips there) |
| Text input and checkbox | Edge in `--border-control` (3:1). Labeled buttons keep `--border-strong` |
| Change pill | Neutral pill beside a KPI value with the arrow glyph and the amount, or "same" |
| Cited ID chip | Mono 12px on the Info pair; selected: `--accent-subtle` with a 1px `--accent-text` border. A real button wherever a click selects the cited event (the full alert page); plain text where there is nothing to select. An id that fails the citation check is outlined in `--danger`, never filled |
| State notice (`StateNotice`) | One line, 1px border with a 2px `--warn` left bar; blind notices add the `--warn-tint` background |
| Card | `--surface`, 1px `--border`, 6px radius, title as a `SectionTitle` or `PanelTitle` |
| Card anatomy (`Card`, D254) | One header row of one height (40px), 12px sides and 8px top and bottom, no fill, a 1px bottom border; in it the title (`SectionTitle` for a page section, `PanelTitle` for a panel inside one), an optional `About` (i) for how its rows are counted, an optional muted note of a few words that shortens before the title does, an optional small status tag ("2 changed"), and one optional action (`CardAction`) last on the right in `--accent-text`: **View all** when it opens the full list of what the card shows, the page's name only when it leaves the card's subject ("Open AI usage"). A sentence or a state notice about the card is the first row of the body, never in the header; controls (Group by, Export, a "Hide ..." checkbox) go in the card's filter bar. Cards side by side stretch to the tallest. `scripts/check-layout.py` fails on card headers of more than one height on a page or a header with a fill |
| Section title (`SectionTitle`) | The title of a page section (AI Watch, Identity, Attacks and access, Detections, and the AI usage, Agents, and Health equivalents): `text-md` 600 in `--section-text` on a `--section-bg` pill, 3px radius, no outline. Never clickable-looking: no link blue, no hover state |
| Panel title (`PanelTitle`) | Titles inside a section (Top services, AI use since, Failed sign-ins per day, Top failing users) and KPI labels: 14px, 600, sentence case, `--text`. No upper case, no extra letter spacing. Clearly smaller than a section title; no hover state |
| Table header | No fill. 12px at 500 in `--text-secondary` over a 1px divider, sortable on click |
| NULL value | `·` in `--text-muted`, never blank, never "null" |
| Command palette | `Ctrl+K` / `Cmd+K` and the top bar search; opens under the search at its width (680px), `--surface`, 6px radius. Sections: Recent (empty query), then **Ask AI: <typed text>** when the text reads as a question (more than one word, and it ends with "?" or starts with how, what, who, when, why, which, show, list, or did; D181), then Addresses, People, Hosts, AI services (found by the server in the viewer's own sources, last 30 days; ADR-0038 edit 10), Navigate (with **Logs** and **Ask AI**), Actions, Saved searches, Sources, and a **Logs** section with **Search events for "..."** last. An entity opens its page. Addresses and hosts in the data font, with country, network, and event count. Flavor names (Séance, Grimoire, Ossuary) and former labels (Search, Ask) resolve as aliases only |
| Ask AI slide-over | Ask AI from any page (ADR-0042): the palette's **Ask AI** item (on the Ask AI page it stays there), titled **Ask AI**, or **Ask AI: <typed text>** for a sentence typed in the palette (first for a question, otherwise beside Search events for, in the **Logs** section), opens a 560px panel on the right with the same answer blocks, last 24 hours on the viewer's sources. Escape or the close button closes it. For asking only; events still expand inline |
| Truncate (`Truncate`, D257) | Long identities in cells; the cut is CSS only. An email's "@domain" follows in `--text-muted` and is cut first, then the local part, so nothing overflows its box. Any other name (source id, host, app, network, file) is cut in the middle, keeping its start and its last 8 characters. Inside a link or button, it carries the full value as title and accessible name; a plain cell is a tab stop, shows the full value on hover (title) and under the cell on keyboard focus, and is read as its text. Copying any selection gives each value whole on one line (`lib/copyWhole.ts`). `EntityLink` uses it, in the link color. Sentences such as alert titles never use it: they wrap to two lines, then cut, the full text on hover |
| Toasts | Only for background job completion. Errors appear inline where they happened |

Icons: Lucide, 16px in nav and buttons, 14px in tables, 1.5px stroke. No emoji anywhere.

---

## 8. Do / Don't

| Do | Don't |
|---|---|
| Labeled nav, pages only (Pinned and Recent in their own labeled regions under the pages, D258, D259); tabs in the page | Sub-pages in the rail; tabs that repeat the rail; icon-only navigation as the default |
| The page's own title and tabs on every page | Pages without a clear "where am I" |
| One filled primary button per page, where one exists | A row of equal text commands |
| A blind state pinned first on a warn tint | A source-down row that looks like an alert |
| Help in popovers and buttons; state notices always shown | Paragraphs that explain the page |
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

- WCAG AA contrast (4.5:1 text, 3:1 large text and UI) in both themes; checked per token change. Chart series are UI: at least 3:1 on `--surface` and `--surface-head`, so border tokens are never a series color (`--series-neutral` instead).
- Every interactive element is a real `button`, `a`, or input; visible focus ring; `Esc` closes any layer.
- Tables support arrow-key row movement and `Enter` to expand; expanded rows set `aria-expanded`.
- Charts carry an `aria-label` summary of their values.

---

## 10. Terminal (CLI and TUI)

The CLI (`remnant`) and the Slice 6 terminal UI follow the same rules as the web console.

| Rule | CLI now | TUI (Slice 6) |
|---|---|---|
| Data first | Plain aligned columns; `json`, `csv`, `raw` for piping | Same table grammar as Logs: rows, expand inline with `Enter` |
| Status on stderr | Row count and timing go to stderr so stdout stays pipe-clean | Status bar at the bottom: rows, timing, source scope, server |
| Color | None by default in piped output. When a TTY: severity labels and errors only, honoring `NO_COLOR` | Same palette roles as section 2 mapped to 256-color: accent blue for focus, severity tints for badges |
| Safety | Log content stripped of control sequences before printing | Same; raw view renders text only |
| Layout | Truncate the last column to the terminal width with `…` | Left pane (sources, saved searches), main results table, bottom detail pane, `?` for keys |

The TUI gets its own mockups on the design canvas before it is built.

---

## 11. Token mapping (reference)

`tokens.css` carries these values; `scripts/check-contrast.py` (in CI) fails when the two differ or when a pair drops under section 9. `--focus-ring-top` is the focus ring inside the top bar. On the pressed fill (`--accent-subtle`) muted text takes `--text-secondary`: `globals.css` sets that for anything on the fill, since `--text-muted` is 4.47:1 there in dark.

```css
:root, :root[data-theme="dark"] {
  --bg: #0E1013; --top: #0A0B0E; --nav: #0E1013; --surface: #0E1013; --surface-head: #13161A;
  --surface-expand: #14171C; --inset: #0A0B0E; --border: #1F242B; --border-strong: #2E353F;
  --border-control: #5F6977; --text: #E4E7EC; --text-secondary: #9BA3B0; --text-muted: #7F8896;
  --series-neutral: #646D7D; --series-ice: #81DAEF; --series-graphite: #929CAB;
  --accent: #3A68E0; --on-accent: #FFFFFF; --accent-text: #7EA2FF;
  --accent-subtle: rgba(91,140,255,0.14); --row-selected: rgba(91,140,255,0.09);
  --warn-tint: rgba(232,188,98,0.08); --ok: #58C29A; --warn: #E8BC62; --danger: #F28B9B;
  --info-bg: #1A1E24; --info-tx: #9BA3B0; --sev-c-solid: #F2647A; --sev-c-on: #1F0409;
  --sev-h-solid: #F08A3C; --sev-h-on: #1A0E03; --sev-m-dot: #F0C46A;
  --local-bg: rgba(63,182,139,0.16); --local-tx: #7FD3B2; --cloud-bg: rgba(167,139,250,0.16);
  --cloud-tx: #B9A2FB; --focus-ring-top: #7EA2FF;
  --focus-ring: var(--accent-text); --panel-title: var(--text); --section-text: var(--text);
  --section-bg: rgba(148,163,184,0.12);
}
:root[data-theme="light"] {
  --bg: #FAFAFB; --top: #16181D; --nav: #FAFAFB; --surface: #FFFFFF; --surface-head: #F4F5F7;
  --surface-expand: #F5F8FE; --inset: #F1F2F4; --border: #E4E6EA; --border-strong: #C9CDD4;
  --border-control: #808896; --text: #16181D; --text-secondary: #4A5160; --text-muted: #636D7D;
  --series-neutral: #858D9C; --series-ice: #0D6A7C; --series-graphite: #262E3A;
  --accent: #2B5BD7; --on-accent: #FFFFFF; --accent-text: #2452C9;
  --accent-subtle: #E9EFFD; --row-selected: #EFF3FE; --warn-tint: #FCF5E4; --ok: #1C7656;
  --warn: #855100; --danger: #B0152E; --info-bg: #EDEFF2; --info-tx: #3F4654;
  --sev-c-solid: #B4162F; --sev-c-on: #FFFFFF; --sev-h-solid: #B8500A; --sev-h-on: #FFFFFF;
  --sev-m-dot: #8A5300; --local-bg: #E3F4EF; --local-tx: #1F6B57; --cloud-bg: #F1EBFE;
  --cloud-tx: #6D28D9; --focus-ring-top: #7EA2FF;
  --focus-ring: var(--accent-text); --panel-title: var(--text); --section-text: var(--text);
  --section-bg: #E6E9EE;
}
```

The last two lines of each block are aliases kept so existing components do not break: `--focus-ring` is `--accent-text`; `--panel-title` and `--section-text` are `--text`; `--section-bg` is `rgba(148,163,184,0.12)` dark and `#E6E9EE` light.
