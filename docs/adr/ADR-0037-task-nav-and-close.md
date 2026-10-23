# ADR-0037: Navigation by task, the morning answer, deep links, and one Close

Status: **Accepted** 2026-10-22 by the owner, with the answers in "Owner answers" below (they amend rows 16, 18, and 13). Product pass step 3, from `docs/ux/journeys.md` (approved). Recorded as D112 in `docs/SPEC.md`.

## Context

The journeys showed the menu follows how features were built, not what the lead is doing. The morning answer is spread across Dashboard, Health, and AI usage, which link to each other; an alert's link opens the Dashboard; a detection opens the rule list; a Health row opens Settings, which disagrees with it; and only flagged dashboard panels can be acknowledged, without a reason.

## Decision

### Nav, before and after

```
Before                                   After
------                                   -----
General                                  Dashboard            morning answer, then panels   (journey 1)
  Dashboard                              Alerts          3    what fired, open and closed    (journey 2)
Investigate                              Investigate
  Search                                   Search                                           (journey 3)
  Investigations                           Investigations
  Saved searches                           Saved searches
Detect                                   AI usage             AI Watch first (ADR-0035)      (journey 4)
  Detection rules                          Services, Agents, MCP servers, Claude usage, Review
  Schedules                              Health               sources, feeds, agents, devices (journey 5)
AI                                         Sources, Enrichment feeds, Endpoint agents, ...
  AI usage (5 tabs)                      Detect
System                                     Detection rules
  Health (5 tabs)                          Schedules
Settings (pinned)                        Settings (pinned)    Sources and connectors, ...     (journey 6)
```

| # | Change | Why (journey) |
|---|---|---|
| 1 | Top-level **Dashboard**, **Alerts**, **AI usage**, **Health** without group headings; **Investigate** and **Detect** stay groups | The four places the lead goes daily are one click and not buried under a heading of one item (1, 2, 4, 5) |
| 2 | **Alerts** is new: one list of everything that fired and needs a decision, open first, with a count badge | One queue to close from, instead of panels, rule runs, AI watch, and gaps in four places (2) |
| 3 | Order is the morning: Dashboard, Alerts, Investigate, AI usage, Health, Detect, Settings | Read top to bottom on a normal morning (1) |
| 4 | Settings stays pinned at the foot; **Add source** is also on Health > Sources | Adding a source starts where a missing source is noticed (6) |

### The morning answer (top of the Dashboard)

| # | Part | Decision |
|---|---|---|
| 5 | Sentence | One line from the open alerts, Health, and AI Watch: "2 things need you: a gap on paloalto_fw and 3 failed SSH bursts. Everything else is flowing." When nothing is open: "Nothing needs you. All 4 sources are flowing." |
| 6 | Three columns | **Needs you** (open alerts, newest first, each with Close), **Sources** (N of N flowing, gaps, longest wait; the Health tiles), **New** (first seen in 24 h: AI services, agents and MCP servers, admin and role grants, app consents; ADR-0035 data). Each row is one click from its explanation |
| 7 | Panels | The owner's panels sit below, unchanged (ADR-0034) |
| 8 | Health | Keeps its tiles and rows for detail; the Dashboard's Sources column links to it |

### Deep links

| # | From | Opens | Was |
|---|---|---|---|
| 9 | Alert message (Slack, Teams, email, webhook) | `/alerts#item=<id>`: that alert, expanded | `/dashboard` or `/ai` |
| 10 | A detection anywhere (status line, Needs you, Alerts) | Its alert: what fired, why, the matching rows with pivot links, and Close | Detection rules list |
| 11 | A source name on Health or the Dashboard | `/health#source=<id>`: its Health row expanded, gap shaded; Settings one more click from there | Settings > Sources |
| 12 | Settings > Sources | Shows the same gap note while it is within 24 hours, linking back to the Health row | Nothing |

### Close (owner answer 2)

| # | Part | Decision |
|---|---|---|
| 13 | What can be closed | An **alert item**: a flagged schedule run, a rule run with matches, an AI Watch item (ADR-0035 review queue), or a gap (D104) on a source with Alert if quiet on (owner answer 3; every gap still shows on Health). One table, `alert_items`, written when the thing happens; the existing per-dashboard acknowledgements are migrated to closed items (reason Benign or expected, note "Acknowledged before Close existed") |
| 14 | Reasons | True positive; Benign or expected; False positive (tune the rule); Needs follow-up |
| 15 | Note | Required for False positive and Needs follow-up; optional otherwise; up to 2,000 characters |
| 16 | Mute similar | Admins only (owner answer 2), optional, 1 to 30 days, expires on its own: new items with the same subject close themselves with reason "Muted until <date>" (and their own audit row). Subject is the schedule, the rule, the source (gaps), or the AI Watch kind and value. The Alerts list shows "N muted" linking to the list of mutes; unmute from there |
| 17 | Effect | A closed item leaves Needs you, Needs attention, and the Alerts count, for everyone who can see it. Reopen is allowed; the history (who closed, why, when, reopened) shows on the item |
| 18 | Who | Admins and Analysts close and reopen; only Admins mute; Auditors read. Each is audited `alert.close`, `alert.reopen`, `alert.mute` with the reason, note, and mute |
| 19 | Access | An item is visible only to viewers who may read every source its run read (the Restricted rule, ADR-0034 row 9); a restricted item counts as "1 restricted" with no detail |
| 20 | Case handoff | Closing with True positive or Needs follow-up offers Send to case target (ADR-0024) when one exists; never automatic |

## Consequences

- One queue and one verb for everything that fires; the morning answer can be one sentence because there is one source of open items.
- Alert messages and Health rows deep-link, so the journeys hit their targets (2: 4 clicks, 5: 2 clicks).
- New table and migration (additive); acknowledgements migrate; the Needs attention strip becomes a view of open items.
- Work, after review: nav and morning answer (one PR); `alert_items`, Alerts page, Close, mute, and deep links from alert messages (one PR); Health row deep link and the Settings gap note (one PR, F61).

## ATLAS / ATT&CK

No AI surface change: no model call in navigation, Close, or the morning answer. Close notes are user text: rendered as text, never parsed, and capped. Mute is a way to hide real activity (an insider muting a rule); it is admin only, bounded (30 days, then it expires on its own), audited, visible on the Alerts list, and closes items rather than dropping them, so the record stays (ATT&CK T1562 Impair Defenses, as the abuse case).

## Owner answers (2026-10-22)

| # | Question | Answer |
|---|---|---|
| 1 | Nav label for the queue | **Alerts** |
| 2 | Who may mute | Admins only; at most 30 days; a mute expires on its own; audited; the queue shows "N muted" with a link to the list |
| 3 | Which gaps become alert items | Only gaps on sources with **Alert if quiet** on; gaps still always show on Health. Alert if quiet is on by default for new sources, with a default threshold per source kind (Loki and syslog 60 min, Microsoft 365 3 h), editable |

Default quiet thresholds by kind, for new sources only (existing sources keep their setting):

| Source kind | Default |
|---|---|
| Syslog listener, Loki, file or folder, OTLP | 60 min |
| Microsoft 365 and other API connectors (content arrives late and in batches) | 3 h |
| Endpoint agent groups | 60 min |

A new source's default watch starts with no alert targets: a gap raises an alert item (Alerts, Needs you) and sends messages only once an admin adds targets. The admin edits or turns it off on Settings > Sources, as today (ADR-0014).
