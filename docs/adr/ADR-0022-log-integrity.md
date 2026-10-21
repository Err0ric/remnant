# ADR-0022: Log integrity: a hash-chained lake ledger, an audit chain, and sealed reports

Status: **Accepted** 2026-10-17 (project owner: "do what's next"). Recorded as SPEC D59; threats T22 and T13 strengthened, T52 added.

## Context

Slice 8 asks for hash-chained partitions, scheduled verification, and an exportable integrity report (SPEC T22: stored logs altered to hide activity, ATT&CK T1565.001 and T1070). The lake changes legitimately all the time: new part files every few seconds, compaction merging them, retention deleting old days, damaged files moved to quarantine. The audit log is protected from DELETE by a trigger (T13) but a person with write access to the SQLite file can still edit rows. An investigator or regulator asks two questions: has anything stored been changed or removed outside the product's own jobs, and can you show it?

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Unit | Each published lake file. A ledger in the metadata database records every file the product adds (path, SHA-256, size, rows) and every file it removes, with the reason (compacted into another file, retention, quarantine). Each entry carries the hash of the one before it, so the ledger is one chain | Files are what change; per-file hashes make verification simple and show exactly what changed | Hash per row (heavy, and compaction rewrites rows); per partition (any compaction would look like tampering) |
| 2 | Where hooks sit | The writer, compaction, retention, and quarantine report to the ledger through one small interface. An install that predates the ledger, or a restore, starts with one `baseline` entry per file found | One place per change; earlier data is covered from the day the feature starts, and says so | Scanning the lake and guessing why files disappeared |
| 3 | Verification | Daily (configurable) and on demand: the chain recomputes; every file the ledger says is present exists with the same hash; no file is present that the ledger never saw. Results: **Verified**, **Warnings** (a file published just before a crash and never recorded is adopted and listed; a removal recorded just before a crash whose file still exists), **Failed** (changed hash, missing file, broken chain) | The three things an attacker does: change, delete, insert | Size and time checks only (cheap but forgeable) |
| 4 | Audit log | Each audit row gets a chain hash over its content and the previous row's hash, written in the same transaction. Rows written before the feature are listed as unchained | Edits to the SQLite file show up, not just deletes | A second database |
| 5 | Anchoring | A **seal** records both chain heads, counts, and the verification result, signed with HMAC-SHA256 under the install key. A daily seal can be sent to alert targets (email, Teams, Slack, webhook), so a copy of each day's head lives outside the server | Someone who controls the server can rewrite the ledger and the chain together; a head already sent elsewhere cannot be changed after the fact | Signing only (the key is on the same server) |
| 6 | Who | Admins and auditors see the status and download the report; admins run verification and choose seal targets. Everything is audited (`integrity.*`) | Matches the audit log's audience | |
| 7 | Report | JSON, signed like a seal: period, current chain head, and every seal in the period with its counts, heads, and each warning and failure with path and reason. Readable without the product | Something to hand to a third party | PDF (later, if asked) |

## Consequences

- New tables `lake_ledger` and `integrity_seals`, column `audit_log.chain_hash` (migration 37, additive).
- Writing a part file now also hashes it (it is in the page cache; about 1 ms per MB). A full verification reads the whole lake once per run; the interval is configurable for large lakes.
- The ledger proves the product's own view of what happened. It does not stop a person with root on the server; together with seals sent off the server it makes the change visible.
- ATT&CK: T1565.001 Stored Data Manipulation and T1070 Indicator Removal against the lake and audit log become detectable. Not AI-facing; no ATLAS mapping.
- Threats: T22 control implemented; T13 strengthened; T52 added (ledger and chain rewritten together by someone with server access: mitigated by off-server seals).
