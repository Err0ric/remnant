# ADR-0011: Grafana Loki as a source

Status: **Accepted** 2026-10-11 (reviewed by the project owner; see Review outcome).

## Context

Many teams already collect their logs in Grafana Loki. Reading from Loki lets them try the product on those logs with no new collection pipeline. Today the only ingest path is files and folders (Slice 1); connectors are Slice 7 and the spec does not mention Loki.

Loki stores log lines in streams identified by labels (`{job="syslog", host="fw01"}`) and serves them over HTTP: `GET /loki/api/v1/query_range` with a LogQL query, a start and end in nanoseconds, a `limit`, and `direction=forward`, returning streams of `[timestamp_ns, line]` pairs. Multi-tenant installs need an `X-Scope-OrgID` header. Servers cap entries per query (`max_entries_limit_per_query`, 5000 by default).

Loki keeps the lines as received, so the deterministic pipeline (envelope, then payload template) can parse them the same way it parses a file.

## Decision

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. Shape | A pull connector: a source of kind `loki` with a base URL and a LogQL **stream selector** (label matchers only, optionally one `\|=` line filter). The ingest worker polls every 30 s with `query_range`, `direction=forward`, a `limit` of 1000 | Polling is simple, restartable, and works through proxies; the selector keeps Loki doing the narrowing | Loki's websocket tail endpoint (harder to resume after a gap) |
| 2. Parsing | Each line is a frame through the normal pipeline with the source's template, exactly as a line from a file; `raw` is the Loki line unchanged. Stream labels go to `envelope.loki_labels` | One parser path; `raw` stays sacred (CLAUDE.md rule 5) | Map labels straight into columns |
| 3. Checkpoint and duplicates | The checkpoint is the last timestamp read plus a hash of each line seen at that exact nanosecond; the next poll starts at that timestamp and skips lines already seen. Each poll ends 30 s before now so late lines in Loki are still picked up | No gaps and no doubles across restarts and across lines sharing a timestamp | |
| 4. First run | Reads back `backfill_hours` (default 24, at most the source's retention) | Useful data on day one without pulling a whole Loki store | Start from now |
| 5. Authentication | None, basic auth, or bearer token, plus an optional tenant (`X-Scope-OrgID`). Secrets encrypted with the install key and never returned, as for alert targets | Covers Loki behind a gateway and Grafana Cloud | |
| 6. Network safety | The same address rules as webhooks (ADR-0007 row 4): `https` for public hosts, `http` allowed for private and loopback; metadata and link-local addresses refused; address resolved once and pinned; no redirects | Same SSRF stance as every outbound call | |
| 7. Who | Admins add, change, and remove Loki sources (audited); classification defaults to `local_only` like every source | Same as file sources | |
| 8. Health | The Sources page and Overview show last poll, lines read, lag behind Loki, and errors; non-admins see a generic error, as today | Visible failures | |
| 9. When | Build it now as the first connector, ahead of Slice 5's remaining items: a small `Connector` interface (poll, checkpoint, health) that Slice 7's connectors reuse | A real team can try the product against their real logs without new plumbing; the interface was planned anyway | Keep it in Slice 7 |

## Questions for the owner

1. **Timing (row 9):** build the Loki source now as the first connector (recommended), or keep it in Slice 7?
2. **Query scope (row 1):** stream selectors plus one line filter only (recommended), or full LogQL log queries?
3. **First run (row 4):** back-fill 24 hours (recommended), or start from now?

## Consequences

- `ingest/connectors/base.py` (interface) and `ingest/connectors/loki.py`; the watcher loop runs connector sources beside file sources.
- `SourceConfig` gains `kind` (`file` or `loki`) and Loki fields; meta stores the checkpoint and encrypted credentials. Additive migration.
- Sources page: kind choice on Add source, Loki fields, and a "Test connection" that runs one small query.
- Fixtures: a fake Loki server in tests (no network), with streams that share timestamps, arrive late, and span a restart.
- SPEC 3.5 and 3.7, the Slice 7 DoD line for connectors, and `docs/ingest/` (pointing guide) updated. BACKLOG row moves into the plan.

## ATT&CK

| Threat | ATT&CK | Control |
|---|---|---|
| Loki URL aimed at internal services or metadata | CWE-918 Server-Side Request Forgery | Row 6 |
| Loki credentials leaked from the app | T1552 Unsecured Credentials | Encrypted at rest, write-only in the API, never logged |
| Hostile content in Loki lines | T1027 Obfuscated Files or Information (log content crafted to mislead) | Lines are untrusted like any log line: escaped on render, bound in SQL, data-only in prompts |
| Silent gaps in collection | T1562.006 Indicator Blocking | Checkpoints, lag shown on Sources and Overview |

Not AI-facing, so no ATLAS mapping.

## Review outcome

| Question | Answer |
|---|---|
| 1. Timing | Now, so it can be tried against an existing Loki instance early |
| 2. Query scope | The recommendation: a label selector plus optional line filters |
| 3. First run | Back-fill 24 hours by default, adjustable per source (up to the source's retention) |

Implementation notes: a line whose parser finds no timestamp takes Loki's timestamp as its event time, so it still sorts and filters by time; the Loki stream labels are kept in `envelope.loki_labels`.
