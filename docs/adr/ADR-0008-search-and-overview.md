# ADR-0008: Ask inside Search, and an Overview home page

Status: **Accepted** 2026-10-11 (reviewed by the project owner: every recommendation accepted). Rows 1 and 5 are extended by ADR-0009 (accepted): Search gains a third tab, Simple, which becomes the first-time default.

## Context

Two things came out of using the app on the homelab VM:

1. **Ask is a separate page, but it is really a way to write a search.** Ask produces SQL that the analyst then runs; the results, export, save, and schedule actions all belong to Search. Keeping them apart means two editors, two results views, and a copy step between them. Asking in plain English is a core feature of searching, not an add-on, and putting it on its own nav item makes it look bolted on.
2. **The app has no home page.** Login lands on Search with an empty editor. Overview, Investigations, and Audit log show as inert "Later" items. With little log flow, nothing on screen says whether ingest, rules, schedules, and alerts are healthy, so the product looks thinner than it is.

SPEC 5.2 and 5.3 describe Query mode and Ask mode as two modes on one engine; DESIGN section 5 lists Ask as its own nav item and 6.3 gives it its own page. Neither covers a landing page. This changes UI layout only: the Ask contract in SPEC 5.3 (two tools, SQL shown, run on click, gate, audit) is untouched.

## Decision

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. Where Ask lives | A tab strip at the top of Search's editor area: **SQL** and **Ask in plain English**. One results card under both. The Ask nav item is removed; `/ask` and the command palette's Ask entry open Search on the Ask tab | One place to search; results, export, save, and schedule are shared | Keep a separate Ask page and add a "Send to Search" button |
| 2. What Run does from Ask | The Ask tab shows the generated SQL (read-only, with explanation and assumptions) and a **Run** button. Run copies the SQL into the SQL tab's editor and runs it there, so the analyst can see and edit exactly what ran. Nothing runs without the click; `ask.auto_run` keeps its current meaning | Keeps SPEC 5.3 step 3 exactly; the editor always holds what produced the results | Run in place without touching the editor |
| 3. Follow-up turns | Kept while the analyst stays on Search, shown as a compact list of earlier prompts above the latest SQL (no chat bubbles). Leaving the page or "New question" clears them. Up to 3 turns, as now | Same behavior as today's page, inside Search | Persist turns across page loads |
| 4. Who sees the Ask tab | Admins and analysts, as now. Auditors do not see the tab. With no provider configured, the tab shows a one-line note ("No AI provider is set up") and, for admins, a link to AI providers; the SQL tab works as always | Deterministic core works with zero providers (CLAUDE.md rule 1) | Hide the tab when no provider exists |
| 5. Default tab | The tab last used on this browser (stored with try/catch); SQL the first time | Respects how each person works; SQL is the safe default | Always SQL |
| 6. Save and schedule from Ask | Unchanged: saving records the SQL, not the prompt (SPEC 5.3 step 5) | | |
| 7. Overview page | A read-only home page, built from data the server already has, shown only for what the viewer may read: **Event volume** (events per permitted source per hour, last 24 h, small bars); **Ingest health** (per permitted source: last event time, files waiting, last error, from `SourceStatus`); **Detections** (flagged schedule runs and rule matches in the last 24 h, linking to the run); **Paused schedules** (the viewer's and shared ones, with the reason); **Alert delivery** (admins: targets marked failing and deliveries failed in the last 24 h) | Answers "is it working and did anything fire" at a glance, and gives the app a real front door | A configurable widget grid (later, if ever) |
| 8. Overview access and audit | Every number comes through the per-session `events` view and the guard, like any query (CLAUDE.md rules 7 and 13). Restricted runs are left out, not counted. One audit row per page load (`overview.view`), with results cached per user for 60 s so refreshes do not flood the audit log | No side door around access control; still attributable | No audit for the Overview (breaks rule 14) |
| 9. Landing page | Overview becomes the page after login and the target of the product mark | A home page should be home | Keep Search as the landing page |
| 10. When to build | Now, as two small UI-led PRs before Slice 5 (Ask into Search; then Overview with one read-only endpoint `GET /api/overview`) | Slice 4 is done; this is the first thing every user sees, and it is small | Slice 6 (polish) |

Not changing: Investigations and Audit log stay as inert "Later" items (Slice 5 builds the audit log viewer; Investigations is not scheduled).

## Questions for the owner

1. **Ask placement (rows 1 and 2):** tab inside Search, with Run copying the SQL into the editor (recommended), or keep Ask as its own page?
2. **Overview contents (row 7):** the five panels listed (recommended), or a different set?
3. **Landing page (row 9):** Overview after login (recommended), or keep Search?
4. **Timing (row 10):** build now before Slice 5 (recommended), or in Slice 6?

## Consequences

- SPEC 5.3 gains a line: Ask is a tab of the Search page; the contract is unchanged. SPEC gains a short Overview section (5.8) and a decisions row.
- DESIGN section 5: nav drops Ask; Overview becomes ready. DESIGN 6.1 gains the SQL / Ask tab strip; 6.3's Ask paragraph moves under 6.1; a 6.4 Overview pattern uses the Dashboard card grammar.
- Frontend: `features/ask/` components are reused inside `features/search/`; `AskPage` becomes a redirect. Tests for "Ask does not run SQL without a click" move with it.
- Backend: one new read-only endpoint, `GET /api/overview`, using existing services; no migration.
- The Slice 2 Ask DoD items stay valid as written.

## ATT&CK and ATLAS

No new AI capability: Ask keeps the same gate, the same two tools, the same audit, and run on click, so the SPEC 7 ATLAS rows for Ask (AML.T0051.001, AML.T0057) are unchanged. The Overview is a new read path; it is covered by T15 (reading sources one is not cleared for, T1213) through the per-session view and restricted runs being left out (row 8).

## Review outcome

| Question | Answer |
|---|---|
| 1. Ask placement | A tab inside Search; Run copies the SQL into the editor and runs it |
| 2. Overview contents | The five panels in row 7 |
| 3. Landing page | Overview after login |
| 4. Timing | Build now, before Slice 5 |
