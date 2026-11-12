# ADR-0050: A source whose template cannot load falls back loudly

Status: **Accepted** 2026-11-10 (owner, with two changes recorded in section "Review changes": threat rows renumbered, and a rule re-run after reparse). Owner direction 2026-11-09 (handoff item 3, after ADR-0049 Phase 0). Amends ADR-0005 row "Deleting an approved user template" and D121 ("there is no re-parse") where the rows below say so. Threats T87 and T88 are added to SPEC 7.1 by the slices that build them. Decision D233.

## Context

Today a source whose template cannot load stops (`ingest/watcher.py`, `_normalizer`: "Never fall back silently"). The source shows an error until the template exists. That is safe for a file source, whose checkpoint does not move, but not for pushed data:

- A syslog listener or OTLP source keeps spooling until 512 MB waits for the source, then refuses new messages (found on #473). Senders do not retry for long, so those messages are lost.
- A rollback to a release without a newer template, a bad edit to a user template, or a missing file all cause this. Users are not technical (CLAUDE.md section 9): a stopped source looks like a quiet network, not an outage.

The owner's direction: keep it never silent, but stop dropping data.

## Decision

| # | Topic | Proposed default | Why | Alternative |
|---|---|---|---|---|
| 1 | What is stored | The source keeps running. Syslog sources store the envelope parse (host, time, program, message), other formats the generic parser for the source's format, as a source with no template would today. `raw` is kept exactly; classification comes from the source as always | Nothing is dropped and nothing is guessed: the generic parsers already exist and are tested | Keep stopping, but raise the spool cap (still drops, only later) |
| 2 | Marking | `parse_status = template_missing` (a new value, no new column) and `parse_errors = "Template <id> was not available"`. `template_id` stays the source's configured id, so a search on the template still finds these rows | One value finds every fallback row, for searches, Health, and the reparse | A new column (schema change for one flag) |
| 3 | When it applies | Any time the configured template is absent from the registry: missing file, failed validation, a version that no longer loads. `auto` sources are unaffected (they already fall back per line). A template that loads again is used from the next pass | One rule for every cause; the registry is already the single place that knows | Only on rollback (misses the other two causes) |
| 4 | Health | An error row naming the source and the template ("Source edge_fw is storing events without its parser: template paloalto_csv is not available"), until the template loads again. Sources shows the same state as `error` with the same text | The owner asked for Health to name both | Warning level (too easy to ignore) |
| 5 | Alert | One message to every alert target, kind `source_fallback`, when a source starts falling back, and one `source_fallback_cleared` when the template loads again, with the count of rows stored without the parser. No repeat while it continues. Audited | One message per outage, and the second one tells people the gap is over | No cleared message (people do not know it ended) |
| 6 | Detections | The alert and the Health row say that rules and searches using the template's fields miss these rows until they are reparsed. No rule is changed | Honest about the gap without touching detection logic | Run rules on the fallback rows (would mostly miss anyway) |
| 7 | Reparse | Once the template loads again, an admin can choose "Reparse N events" on the source. A background job rewrites only the affected rows with the template, keeping `event_id`, `raw`, `time` from ingest, and classification; `parse_status` becomes the new result. It reuses compaction's crash-safe rewrite (manifest, retire then delete, D183) and records each rewrite in the integrity ledger. Audited with the count. When it finishes, the source offers "Run rules over the reparsed range": on demand, admin only, it runs the enabled rules over the reparsed rows' time range for that source, and any results are stored as normal rule matches (alert items under D200, so an item already open for the same group and day grows instead of duplicating). Audited | The owner asked for reparse; the compaction machinery already rewrites files safely. Rules that ran during the window saw only envelope-only or generic rows and missed what the template's fields would have matched | Append reparsed copies and hide the originals (doubles storage, two rows per event in exports) |
| 8 | Reparse scope | Only `template_missing` rows of that source, in its retention window, at most one job per source at a time, low priority behind ingest | Keeps it from becoming a general re-parse of history, which D121 rules out | General reparse of any rows after any template change (out of scope; would reverse D121) |
| 9 | Deleting a template in use | Still refused (ADR-0005). This ADR covers the causes that bypass that check | The refusal is still the first line | Allow it now that fallback exists (makes a mistake easier) |

## Alternatives considered

- **Keep stopping (today).** Never silent, but pushed data is dropped after 512 MB, and that is a real loss.
- **Fall back silently to the generic parser.** Rejected by the owner's direction and ADR-0005.
- **Hold the raw lines aside and parse later.** A second storage path for the same lines; searching them meanwhile would need a second engine path. Storing them as events with a clear status is simpler and searchable now.

## Consequences

- Detections and dashboards that rely on the template's fields have a gap until the reparse. Health, Sources, and the alert say so in plain words.
- D121's rule now has one exception (row 7), recorded as a decision.
- Reparse rewrites lake files, so the integrity ledger gains a `reparse` entry type next to compaction's.
- Rollback (CLAUDE.md section 9 rule 4): the rollback note for a release that removes or renames a template can say that events keep being stored and can be reparsed after updating again.

## Thin-slice plan

1. **Fallback and status** (rows 1 to 3): watcher change, `template_missing` status, tests for file, listener, and OTLP sources. Release note says what users will notice.
2. **Health, Sources, and alert** (rows 4 to 6).
3. **Reparse** (rows 7 and 8): job, button, ledger entry, audit, and "Run rules over the reparsed range".

Each slice is one PR through the queue with the section 9 checks.

## Tests

- A file, listener, and OTLP source with a missing template: every line stored with `raw` unchanged and `parse_status = template_missing`; the listener never refuses for this reason.
- The template returns: new lines parse with it from the next pass; one cleared message with the count.
- One alert per outage, not per pass; audited.
- Reparse: rows rewritten with the same `event_id` and `raw`; a crash mid-job leaves either the old rows or the new rows, never both or neither; only that source's `template_missing` rows change; the ledger records it.
- After a reparse, "Run rules over the reparsed range" finds a match the rules missed during the window and stores it as a normal match; running it twice does not duplicate items.
- An Analyst cannot start a reparse or the rule re-run; an Auditor sees the ledger entry and audit rows.

## Threats

| Row | Threat | ATT&CK / ATLAS | Mitigation |
|---|---|---|---|
| T87 | An attacker with write access to the templates folder breaks a template to blind detections on a source | ATT&CK T1562.001 Impair Defenses (Disable or Modify Tools) | Events are still stored (row 1); Health error and alert to every target (rows 4, 5); reparse closes the gap, and the rule re-run over the reparsed range finds what the rules missed during the window (row 7). Not AI-facing: no ATLAS impact |
| T88 | Reparse used to alter stored events | ATT&CK T1565.001 Stored Data Manipulation | Only `template_missing` rows; `raw` and `event_id` never change; admin only; audited; integrity ledger entry |

## Review changes (owner, 2026-11-10)

1. Threat rows renumbered T83, T84 to T87, T88: ADR-0049 owns T79 to T86. `scripts/docs/assemble.py` now fails when two ADRs claim one threat number (`--check`) and when a threat number a PR adds is already in SPEC 7.1 on main (`--prep`, in the queue) (D234).
2. Row 7 gains "Run rules over the reparsed range", built in the third PR; T87's controls name it.

## Open questions for the owner (answered 2026-11-10: proposed answers accepted)

1. Reparse in this ADR: yes, as the third PR.
2. Cleared message (row 5): yes.
3. Recipients (row 5): every alert target.
4. Health level (row 4): error.
