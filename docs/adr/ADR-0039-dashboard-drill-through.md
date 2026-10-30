# ADR-0039: Every Dashboard number opens its rows in Search

Status: **Accepted** 2026-10-30 (project owner). The owner set the rule; he chose option A for the open question (row 4). Recorded as SPEC D126.

## Context

Most Dashboard cards were numbers with nothing behind them: failed sign-ins, app consents, Conditional Access edits, external sign-in failures, countries. To see the rows, an analyst had to write the search the card already ran. Some counts depend on things SQL cannot express today: the country of an address (local GeoIP, ADR-0023) and whether an address is in the install's Internal networks list (ADR-0038 edit 10, call 8). A card can count up to 5,000 addresses, and Search takes at most 20,000 characters of SQL, so an address list does not fit.

## Decision

| # | Question | Decision |
|---|---|---|
| 1 | What opens what | On every Dashboard section (AI Watch, Identity, Attacks and access, Detections, and later areas): a KPI number opens Search with the query behind the card over the page window, already run, returning the rows the card counted. The change pill opens the same query over the window before. A chart point opens the query narrowed to that hour or day. A top-N row opens the entity page (person, host, address, AI service) when there is one, else Search filtered to that value. A small-multiples row ("Failures by host") opens that host's rows. A sub-line ("2 blocked", "4 more devices not matched") opens its own list. A zero card still opens its empty search, so the analyst sees what is checked |
| 2 | Hover | Pointer cursor and a tooltip "Open N events in Search" (or "Open <name>" for an entity page) |
| 3 | Where the query comes from | The server builds a **predicate** for each number, from the same expressions the count uses, with values as escaped SQL literals; the page adds the time bounds as `TIMESTAMPTZ` literals and opens Search with the smallest time range that covers them. Search runs it through the guard on the caller's own `events` view like anything typed (rules 7 and 13); nothing from the predicate is trusted. Detections use the event ids the matches recorded, since a rule match is not an events predicate |
| 4 | Counts that need GeoIP or Internal networks | **Option A (chosen).** Four SQL functions on every query connection: `ip_country(ip)` returns the two-letter country code from the local GeoIP file or NULL, `ip_asn(ip)` the autonomous system number (integer) and `ip_org(ip)` its organization from the local ASN file or NULL (owner, 2026-10-30: so "top networks" rows drill the same way), and `is_internal(ip)` returns true when the address is in the install's Internal networks list (false for text that is not an address). Both are Python functions in the server process, deterministic, with no network access: they read the same local file and list the Dashboard reads. They are allowed by the guard like any other scalar function, so analysts and Ask can use them too ("`NOT is_internal(src_endpoint_ip) AND ip_country(src_endpoint_ip) = 'NL'`"). Rejected: B, address lists capped at about 500 (not the same rows on a busy install); C, server-held drill sets (exact, but not readable or savable) |
| 5 | How Search shows it | The query on the SQL tab, formatted one clause per line, and a line above it: "From Dashboard > Identity > Failed sign-ins, Oct 24 to Oct 30". Save and Schedule work as for any query |
| 6 | Back | Back returns to the Dashboard with the same window (kept per browser) and the scroll position it left |
| 7 | Test | A frontend test renders the Dashboard and fails when a KPI, chart, small-multiples row, or top-N row has no drill-through target |

## Consequences

- Every count on the page becomes checkable in one click, and the query is a starting point the analyst can edit and save.
- `ip_country`, `ip_asn`, `ip_org`, and `is_internal` run per row in Python. A query that applies them to millions of rows is slower than a plain column filter; the predicates put them after the indexed-like filters (`class_uid`, `status_id`, `template_id`) so they see few rows. A function result for the same address is cached for the query.
- A change to Internal networks or a GeoIP update changes what an old saved search returns. That is intended: "external" means "not in the list now".

## ATLAS and ATT&CK

- The functions add no data to a prompt and no network path. Ask may use them in SQL it writes; the SQL is shown and runs on click as before (rule 4). AML.T0057 (LLM Data Leakage): unchanged, the classification gate and source scope apply as before.
- ATT&CK: supports analysis of T1110 Brute Force and T1078 Valid Accounts by making the sign-in counts checkable.
