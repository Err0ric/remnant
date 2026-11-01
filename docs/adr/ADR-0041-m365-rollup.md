# ADR-0041: Daily Microsoft 365 rollup

Status: **Accepted** 2026-10-31 (project owner's design; reverses D129). Recorded as SPEC D131.

## Context

D129 deferred a Microsoft 365 rollup while the 30-day Overview stayed under about 3 s. On the owner's install it took about 14 s (16 s at 7 days in a later walkthrough): every load parsed `raw` JSON for each failed sign-in, joined consents to 60 days of sign-ins, and scanned every Microsoft 365 event twice over (the window and the one before).

D129's objection was that a per-source rollup cannot apply the one-operation key (D122) across Graph and the Management API. On the owner's install both feeds are one source (`m365`, different templates), and keeping the key in the rollup removes the objection for split installs too.

## Decision

| # | Question | Decision |
|---|---|---|
| 1 | What | Per source and closed UTC day, the Overview's **facts** (`app.search.m365.FACTS`) as Parquet under `<data>/rollup/m365/source=<id>/day=<date>/`, outside the lake and the integrity ledger (derived, rebuildable). |
| 2 | Facts | Sign-ins per hour, outcome (succeeded, interrupted, failed), risky flag, person, and address; sign-ins per hour, outcome, app, and failure reason and code (two kinds so neither multiplies the other); the counts row's operations per hour; one row per change and per consent with its D122 key (correlation id, else person and minute); each source's first event. |
| 3 | One SQL | The same fact SQL builds a closed day and reads the days the rollup does not have, so both paths give the same numbers (tested on every window). |
| 4 | Dedupe | Changes and consents keep their key, so they are deduplicated again when read: once across days (a consent copied either side of midnight) and once across sources. An install that splits Graph and the Management API into two sources needs no extra events read and no "one source" rule. |
| 5 | Access (rule 13) | Rollup folders are read per source, from the caller's permitted sources only, exactly like `events`. Server-built queries only: Search, Ask, saved searches, and MCP never see `m365_rollup`. |
| 6 | Which days | Only fresh days wholly inside the page's range come from the rollup (closed days in 24 hours, 7 days, and 30 days alike); today and partial days come from events. |
| 7 | Freshness | A day is rebuilt when its lake files change (late events, compaction) or the fact SQL changes (an upgrade); it is removed when its lake day is removed (retention). Built after each compaction with the AI rollup, newest first, at most 60 days per run. A day with more than 100,000 facts is read from events. |
| 8 | Addresses | The rollup keeps addresses, not countries, so a GeoIP update or a change to approved countries applies at once without a rebuild. |
| 9 | Speed | The Overview's queries run together (4 at a time) instead of one after another. |

## Measured

`tests/integration/test_m365_scale.py -m scale`: 60,000 sign-ins (full-size Graph records, about 3 KB) and 100,000 Management Activity operations a day for 61 days in one source, 2 vCPU: 30-day Overview **34 s from events, 1.9 s with the rollup**, the same numbers. The test fails above 2 s.

## Consequences

- The Overview reads days of small facts instead of millions of events; drill-throughs still open the events in Search.
- A definition change (for example a new interrupt code) rebuilds the window over a few maintenance runs; until then those days are read from events, so numbers are never mixed.
- The Dashboard's Microsoft 365 cards still read events; they can move to the same facts if they show up in profiling.

## ATLAS / ATT&CK

No AI surface. Exposure unchanged: the rollup holds only what the same caller could read from `events`, per source.
