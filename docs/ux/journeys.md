# Six journeys: what a security lead does here, and where the app makes them hunt

Status: **Approved** 2026-10-22 (project owner), with the answers below. Step 1 of the product pass; steps 2 to 8 build from it, in the order at the end.

## Who and how this was put together

**The person.** One security lead covering everything (monitoring, detection, response, AI governance, compliance) on a small team's install. Opens the app in the morning, gets pulled in by an alert during the day, and answers questions from leadership ("are people pasting data into AI?"). Has minutes per task, not hours, and needs each screen to say what it found.

**Method.** Journey mapping (design:user-research) against the app as built on main at `e5b579b` plus PR #246, and a design critique (design:design-critique) of the owner's screenshots of their install (Dashboard, Search expanded row, Health, AI usage > Services, Investigations on one IP), the install findings F41 to F61, and a walkthrough of the demo lab. Clicks are counted from opening the app or the alert: a click on a link or button, a tab, a choice in a list, or typing a value and pressing Enter each count as one. Scrolling does not count; **hunting** (reading a page to find where to go next) is called out separately because it costs more than a click.

**What "target" means.** The number of clicks the journey takes once the product pass is done, and the screens it goes through. It is the bar for the pass's definition of done: the owner does each journey on their install at the target, without hunting.

## Summary

| # | Journey | Today | Target | Biggest break |
|---|---|---|---|---|
| 1 | Morning check | 6 to 9 clicks over 3 pages, plus hunting | 1 to 2 clicks, 1 page | No page answers "anything wrong?" in one sentence; Dashboard, Health, and AI usage each hold part of it |
| 2 | Alert fired, investigate, close | 8 to 12 clicks, plus hunting | 4 clicks | The alert's link opens the Dashboard, not what fired; nothing to "close" with a note |
| 3 | Who is this IP, user, or host | 3 to 4 clicks from Search; not possible from most pages | 1 click from anywhere | Values are plain text everywhere except one button in Search's expanded row; the entity page has no summary |
| 4 | Is AI use safe this week | 5 to 7 clicks, and it cannot answer "who" | 2 clicks | No answer at the top; "who" is a raw address (ADR-0029 pending); no page per service |
| 5 | A source stopped logging | 2 clicks to the gap, then a contradiction | 2 clicks | Health says Needs attention; its click opens Settings, which says Reading, up to date (F61) |
| 6 | Add a new source | 4 to 6 clicks, then a separate trip to check it works | 4 clicks ending on proof it works | Saving a source ends on a settings table; whether lines parse is found later, in Search |

## 1. Morning check

**Job.** "Before anything else today: is anything broken, did anything fire, and is anything new I should know about?" Done when the lead knows the answer and has either opened the one thing that needs them or moved on.

**Target: 1 to 2 clicks, 1 page.** The **Dashboard's top section** is the morning answer (owner, 2026-10-22: one landing page, no new page): one sentence ("2 things need you: a gap on paloalto_fw and 3 failed SSH bursts. Everything else is flowing."), then what needs the lead, whether sources are ok, and what is new, each one click from its explanation. The owner's panels sit below it. Health and AI Watch details are one click deeper.

**Today**

| Step | Screen | Click | What the lead sees |
|---|---|---|---|
| 1 | Home | (opens) | Dashboard, if any panel exists; Health otherwise |
| 2 | Dashboard | | Health strip ("1 source with a gap"), Needs attention list, then panels whose headlines are row counts with wrong labels ("79 devices" on SSH logins) |
| 3 | Dashboard | Open Health | Health: four tiles, status line with detections, Sources rows |
| 4 | Health | Needs attention tile | Back to the Dashboard (loop) |
| 5 | Health status line | a detection name | Detection rules: the list of all rules, not the run that matched |
| 6 | Nav | AI usage | Services tab, last 24 hours |
| 7 | AI usage | Range: 7 days | People 0, raw addresses |
| 8 | AI usage | Agents, then MCP servers | New agents and servers, if any, in separate tabs |

**Where it breaks**

