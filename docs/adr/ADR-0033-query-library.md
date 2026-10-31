# ADR-0033: Query library (shipped query packs)

Status: **Accepted** 2026-10-22 (project owner). Build order: ADR-0034, ADR-0035, then this. Owner decision: normalize operation names in the template (remove a trailing period from `message`) so library queries match exactly. Recorded as SPEC D98.

## Context

On a real install, every useful question about a new source means writing SQL by hand. Hand-written SQL breaks without warning when a template changes: F36 (text matched on `message` instead of `raw`) and F42 (failed M365 logons stored with `status_id = 1`) both turned correct-looking searches into wrong answers. Users need a starting set of questions for each source type, and those questions need to be tested against the same template fixtures CI already runs.

Today there are 8 example saved searches in `examples/saved-searches/` (D87, F45). They are imported one at a time, carry no "why" or "what is normal", and are checked only for importing and passing the guard, plus a few answer checks.

## Decision (proposed)

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | Format | One YAML file per pack in `library/<pack>/pack.yaml`. Each query uses the saved-search format (SPEC 5.4) plus: `requires` (template ids), `group` (for example "Microsoft 365 / Identity"), `why` (one line), `normal` (one line on expected noise), `suggested_schedule` (`hourly`, `daily`, or `null`), optional `flag` (the schedule flag: `above N`, `below N`, `change N%`), and optional `expect` (see row 8) | One format for saved searches and library queries, so "Save as my own" is a copy | A new query format (two parsers, two exporters) |
| 2 | Where it lives | In the repo, shipped with the server, read at start. **Never fetched** | Nothing runs that was not reviewed in a PR; no supply-chain path for SQL | A download feed (later at most, signed, like ADR-0023) |
| 3 | What a user sees | Search page: **Library** button next to **Open**. Lists only queries whose `requires` include a template some source in the viewer's scope uses (from `template_id` counts, not configuration, so a template with no events is not offered). Grouped by `group`; each shows name, `why`, `normal` | Offering a query that cannot return rows teaches people the library is noise | Show everything with a "no data" badge |
| 4 | Load and run | Click loads the SQL into the SQL tab (unsaved) with `why` and `normal` shown above the editor. **Save as my own** copies it into a private saved search (with `origin.library: <pack>/<id>@<pack version>`). Running is the normal Run | The library is a starting point, never a hidden runner | Running library queries directly (two run paths) |
| 5 | Dashboard | Dashboard: **Add a pack** checklist. Ticked queries become private saved searches plus schedules with `suggested_schedule` and `flag`, and panel settings from ADR-0034 (section = the pack's group, size, headline) | One click to a working layout; every created object is ordinary and editable | Library panels that are not saved searches (a second panel kind) |
| 6 | Security | Every query goes through the guard (rule 7) and runs on the caller's `events` view (rule 13). Library status grants nothing: no source list, no elevated view, no skipping the guard. `why` and `normal` are display text only; they are **never sent to a model**, as instructions or as data | Library SQL is still SQL from a file; the same rules apply as to a user's own | Trusting shipped SQL (an exception to rule 7) |
| 7 | Updates | A pack has a `version`. A copy saved with **Save as my own** is the user's; an upgrade never edits it. The Library shows "Updated in this version" on a query whose SQL changed since the copy was made, with a diff and **Replace my copy** (audited `search.update`) | A user's copy may have local edits; silent changes would break their schedules' hash check (SPEC 5.5) | Auto-updating copies |
| 8 | CI | A parametrized test loads every pack: schema valid; each query parses, passes the guard, and runs on the template fixtures for its `requires` (the same `sample.log` files the template suite uses) with no error; `expect` (optional) states the result on those fixtures: `rows: N`, `rows_at_least: N`, or `first_row: {col: value}`. A template change that breaks a library query fails CI | This is what makes the library better than hand-written SQL | Import-only checks (today's examples test) |
| 9 | Labels | Plain label **Query library**. "Grimoire" is a command palette alias only (rule 12) | CLAUDE.md rule 12 | |
| 10 | First packs | `m365` (Identity, Mail, Apps and consent, Admin, Copilot, Data), `linux_auth`, `paloalto`, `dns_ai`. The 8 example saved searches move into packs and `examples/saved-searches/` points to the library | One place for shipped queries | Keeping both |
| 11 | Later | Admin-imported packs from a folder, same pattern as Sigma rule import (read-only mount, validated, guarded, audited `library.import`). Not in the first build | Same review path as Sigma | |

### M365 seed (owner install notes, 2026-10-22)

The nine queries in the owner's notes become the `m365` pack with these changes:

| Query | Change for the pack |
|---|---|
| `m365_failed_signins_by_user`, `m365_password_spray`, `m365_failures_then_success` | F42 is fixed (template 1.1.0, PR #235): filter `status_id = 2` on `m365_management_activity` **and** include `m365_signin` rows (`class_uid = 3002`), with a `source_kind` column saying which. `requires: [m365_management_activity]` or `m365_signin` (either is enough; the SQL handles both). Events stored before 1.1.0 still have the old status: the pack's `normal` line says so until re-parse exists |
| `m365_failures_then_success` | Join only on rows already reduced to user and address (as in D94), never event to event |
| `m365_app_consent`, `m365_admin_changes` | Operation names arrive with and without a trailing period ("Add application" and "Add application."). Accepted: a template transform in `m365_management_activity` (1.2.0) that removes one trailing period from `message` (never from `raw`), so the queries use `IN (...)` instead of `ILIKE` prefixes. Microsoft's first-party tenants (`f8cdef31-...`, `72f988bf-...`) excluded on `raw`, as in `m365_new_service_principals` |
| `m365_copilot_activity` | Match `message = 'CopilotInteraction'` and the Copilot record types, not `raw ILIKE '%Copilot%'` (which also matches unrelated rows that mention Copilot in a file name) |
| `m365_inbox_rules`, `m365_signins_by_app`, `m365_external_sharing` | As written; `m365_signins_by_app` notes that `message` is `appDisplayName` |
| New: `m365_new_service_principals`, `m365_user_consent` | Move in from `examples/` |

## As built (2026-10-31, part 1)

- `requires` means any one of the templates; an empty list means any source (the `health` pack, which holds `parser_mix`, the one example that fits no other pack).
- A query may use parameters other than `start` and `end` only with a default; the Library loads it with the default written into the SQL (`who_had_ip` opens with `10.20.1.5`), and Save as my own keeps the parameter.
- `GET /api/library`, `POST /api/library/{pack}/{query}/copy` and `/replace` (admins and analysts); copies carry `origin.library: <pack>/<id>@<version>`. Offering reads `SELECT DISTINCT template_id` over the last 30 days of the viewer's own view.
- "Grimoire" stays a palette alias of Saved searches too; the palette's **Query library** entry also answers to it.
- Part 2: **Add a pack** in the dashboard settings, `POST /api/library/{pack}/dashboard` (admins and analysts). Schedules are private, look back 24 hours, run at the query's `suggested_schedule` (daily when none), and take its `flag` as the threshold; panels are a third wide in a section named after the group (60 characters). An existing copy is reused, never duplicated. Panel headline settings stay the defaults; change them on the panel.

## Consequences

- Shipped questions are tested against the fixtures on every PR, so a template change cannot silently break them.
- The library adds no new run path: it is a source of SQL text for the existing editor, saved searches, and schedules.
- Packs need fixture coverage: a query whose fixtures cannot produce a row gets an `expect: rows: 0` check only for running, and the pack PR adds fixture lines so it can return one.
- Work: about two PRs (loader, CI test, Library panel; then Add a pack, which depends on ADR-0034 for panel settings).

## ATLAS / ATT&CK

No new AI surface: library queries are deterministic SQL, and no library text is sent to a model. The M365 pack maps to ATT&CK T1110.003 (password spraying), T1078.004 (cloud accounts), T1564.008 and T1114.003 (inbox rules and forwarding), T1528 (consent phishing), T1098 (account and role changes), T1567 (sharing links). The Copilot and AI queries support monitoring for AML.T0057 (LLM data leakage), as the AI usage page does.
