# ADR-0035: AI Watch at the top of the Dashboard, on a daily AI rollup

Status: **Accepted** 2026-10-22 (project owner), with two conditions written into rows 4 and 11: the rollup respects source access and the `local_only` label exactly as events do, and the review queue actions are admin only and audited. From install findings F49 (and the rollup asked for in F46). Recorded as SPEC D97.

## Context

On a real install the administrator watches the Dashboard for unsanctioned AI. Panels built from saved searches cannot look like a finished product: row-count headlines, generic tables, developer text ("Showing 3 of 5 columns"). The AI usage page has the data but is a workbench (tabs, tables, review settings), not a daily view.

D94 made AI usage > Services fit a small memory share by grouping events to service, person, machine, address, and hour inside each query. A 30-day chart on the landing page would still scan 30 days of DNS on every load. F46 asked for a daily rollup; this ADR decides it, because AI Watch is the first thing that needs it.

Depends on ADR-0034 (headline values, tiles, sections, Restricted handling).

## Decision (proposed)

### Part 1: the AI rollup

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | What is stored | Exactly the grouped rows D94's query already makes: per source, hour, service id, person, machine name, address, device, with event count, first and last time. Only events whose host matches the catalog | The same shape the live query uses, so live and rollup answers agree by construction | Per day per service only (cannot resolve who had an address, which is hourly) |
| 2 | Where | Parquet under `<data>/rollup/ai/source=<id>/day=<date>/part-*.parquet`, outside the `source=*/day=*` event folders, so it is never read as events | Same storage and retention model as events; no new database | A SQLite table (writes from the compaction job contend with the meta DB) |
| 3 | When | Built by the compaction job for each closed day (UTC) after that day's partitions compact; today and any not-yet-built day are computed live by D94's query and unioned | Closed days never change except by late events (row 6) | Building every hour (more writes, little gain) |
| 4 | Access and classification (owner condition) | A per-session `ai_rollup` view built in `engine/views.py` from the caller's permitted sources, exactly like `events` (rule 13). Rows carry `source_id` and the source's `classification` as the events had it, never upgraded. Anything that would send rollup data to a model goes through the gate with the rollup rows' sources in scope, so a `local_only` source blocks a cloud provider exactly as its events do (today nothing does: row 8). Tests prove a restricted source is invisible in the rollup and that rollup rows keep `local_only` | No new scope or classification logic | Filtering in Python after the query |
| 5 | Catalog and review status | Review status (approved, not reviewed, blocked) and data level are joined **at read time**, never stored. A catalog **domain** change (an admin adds or removes a domain, or an update brings new ones) marks the rollup stale; the job rebuilds the retention window in the background, oldest last, and AI Watch says "Rebuilding history after a catalog change" until done | Status changes are frequent and must show at once; domain changes are rare and change which events count | Storing host, not service (larger, and still needs the catalog per read) |
| 6 | Late events | Events that arrive for a closed day (Loki backfill, an agent catching up) mark that day's rollup stale; the next job run rebuilds just that day | Late data is normal (F43 backfill) | Ignoring them (counts drift from the live view) |
| 7 | Retention and integrity | A rollup day is deleted with the source day it came from. Rollup files are derived and rebuildable: they are not in the integrity ledger (ADR-0022), and the integrity report says so | The ledger proves events were not changed; the rollup is a cache of them | Ledgering derived files |
| 8 | Who uses it | AI Watch (all of it) and AI usage > Services for ranges of 2 days or more. Saved searches do not see it (no new table for users or the LLM to query) | One consumer to start; exposing it later is a separate decision | Exposing `ai_rollup` to Search and Ask (needs schema docs and an Ask prompt change) |

### Part 2: AI Watch