| Step | Problem | Severity |
|---|---|---|
| 2 to 4 | Three places hold part of the answer (Dashboard strip, Health, AI usage), and each sends to another; the Needs attention tile and the Dashboard link to each other | High |
| 2 | Panel headlines are row counts under the wrong noun; nothing ranks what matters (F47, ADR-0034 headlines not set on the owner's panels) | High |
| 5 | A detection opens the rule list, not its matches, so the lead searches for the rule and runs it again | High |
| 6 to 8 | AI is a separate trip with four tabs and no top-line answer | Medium |
| any | Slow first load shows a memory error, then the page fills on refresh | High |

**Target flow:** the Dashboard's top section shows the sentence and the list: 0 clicks if nothing needs them; 1 click to open an item; 1 more to act (Close, or Investigate).

## 2. Alert fired, investigate, close

**Job.** "Slack says something fired. What is it, is it real, and how do I record that it is handled?" Done when the lead has decided (real, benign, or needs more), recorded why, and the alert stops nagging.

**Target: 4 clicks.** Alert link (1) opens the **run page**: what fired and why in one sentence, the matching rows, and the entities in them as links. Entity (2) opens its page with the summary. Back (3), **Close** with a reason and an optional note (4): audited, clears Needs attention, and is sent to the case target if one is set.

**Today**

| Step | Screen | Click | What the lead sees |
|---|---|---|---|
| 1 | Slack | Open in Remnant | The Dashboard, not the run (`/dashboard` for searches, `/ai` for AI watch) |
| 2 | Dashboard | | Hunts for the panel among sections; Needs attention may list it |
| 3 | Panel | Open in Search | Search with the panel's SQL over its range |
| 4 | Search | expand a row | Fields as OCSF codes (`class_uid 3002`, `status_id 2`, `template_id`) |
| 5 | Expanded row | Investigate | Investigations on the first person, address, or host in the row only |
| 6 | Investigations | | Lanes canvas; no summary; activities as masked templates ("from #.#.#.# port #"); Targets empty |
| 7 | Browser | Back, Back | Dashboard |
| 8 | Needs attention | Acknowledge | Cleared, with no reason or note |
| 9 | (none) | | Case handoff happens only if the alert target was a case webhook; nothing records "benign, PA log forwarding restart" |

**Where it breaks**

| Step | Problem | Severity |
|---|---|---|
| 1 | The link loses what fired; every alert lands on the same page | High |
| 4 | Codes instead of labels; no +, -, Top buttons on values (DESIGN 6.1) | Medium |
| 5 | Only one entity per row can be opened; other values are text | High |
| 6 | Entity page has no answer ("2,619 failed SSH attempts against ftp-01 over 7 days, 0 succeeded"); KPIs from DESIGN 6.2 missing | High |
| 8 to 9 | Acknowledge has no reason or note, and only flagged dashboard panels can be acknowledged (rule matches outside a panel and gaps cannot); no "closed" state anyone else can see | High |

## 3. Who is this IP, user, or host

**Job.** "This value showed up somewhere. Who or what is it, what did it do, and should I worry?" Done when the lead can say it in one sentence.

**Target: 1 click from anywhere.** Every IP, user, host, and AI service value in every table, panel, expanded row, AI usage column, and Health row is a link (one pivot component) to its **entity page**: a one-line finding, KPI cards (attempts, successes, users tried, hosts targeted, first and last seen, country and network), activities grouped by outcome with real values, targets, and **View in Search**. The lane graph sits below the summary, collapsible.

**Today**

| Step | Screen | Click | What the lead sees |
|---|---|---|---|
| 1 | Search, a result | expand a row | Fields |
| 2 | Expanded row | Investigate | Investigations, lanes for the first entity in the row |
| | or: Investigations | type the value, Investigate | Same page (the type is now detected, F56) |
| | AI usage Who, Dashboard tables, Health | | The value is text; copy it, open Investigations, paste |

**Where it breaks**

| Step | Problem | Severity |
|---|---|---|
| everywhere but Search | No pivot: values are not links (owner critique, pivots) | High |
| 2 | Entity page leads with an empty canvas; no finding, no KPIs; Targets empty; masked activity patterns read as broken | High |
| AI usage, Dashboard | "Who" is an address: no DHCP or VPN resolution until ADR-0029 (PR #224) | High |
| any | Times in UTC in some places and local in others | Medium |

## 4. Is AI use safe this week

**Job.** "Leadership asks: are people using AI we have not approved, and is company data going there?" Done when the lead can answer with numbers and names, and has acted on anything new (approve, block, or ask someone).

**Target: 2 clicks.** AI usage opens on **AI Watch** (ADR-0035): five KPI cards with change against last week, the review queue (new service, new agent or MCP server, consent grant, sensitive data), and top services. A service name (1) opens its **service page**: who (people and machines, ADR-0029), when, trend, review history, and Approve or Block (2) there, not in a dropdown on every row.

**Today**

| Step | Screen | Click | What the lead sees |
|---|---|---|---|
| 1 | Nav | AI usage | Services tab, 24 hours |
| 2 | Range | 7 days | Services with status dropdowns per row; People 0; Who is raw addresses |
| 3 | Agents tab | | Agents seen |
| 4 | MCP servers tab | | Servers and allowlist status |
| 5 | Claude usage tab | | Per person for Claude Code only |
| 6 | Review and alerts tab | | Settings, not findings |
| 7 | (none) | | No per-service page; no "since last week"; consent grants and sensitive-data signals not in one place |

**Where it breaks**

| Step | Problem | Severity |
|---|---|---|
| 1 | No answer at the top; the page is a workbench | High |
| 2 | Cannot say who; F46 fallback to 24 h still shows on slow loads | High |
| 2 | Approve and Block inline on every row invites mistakes and has no history beside it | Medium |
| 3 to 6 | Four tabs to read one story | Medium |

## 5. A source stopped logging

**Job.** "Did I go blind anywhere? If a source stopped, when, for how long, why, and is it back?" Done when the gap is explained (and recorded), or fixed.

**Target: 2 clicks.** The Dashboard's top section or Health shows the gap in words (0 clicks). The source name (1) opens its **Health row** expanded: the chart with the gap shaded, the gap sentence, current state ("Gap earlier: 2:00 to 7:00 AM (5 h). Reading now."), and **Close** with a reason and note (2), audited. Settings is one more click, from that row, and shows the same note while it is within 24 hours.

**Today**

| Step | Screen | Click | What the lead sees |
|---|---|---|---|
| 1 | Dashboard health strip | Open Health | Health tiles ("3 of 4 healthy") |
| 2 | Health > Sources | | Row with chart and "No events 2:00 to 7:00 AM (5 h). Other sources kept flowing." (after #246; before it, pulled sources were missing, F59) |
| 3 | Row | source name | **Settings > Sources and connectors**, which says Reading, up to date, with no mention of the gap (F61) |
| 4 | (none) | | No way to say it is explained; the row nags for 24 hours |

**Where it breaks**

| Step | Problem | Severity |
|---|---|---|
| 2 | State word is "Needs attention" or "Gap" without why or "reading now" | Medium |
| 3 | The click-through contradicts Health (F61) | High |
| 4 | No acknowledge with a note for gaps (F61) | Medium |
| alerting | "Alert if quiet" is set per source on Sources, away from the gap | Low |

## 6. Add a new source

**Job.** "Start collecting this log, and know it is parsed right." Done when events from it appear, parsed, with the right times.

**Target: 4 clicks ending on proof.** Add source (1), pick the kind (2) (folder, syslog listener, Loki, Microsoft 365, OpenTelemetry), fill and **Test**, which shows sample lines parsed into fields with the template it picked (3), **Save** (4) lands on the source's Health row: first events arriving, parse rate, time offset check. For Loki, Discover lists streams with volume and a suggested template (docs/ux-next-click.md (a)).

**Today**

| Step | Screen | Click | What the lead sees |
|---|---|---|---|
| 1 | Nav | Settings | Settings sub-nav |
| 2 | Settings | Sources and connectors | Sources table |
| 3 | Sources | Add source | Form: kind, path or URL, parser (Automatic), classification |
| 4 | Form | Add | Back to the table; status Waiting, then Reading |
| 5 | Nav | Search | To check parsing: write `WHERE source_id = ...`, look at `parse_status` and fields |
| 6 | Sources | parser mix | Which templates matched (Automatic only) |

**Where it breaks**

| Step | Problem | Severity |
|---|---|---|
| 3 | No preview of parsed sample lines before saving (exists for folders in Discover, not in Add) | Medium |
| 4 | Ends on a settings table, not on proof it works | Medium |
| 5 | Checking parsing needs SQL | Medium |
| Loki | Streams and volume found by trial (ux-next-click.md (a) not built) | Medium |

## What the six have in common

Grouped from the breaks above and the owner's critique (affinity map):

| Theme | Journeys | What fixes it (product pass step) |
|---|---|---|
| No answer first: pages show data before saying what they found | 1, 2, 3, 4 | One sentence at the top of the Dashboard, run, entity, service, and Health pages (6) |
| Values are dead ends: no pivot from a value to its entity | 2, 3, 4, 5 | One pivot component everywhere (2) |
| Links that lose context: alert to Dashboard, detection to rule list, Health to Settings | 1, 2, 5 | Deep links to the run, the entity, the Health row (2, 3) |
| Nav by feature, not task: the morning answer is spread over Dashboard, Health, and AI usage | 1, 4 | Task-based nav and the morning answer at the top of the Dashboard (3) |
| Contradicting states: "Needs attention" here, "up to date" there | 5 | One meaning per state word, with why (6) |
| No closing the loop: acknowledge without a reason, and only for flagged panels | 2, 5 | One **Close** for alerts, rule matches, and gaps (see below) (3) |
| Codes not labels: `class_uid`, `status_id`, `template_id` | 2, 3 | Labels with the code on hover (5, 6) |
| Slow loads show errors | 1, 4 | Performance budget, skeletons, automatic fallback (4) |
| Who is an address | 3, 4 | ADR-0029 (PR #224) |

## Design critique of the current pages

| Page | First impression | Top issue | Recommendation |
|---|---|---|---|
| Dashboard | Good shell; mostly empty space, panels with row counts | No priority: nothing says what matters today | The morning answer as its top section (journey 1); headline values and labels per ADR-0034 on every default panel; ADR-0035 structure |
| Search | Fast and dense; opens on 10,000+ unfiltered rows, mostly DNS | No useful default; codes in the expanded row | Open on the last search or a small "recent notable" set; "Showing the newest 10,000" instead of "limit reached"; labels with codes on hover; +, -, Top and pivots on values; say what "Suspicious" and "AI" do |
| Health | Answers "am I blind" (F55); tabs fixed in #246 | State words do not say why; click-through to Settings contradicts it | F61: why in the state, open the Health row, acknowledge with a note |
| AI usage | A workbench of tabs | Cannot say who; no answer on top | AI Watch first (ADR-0035), service page with review history, ADR-0029 |
| Investigations | Canvas-first, mostly empty | No finding or KPIs; masked activities; empty Targets | DESIGN 6.2 header and finding sentence; activities by outcome with real values; targets listed; graph below, collapsible |
| Sources (Settings) | Dense, now wraps (F54) | Settings view disagrees with Health | Same gap note while within 24 h; link back to the Health row |

**What works and should stay:** the shell and theme, dense tables, expanded rows in place (no modals), facets, the command palette, plain labels, monospace data, and the audit trail behind every action.

**Also from the owner's critique, outside the six journeys:** Linux templates disagree on severity for the same failed login (sshd "Failed password" Medium, PAM "authentication failure" Low); align them in the templates (not a UI change).

## Close (owner, 2026-10-22)

One **Close** action for alerts, rule matches, and gaps alike:

| Part | Rule |
|---|---|
| Reasons | True positive; Benign or expected; False positive (tune the rule); Needs follow-up |
| Note | Required for False positive and Needs follow-up; optional otherwise |
| Mute | Optional "mute similar for N days" |
| Effect | Closed items leave Needs attention; every Close is audited with the reason, note, and mute |

## Order of work

1. Pivot component and entity page summary (step 2): unblocks journeys 2 and 3, and partly 4 and 5.
2. Nav and IA ADR with the morning answer at the top of the Dashboard, deep links, and Close (step 3): journeys 1, 2, 5.
3. AI Watch (ADR-0035) in this pass, for journey 4. Discover from Loki comes right after the pass, for journey 6.
4. Performance budget and first-load states (step 4): every journey.
5. Component audit and consistency rules (steps 5 and 6), then visual QA and the review skill (steps 7 and 8), which then run on every UI PR.

ADR-0029 (PR #224) runs alongside: journeys 3 and 4 cannot reach target without it.

## Owner answers (2026-10-22)

1. No new page: the Dashboard's top section is the morning answer (what needs me, are sources ok, what is new); panels sit below it. One landing page.
2. One Close for alerts, rule matches, and gaps, as above.
3. AI Watch (ADR-0035) is in this pass; Discover from Loki comes right after.
