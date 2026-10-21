# Log integrity

The server keeps a tamper-evident record of its own stored logs and of the audit log, so you can show that nothing was changed, removed, or slipped in outside the product's own jobs (ADR-0022). It is on for every install; there is nothing to enable.

## What is recorded

| Record | What it holds | Where |
|---|---|---|
| Lake ledger | One row per lake file the server writes or removes: path, SHA-256, size, and the reason for a removal (compacted into another file, retention, quarantine). Each row includes the hash of the row before it | `lake_ledger` in `meta.sqlite` |
| Audit chain | Each audit row carries a hash over its content and the previous row's hash | `audit_log.chain_hash` |
| AI call chain | Each AI call record is chained the same way when the call completes (calls still running have no hash yet) | `llm_calls.chain_hash` |
| Seals | Each verification: both chain heads, counts, the result, and every finding, signed with a key derived from the install key (`data/.key`) | `integrity_seals` |

Files already in the lake when the feature first starts are recorded as `baseline` (until the first check is sealed, even if ingest has written new files in the meantime), and audit rows and AI call records written before it are reported as unchained. Coverage starts on that day. After the first seal, a file nobody recorded is never baselined: it is reported.

## Verification

Runs once a day (change with `APP__MAINTENANCE__INTEGRITY_INTERVAL_S`, minimum 300) and whenever an admin clicks **Verify now** on **Settings > Audit log > Integrity**. It reads every lake file once, so on a large lake run it less often. **Verify now** waits 30 seconds after the last check before it runs another.

| Result | Meaning | What to do |
|---|---|---|
| **Verified** | Every recorded file is present with the same hash, the ledger chain holds, and every chained audit row is unchanged | Nothing |
| **Warnings** | A file was found that was never recorded (adopted, and listed again on every check for 7 days); a file recorded as removed is still there; or a `.parquet` file sits outside the `source=*/day=*/part-*.parquet` layout (searches never read those). The first two happen after a crash between writing a file and recording it, or after a restore from a backup taken while ingest was running | Check the listed paths look like normal lake files and the time matches a crash or restore; remove stray files you did not put there |
| **Failed** | A recorded file changed or disappeared, a ledger row was edited, an audit row or AI call record was edited or removed, or the chains no longer hold what the last valid seal recorded (for example the ledger was emptied and started over) | Treat as an incident: see below |

Files younger than 2 minutes are not judged yet; the writer records them as it publishes. A file dated in the future is judged at once.

Compaction, retention, and the empty-file sweep never remove or merge a file whose content no longer matches the ledger: it stays where it is, and the next check reports it as changed.

## Getting a copy off the server

Someone with full control of the server could rewrite the ledger and the chain together so a check passes again. Seals sent elsewhere stop that from going unnoticed.

1. Add an alert target (email, Teams, Slack, or webhook) under **Settings > Alert targets**, ideally one the server's admins cannot edit afterwards: a shared mailbox, a channel with retention.
2. On **Settings > Audit log > Integrity**, tick the target and **Send a daily seal to these targets**, then **Save**.

Failed checks go to the ticked targets whether or not daily seals are on. Each seal message shows the first 16 characters of the lake head, the audit head, the AI call head, and the signature. To check a later report against them, compare those characters with the matching seal in the report.

## Report

**Download report** (admins and auditors) saves a JSON file with every seal in the last 30 days, the current lake head, and an HMAC signature. Use `GET /api/integrity/report?days=N` for another period (1 to 366). Downloads are recorded as `integrity.report` in the audit log.

## When a check fails

1. Do not restart, compact, or delete anything yet. Download the report.
2. For `Changed` or `Missing` files, compare with your latest backup: its manifest holds a SHA-256 for every file, and `app-admin verify-backup` checks them.
3. For `Audit row edited`, the row number is in the finding; export the audit log and compare with an earlier export or backup.
4. For `Ledger edited`, compare the lake head with the last seal message your targets received.
5. Look for who had shell access to the server around the time between the last verified seal and the failed one.

## Limits

- The record proves what the server itself saw. It does not stop someone with root on the server; with seals sent off the server it makes the change visible.
