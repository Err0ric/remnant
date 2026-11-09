# Handoff

Updated at the end of each batch. Start the next session here, after `sh scripts/dev/session-check.sh`.

## Current state (2026-11-08)

- `main`: #457 on top of #443. Public repository published as `dd2dfe6` after release-checks passed (vector, systemd, digests, container).
- Open PRs: none.
- Merged this batch: #445 (Identities scoping, T70, D219, D223), #447 (decisions), #448 (certifi, Dependabot, D224), #449 (ADR-0048, T71 to T76), #450 (query connection lock, ADR-0047, D225), #451 (Auditor SQL setting, D220), #452 (accuracy and readability, D221), #453 (rollback command, D226), #454 (server-built display lists), #455 and #456 (speed check and smoke test in the queue), #446 (suite speed, D216), #443 (self-hosted runner prep, D217), #444 (backlog, D218).
- Speed overrides applied under the standing rule: #452, People & devices, queue +143 ms, clean re-time +50 ms.

## Next, in order

Owner, 2026-11-08 22:02, from the work install on `dd2dfe6` (15 pages, no console errors). Each item gets the speed check and the three-role smoke test. Do not touch the work install or real tenant data; real-data checks stay with the owner.

1. **Ask routing.** Run the keyword and library match BEFORE the model router; a library hit never waits on the model (about 25 s on a CPU-only local model today). Router only on a library miss. Test: a library question answers in under 2 s with the provider unreachable.
2. **People & devices on real-shaped data.** About 18 s at 1.9M auth and 5.7M DNS events (bench lake: 2.7 s). Target under 3 s. Profile on the synthetic scale lake first (likely a full scan or a per-row identity lookup); make the bench lake real-shaped (many distinct users, DNS-heavy) so it catches this.
3. **AI usage > People empty for Last 7 days** while `claude_hooks` has 35 events 5 days old. Check the time filter and that hooks plugin events (not only Claude Code telemetry) feed the table. Test with hooks-only data.
4. **One healthy count.** Health "N of M healthy" and the Dashboard footer use one function (today Health says 4 of 6 with 2 quiet sources; the footer says 6 of 6 flowing, no gaps). Also leave refusal-only sources (`server_events`, which records only refused credentials, so quiet is expected) out of the footer's "longest wait".
5. **Unsanctioned AI alert (for example Gemini).** (a) Resolve the device to a person through the hooks plugin's host mapping, not only the identity map. (b) "Why it matters" follows the catalog status; Not approved gets its own wording.
6. **Person page "What it did".** The Palo Alto USERID row shows the raw CSV line as its subtitle; use the parsed summary as #425 did elsewhere. Fixture test.
7. **Low.** Suggested source groups on Users and access list only `server_events`; Logs opens on the SQL tab (should open on the plain search).

8. **Scheduled backups.** The work install has never run one (only four hand-run files from Oct 22). Daily backup schedule, on by default for new installs, 14 kept, time and count in Settings; a Health row with the last backup and its age; an alert when none for 48 hours. Document the restore steps. Test with a frozen clock.
9. **Remnant's own access log as a source.** Request and sign-in lines (user id, client IP, path, status) go only to journald, so "who is this IP" cannot be answered inside Remnant. Write them into the `server_events` source (metadata only, no request bodies, no tokens), with a template and fixture. Integration test: a client IP from a sign-in is searchable in Logs.

Then, carried over:

1. Lake and rollup files 0444 for non-root installs, with an in-place overwrite test; SPEC 5.1 wording to match (owner-approved follow-up to #450).
2. ADR-0048 slice 0: View people in AI usage permission and masking (ADR-0029 G1 to G3).
3. Tooling batch: speed check rounds sized from measured spread (BACKLOG); `--rounds` maximum is 8; fix the flaky eval test (`tests/evals/test_nl_suite.py`: fake provider named from `id()` can repeat).
4. ADR-0046 fast YAML loader with alias and depth tests (accepted, not built).
5. Backlog, ranked: person page under 2 s; per-file account record for Identities scoping; remaining Logs page queries to the server; user SQL in a read-only worker process (later).

## Owner actions pending

- Turn on Dependabot security updates in the dev repository settings.
- Set the `CI_RUNNER` repository variable once the self-hosted runner is up.
