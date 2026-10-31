# ADR-0036: Live mode on Search

Status: **Accepted** 2026-10-22 (project owner), with the answers to the open questions written into rows 5 and 12. From the owner's proposal (live results on Search, ADR first, stop for review). Recorded as SPEC D101.

## Context

Search runs a query once over a range. To watch something happen (a test login, a new agent rolling out, a firewall change) an analyst presses Run again and again. The CLI already follows a source (`tail -f`) and the TUI has a tail pane; both poll `/api/query` every few seconds with a cursor on `time_observed` and `event_id` (`app/cli/tailing.py`), so every poll goes through the guard, the per-user `events` view, and the query audit.

Events reach the lake within a few seconds of arrival: the file watcher polls every `ingest.poll_interval_s` (2 s), the syslog listener flushes every 0.5 s, connectors pull on their own schedule (minutes). Live mode can only be as fresh as the slowest of these for the sources in scope, so it must say how fresh each source is.

## Decision

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | Where | A **Live** toggle next to Run on Search. On: the results table keeps the last N rows (default 500, newest at the top) and appends new events as they arrive; the range picker is replaced by "Live since 14:02 UTC". Off: the table stays as it is, a normal result you can export or explain | One place; no new page | A separate Live page (another place to look; duplicates Search) |
| 2 | Which queries | Row queries only: `SELECT ... FROM events WHERE ...` with no `GROUP BY`, aggregate, `DISTINCT`, window, `UNION`, or `LIMIT` other than the live cap. The guard already parses the SQL (sqlglot); live mode adds this shape check and says why when a query does not qualify ("Live works on event rows. Remove GROUP BY, or use Run.") | A follow cursor needs one row per event; an aggregate cannot be appended to | Re-running aggregates every N seconds (a hidden schedule; heavier and easy to leave running) |
| 3 | Transport | Server-sent events: `GET /api/search/live?q=<sql>` returns `text/event-stream` with `rows`, `lag`, `notice`, and `end` events. Sent with `Cache-Control: no-cache` and `X-Accel-Buffering: no` so nginx, Caddy, and forward-auth proxies pass it through. A dropped connection is a stop; the browser reconnects only if the user turns Live on again | One-way, works over plain HTTPS, the session cookie applies, no new library; proxy settings go in `docs/install/tls.md` | WebSocket (two-way not needed; more proxy setup); the browser polling `/api/query` (works today, but each poll is a full audit row and a cold query) |
| 4 | How the server finds new rows | The server keeps the same cursor the CLI uses (`time_observed` at or after the newest seen, `event_id` not yet sent), polling every 2 s on the caller's per-session `events` view through the guard, on the read-only connection, with the normal query timeout and memory share. The cursor lives in the stream, not the client | Rule 7 and 13 unchanged: same guard, same view, same scope, nothing trusted from the client but the SQL | A push from the writer (lower latency, but couples ingest to query sessions and skips the guard) |
| 5 | Limits | At most **2 live streams per user**, counting browser, CLI, and TUI streams together (the limit protects DuckDB; the client does not matter). A third is refused with which streams are open and since when ("You have 2 live searches open: Search in a browser since 14:02 UTC, `tail -f` since 13:40 UTC") and a **Stop** button on each, so the user can free one and start. Each stream stops after the **live time limit**, the same for every role: one administrator setting, default 30 minutes, changed on Settings and audited `settings.live_limit` with from and to. On the limit the stream sends an `end` event saying so and the page shows **Resume**. At most 500 rows per push; a stream that would send more than 1,000 rows in a push says "More than 1,000 new events in 2 seconds; narrow the search" and stops | Keeps a forgotten tab from holding a DuckDB slot all day | Per-role limits (more settings, same protection) |
| 6 | Audit | One `search.live_start` row (user, SQL hash and text, sources in scope) and one `search.live_stop` row (reason: user, time limit, disconnect, error; duration; events sent). Polls are not audited one by one | Every action attributable (rule 14) without 900 rows per half hour | A row per poll (the audit log fills with noise) |
| 7 | Freshness per source | The stream sends a `lag` event every 10 s: for each source in scope, the newest `time_observed` and how long ago it was. Shown above the table as "Live. fw-edge 3 s, m365 4 min (pulls every 5 min)" in muted text, and a source silent for more than its expected gap shows in `--warn`. A connector source states its pull interval so a 4-minute gap reads as normal | The user must know which sources are actually live | One overall "Live" badge (hides a slow connector) |
| 8 | Access changes mid-stream | Each poll runs on the view built at the start. If an admin removes the user's access to a source, the stream ends at the next poll with "Your access changed; start Live again" (the session view is rebuilt on access change today) | Same as schedules: permissions re-checked, never silently widened | Keeping the old view until the 30-minute limit |
| 9 | LLM | None. Explain and Ask work on a paused or stopped live table like any result, through the gate as today | No new AI surface | Live AI summaries (a model call per push; cost and leakage) |
| 10 | CLI and TUI | `remnant tail -f` and the TUI tail pane move to the same endpoint (the CLI reads the stream instead of polling), so the limits, audit, and lag apply to all three. `--where` and `--source` become the SQL the stream follows | One code path, one audit shape | Leaving the CLI on polling (two follow implementations to keep in step) |
| 11 | Shared links | A Search link opened with Live on (`/search#...&live`) does **not** start Live; it opens the query with the toggle off and a hint to turn it on | Opening a link should not start a long-running stream or write an audit row the user did not intend | Auto-start (surprising; counts against the 2-stream limit) |
| 12 | Pause and Resume (owner answer) | **Pause ends the stream on the server**: the cursor (newest `time_observed` and the last event ids shown) stays in the page. **Resume** starts a new stream from that cursor and first sends what arrived while paused, up to the 1,000-row buffer; beyond it the stream says "1,000 of N events since you paused; showing the newest" and continues. A paused search holds no DuckDB work, does not count toward the 2 streams, and does not run its time limit; Resume starts a fresh limit and writes a new `search.live_start` row (with `resumed: true`) | Paused costs nothing | Keeping the stream open while paused (holds a slot for nothing) |