```
+--------------------------------------------------------------------------------------+
| Dashboard: Daily                       Last 7 days v      Updated 3 min ago   Edit   |
| [health strip, ADR-0031]                                                              |
+--------------------------------------------------------------------------------------+
| AI Watch                                                                             |
| +--------------+ +--------------+ +--------------+ +--------------+ +--------------+ |
| | 4            | | 11           | | 2            | | 1            | | 3            | |
| | unapproved   | | people using | | new agents   | | app consent  | | sensitive    | |
| | AI services  | | unapproved AI| | and MCP      | | grants       | | data to AI   | |
| | +1 vs prev.  | | -3 vs prev.  | | +2 vs prev.  | | same         | | +3 vs prev.  | |
| | ChatGPT most | | 8 on ChatGPT | | 1 unapproved | | bob@ to ...  | | Claude Code  | |
| +--------------+ +--------------+ +--------------+ +--------------+ +--------------+ |
| Needs review (5)                                                                      |
|  HIGH  New unapproved service: DeepSeek    3 people, 5 devices   2 h ago   Review v   |
|  MED   New MCP server: filesystem-tools    WS-0042 (dana)        5 h ago   Review v   |
|  MED   App consent: Example Notes          bob@example.com       1 d ago   Review v   |
|  ...                                                                                  |
| AI use, last 30 days                                    [approved][unreviewed][blocked]|
|  ||| stacked daily bars by review status                                              |
| Top services                                                                View all  |
|  Service      Status        People  Devices  First seen   Last seen                    |
|  ChatGPT      Not approved  8       12       12 d ago     4 min ago                    |
+--------------------------------------------------------------------------------------+
| Custom panels (ADR-0034 sections) ...                                                 |
+--------------------------------------------------------------------------------------+
```

| # | Part | Proposal | Data |
|---|---|---|---|
| 9 | Placement | A built-in section at the top of any dashboard that enables it ("Show AI Watch", on by default for the first dashboard of an admin once any DNS, firewall, proxy, telemetry, or M365 source exists). Custom panels below | |
| 10 | KPI strip (5 equal cards) | Unapproved AI services; people using unapproved AI; new agents and MCP servers; app consent grants; sensitive data to AI. Each: value, label, delta against the previous period of the same length ("+1 vs previous 7 days", "same"), and one context line. A card whose data needs a source the install does not have shows "Needs a Microsoft 365 source" (a link to add it), not zero | Rollup (1, 2); existing MCP and agent change logic (3); M365 directory and management audit, `Consent to application` (4); Claude Code `sensitive_total`, M365 `DlpRuleMatch` on Copilot records, and events to services whose data level is restricted (5) |
| 11 | Needs review queue | One row per open item: new unapproved service, new agent or MCP server, consent grant, sensitive-data signal. Severity badge (High: a not-approved service used by more than one person, or any sensitive-data signal; Medium otherwise), title, who and where, relative time, **Review**. Admins only (owner condition): **Approve** and **Block** (services and MCP servers, the existing admin-only review endpoints, audited as today) and **Dismiss** (every kind; stored per item, audited `ai.review_dismiss` with the item and reason). Other roles see the queue without actions; the API refuses them (403, tested). Empty: "Nothing to review" in `--ok` | Existing review status endpoints; a new `ai_review_dismissals` table |
| 12 | AI use over 30 days | One stacked bar chart, a bar per day, stacked by review status. Fixed 30 days regardless of the range picker, stated in the title. Reads the rollup only, never events | Rollup |
| 13 | Top services | Service, status pill, people, devices, first seen, last seen; 10 rows and **View all** (AI usage > Services with the same range) | Rollup |
| 14 | Polish rules (every panel on the page, custom ones included) | Relative times with the UTC time in a tooltip; header shows the range and "Updated N min ago"; headline values from ADR-0034, never raw row counts; no developer text (a column note becomes **View all**); equal card heights per row on a 12-column grid; tabular numbers; every number links to the rows behind it (Search with the matching SQL and range, run as the viewer through the guard) | |
| 15 | Access | Every number is computed on the caller's view. A card or queue item that needs a source the viewer cannot read shows **Restricted**. `local_only` data stays local: no model call anywhere on the page | Rule 13, SPEC 6.2 |
| 16 | Design | Built with DESIGN.md tokens and the frontend-design skill; the KPI card, queue row, and stacked bar become DESIGN.md patterns (section 6) before the build | |

## Consequences

- The landing page shows the answer to "is anyone using AI we have not approved" without a saved search.
- The rollup adds a compaction step and a rebuild path; its cost is one grouped pass per source per day, which D94 measured at seconds for 300k DNS events.
- AI usage > Services gets faster for long ranges as a side effect.
- Work, after ADR-0034: rollup and its view (one PR), AI Watch API (one PR: KPIs, queue, chart, top services), AI Watch page (one PR, with the DESIGN.md patterns).

## ATLAS / ATT&CK

No new AI surface: no model call on the page, and the rollup is not exposed to Ask or the LLM gate. What the page monitors is AML.T0057 (LLM data leakage: company data sent to AI services) and the use of unapproved AI services and agents; consent grants map to ATT&CK T1528.