### Screen

```
+------------------------------------------------------------------------------------+
| SQL editor                                                   [Live (on)] [Run]     |
| Live since 14:02 UTC. fw-edge 3 s, linux-auth 2 s, m365 4 min (pulls every 5 min)  |
| 128 events, newest first                                   Pause   Stop   Export   |
| time        source    host     message                                             |
| 14:09:41    fw-edge   fw01     deny tcp 203.0.113.9:443 ...                        |
+------------------------------------------------------------------------------------+
```

**Pause** ends the server-side stream (row 12) and keeps the table still; **Resume** starts a new stream from the last event shown; **Stop** ends it and clears Live. New rows get a short `--accent-subtle` row tint that fades once (one motion, respecting reduced motion).

## As built (2026-10-31, part 1: server)

- `app/search/live.py`: the shape check (sqlglot: one SELECT from `events`, no WITH, JOIN, subquery, GROUP BY, HAVING, DISTINCT, aggregate, window, UNION, or LIMIT; placeholders only `{{start}}`/`{{end}}`), the cursor columns `_live_t`/`_live_id` and `time_observed >= $since` added server side, the registry (2 per user), and the lag query. `app/api/live.py`: the SSE endpoint, streams list and stop, the limit setting.
- The cursor reads partitions from one day before the stream's start (`LOOKBACK`), so a poll stays a small query; an event whose own time is older than that and arrives during the stream is not followed. Recorded in the release note.
- The refusal of a third stream is a 409 naming the open streams; the page lists them with Stop from `/api/search/live/streams`.
- A keep-alive comment is sent on polls with no rows, so proxies with a 60 s read timeout keep the stream.

## As built (part 2: Search)

- The switch sits beside Run on the SQL tab and follows the editor's SQL at the moment it is turned on; editing the SQL afterwards does not change the stream (turn Live off and on).
- The browser reads the stream with `fetch`, not `EventSource`, so a refusal's reason (400 shape, 409 third stream) is shown; the 409 panel lists open streams from `/api/search/live/streams` with Stop.
- Row 11: Live is never written to the address, so a shared link cannot start it; there is no hint to show.
- The range picker stays visible while Live is on; the panel's header states "Live since".
- The time limit setting is on Settings > About.

## As built (part 3: CLI and TUI)

- `Api.live` reads the stream with httpx (read timeout 60 s; the server writes every 2 s). `tail -f` prints the latest lines through `/api/query` as before, then follows from the newest line shown (`since`, `after`); the poll reads partitions from a day before that cursor or the stream's start, whichever is earlier.
- The stream's `end` and `notice` messages go to stderr; `tail -f` exits 0 at the time limit.
- The old polling follow (`TailCursor.poll`) is removed; `--interval` stays as an ignored, hidden option so old scripts parse.

## Consequences

- Watching something happen no longer means pressing Run repeatedly, and the CLI, TUI, and browser follow the same way.
- Each open stream holds a polling task and runs a small query every 2 s. With the limits above, a 10-analyst team is at most 20 streams, each a cursor query over the last few seconds; the scale test should prove this does not delay schedules.
- A new SSE endpoint must pass through proxies; `tls.md` gets the settings (buffering off, read timeout above 30 minutes or the stream ends early, which is already handled as a disconnect).
- Work: endpoint, shape check, limits, and audit (one PR, backend tests including scope and access change); Search toggle, lag line, Pause and Stop (one PR); CLI and TUI moved to the stream (one PR).

## Owner answers (2026-10-22)

1. The time limit is the same for every role: one administrator setting, default 30 minutes, audited (row 5).
2. CLI and TUI streams count toward the 2 streams; the refusal names the open streams and offers to stop one (row 5).
3. Pause ends the server-side stream; Resume restarts from the last event seen with up to 1,000 rows of backfill; paused time counts toward nothing (row 12).
4. Event-row queries only (row 2), shared links never start Live (row 11), and ending the stream on an access change (row 8) are kept.

## ATLAS / ATT&CK

No AI surface (row 9). Resource exhaustion by many open streams is bounded by rows 5 and 8 (ATT&CK T1499, endpoint denial of service, as an internal-misuse risk). Exposure is unchanged: a stream returns only what the same user could get from `/api/query`.
