# History

Material moved out of CLAUDE.md on 2026-11-08 to keep it short. Nothing here is a current rule unless CLAUDE.md says so.

## Why the remote layout checks exist (D207)

- The session environment can reset `origin` to the public repository with pushing enabled (it has, twice, once with `main` reset onto the public history). Two guards that do not depend on remembering (D207): `scripts/dev/session-check.sh`, run first in every session (section 8), puts the remotes back to this layout, points `main` at `origin/main`, warns when `main` holds commits that are not on `origin/main`, installs the pre-push guard, and prints `git remote -v`; the guard (`scripts/dev/pre-push`, installed into the checkout's hooks folder because git does not commit hooks) refuses any push whose URL is the public repository unless `REMNANT_PUBLISH=1`, which `publish.sh` sets only for its own two pushes, after the scans pass. `session-check.sh --verify` changes nothing and exits with one line naming the failed check when origin's fetch or push URL is not the dev repository, the public remote can push, local `main` does not track `origin/main`, or `origin/main` shares any commit with the public `main` (publishing never pushes dev commits, so the two histories share none); the queue runs it before every PR and every push, and `publish.sh` before it copies anything, and both stop on a failure. The check and the guard are export-ignored, like `scripts/publish`. Tests: `bash scripts/dev/test.sh` and `bash scripts/publish/test.sh`. The environment's unpushed-commits check compares branches against `origin`, so with this layout it sees merged and pushed work as pushed

## Definition of Done, slices 1 to 8 (completed)

A slice is done when every box below is checked, demoed end to end from a fresh `docker compose up`, and tagged `slice-N`.

### Slice 1: files to query, no AI
- [x] Loopback bind with no users runs without login (single-user local convenience)
- [x] Non-loopback bind with no users enters setup-only mode and prints a one-time setup link; the setup page says it is creating the administrator account; the link is single use and expires in 30 minutes
- [x] After setup: login, logout, Argon2 hashes, secure session cookie, CSRF, login rate limit
- [x] HTTPS by default off loopback with a generated self-signed cert; bring-your-own cert documented
- [x] `docker compose up` on a VM reaches the setup link with no manual credential step (verified 2026-10-10 on a Debian 13 LXC on Proxmox, after #54)
- [x] Source can be added pointing at a file or folder under `allowed_roots`, with tail/watch
- [x] JSON lines, CSV (with header), and syslog files ingest; RFC 3164 and 5424 envelopes parsed; headerless lines stored with `parse_status=envelope_only`
- [x] Relay headers stripped and counted; truncated and non-UTF-8 lines stored with flags
- [x] Windows events via NXLog JSON, Winlogbeat JSON, and Snare CSV land with `raw` intact (generic parsers, no OCSF mapping yet beyond time and message)
- [x] Parquet partitioned by `source/day`; compaction and retention jobs run and are tested
- [x] Query mode: SQL editor, guard enforced, results table with raw/parsed toggle, export CSV
- [x] Envelope test matrix and ingest integration test pass
- [x] `docs/ingest/` has rsyslog, syslog-ng, and Vector guides that were actually tried once (rsyslog and syslog-ng on the homelab; Vector 0.59.0 on an Ubuntu 24.04 VM by `release-checks.yml`)
- [x] CLI: `login` (keychain token), `tail -n/-f`, `query`, `--since`, `--where`, `--format table|json|csv|raw`, control sequences stripped

### Slice 2: provider + Ask mode + saved searches + team access
- [x] `Provider` protocol and OpenAI-compatible adapter; Ollama compose profile
- [x] Locality computed from URL; UI shows local/cloud badge
- [x] Ask mode returns SQL + explanation; SQL is visible; nothing runs without click
- [x] Follow-up refinement works for 3 turns
- [x] `preview_query` tool capped at 5 rows
- [x] Saved searches: create from Query and Ask, params, tags, YAML import/export round-trips
- [x] `llm_calls` audit rows written with hashes for every call
- [x] Gate exists and is the only path (CI grep passes), even though classification UI is Slice 5
- [x] Users: invite, disable, reset; Admin, Analyst, Auditor roles enforced on every route
- [x] Source groups: admin grants groups to users; per-session `events` view includes only permitted sources; integration test proves a restricted source is invisible to Query, Ask, saved searches, CLI, and the gate scope
- [x] Saved searches private or shared; shared searches run with the caller's permissions
- [x] Audit log records user id for queries, exports, logins, admin changes, and LLM calls
- [x] Per-user API tokens for the CLI, revocable
- [x] CLI: `search`, `ask` (prints SQL, `Run? [y/N]`, never auto-runs)
- [x] NL eval harness with at least 100 questions over fixture data; results reported per model in the PR (SPEC 5.7) (qwen3.5:9b, Thinking off, `ask.v4`: 99% executable, 87 to 88% exact over two runs, 2.0 s median; results in `backend/evals/nl_queries/README.md`)
- [x] Semantic layer YAML loaded into Ask prompts; verified saved searches used as few-shot examples
- [x] Self-check loop: guard plus preview, up to two automatic refinements, every attempt audited

### Slice 3: templates + LLM parser flow + EVTX
- [x] Source discovery over a folder: candidates grouped by host and pattern, sniffed, matched to templates
- [x] Templates declare `category`; suggested groups shown as an approve-only checklist; nothing auto-granted; acceptances audited
- [x] Template schema validator with clear error messages
- [x] All payload formats implemented and unit tested
- [x] Starter pack from SPEC 4.4 shipped, each with fixtures and >= 95% parse rate
- [x] Shared Windows EventID to OCSF map used by NXLog, Snare, Winlogbeat, and EVTX paths
- [x] Native EVTX ingestion via `evtx` library
- [x] Parser draft flow: deterministic envelope and format sniff, LLM drafts payload block only, preview table, test run, approve moves file out of `drafts/`
- [x] Manual path works with no provider configured

### Slice 4: Sigma + explain with citations
- [x] pySigma DuckDB backend with the compatibility pipeline (`detect/pipelines/compat.py`) compiles the SigmaHQ core rule set for `linux` and `windows` logsources; compile rate reported in the PR and recorded in `docs/SPEC.md`
- [x] OCSF-native pipeline is not started; a stub file and a `docs/BACKLOG.md` entry are enough
- [x] Rules run on demand over a time range and on a schedule; matches stored with rule id and event ids
- [x] Saved searches can be scheduled (cron or presets); runs store count, duration, capped sample, and `sources_in_scope`; last 30 runs kept
- [x] Schedules run as the owner with permissions re-checked each run; pause on loss of access; never re-ask the LLM
- [x] Dashboard page: panel per schedule with last run, count, sparkline, threshold or change flag, top rows, click-through to Query; panels hidden from viewers lacking source access
- [x] "Explain these events" accepts a selection, sends only those events (capped), returns claims with `event_ids[]`
- [x] Citation verifier marks unverified claims in the UI and logs `citation_check`
- [x] Report draft exports Markdown with inline event id references
- [x] Alert routing: email (SMTP), Microsoft Teams, Slack, generic webhook; per-rule and per-schedule targets; test-send button; failures retried and shown

### Slice 5: classification gate + redaction + full audit
- [x] Source classification UI, default `local_only`
- [x] Cloud provider blocked when any in-scope source is `local_only`; block is surfaced in UI and logged
- [x] Redaction tokens stable per install; reverse map applied to responses (opt-in per provider, off by default per D36)
- [x] Audit log viewer and export; delete trigger tested
- [x] Anthropic adapter if not already landed (unit-tested against a fake server; not yet tried against the live API)

### Slice 6: polish and release
- [x] Light mode complete per `docs/DESIGN.md` (every page checked in light; all text tokens meet WCAG AA 4.5:1 in both themes)
- [x] Command palette covers navigation, sources, saved searches, run, provider switch
- [x] CLI `tui` (Textual): query box, results table, tail pane (baseline; optional `tui` extra)
- [x] Install guides: team VM (Compose and systemd) and single user (Compose and single-user tried on the homelab; the systemd unit, copied from the guide, installed and run on an Ubuntu 24.04 VM by `release-checks.yml`: setup link, HTTPS health, restart, and a syslog message ingested and queried under the sandbox, `systemd-analyze security` 1.4 OK; the same unit, hardening included, ran unchanged in an unprivileged Proxmox LXC on Debian 13 on 2026-10-21 and survived a reboot)
- [x] README states tested scale (ingest rate, lake size, query latency on named hardware) (2 vCPU cloud VM and 4 vCPU homelab container via `scripts/bench.py`)
- [x] SBOM generated, images pinned, release tagged `v0.1.0` (SBOM from lockfiles in every CI run via `scripts/sbom.py`; base images, compose images, and workflow actions pinned by digest or commit and enforced by `check-architecture.sh`; tagged 2026-10-17 on the owner's go-ahead)

### Slice 7 (v0.2): connectors
- [x] `Connector` protocol, scheduler in the ingest worker, checkpoints, de-duplication, backoff, health on the Sources page
- [x] Microsoft 365 connector per ADR-0002: Management Activity API content types and Graph sign-ins, directory audits, alerts; setup guide with exact permissions; templates mapping to OCSF (tested against fake endpoints; running against a live tenant on the test install since late October 2026)
- [x] Native syslog listener (UDP, TCP with octet counting, TLS) per ADR-0021 (tested with real sockets in the suite and a live server; first device on the homelab pending)
- [x] Read-only MCP server per ADR-0003: `get_schema` and `run_query` only, per-user tokens, `local_only` results withheld unless the endpoint is marked local, every call audited, off by default (tested in the suite and against the official MCP Python client; Claude Desktop and Claude Code against the homelab pending)
- [x] AI usage visibility per ADR-0015: OTLP/HTTP JSON receiver with per-source tokens (content dropped by default); Claude Code telemetry template; AI service catalog and shadow-AI view; MCP inventory (telemetry and endpoint script) with allowlist; AI usage page; AI watch alerts; Anthropic usage, cost, Claude Code, analytics, and compliance activity connectors (connectors tested against a fake API; live key and the PowerShell script pending)
- [x] Optional endpoint agent per ADR-0017: generated OpenTelemetry Collector configs per agent group, Windows XML and journald conversion at the receiver, install guide (configs tested by conversion of sample payloads; first run on real endpoints pending)
- [x] Health page per ADR-0019: one view of sources, connectors, per-machine agents, watched devices (seen in events, never contacted), alert targets, and schedules; silence and volume-drop alerts for watched devices
- [x] Investigation per ADR-0016: AI toggle in the Search bar, facet sidebar, Suspicious presets, entity risk, investigator graph with AI flow mode
- [ ] Okta, Google Workspace, AWS CloudTrail connectors (deferred by the owner 2026-10-17; in `docs/BACKLOG.md`)

### Slice 8 (v0.3): enrichment, integrity, tiering
- [x] GeoIP/ASN and threat intel enrichment at query time, with feed freshness shown (per ADR-0023: DB-IP Lite, abuse.ch Feodo Tracker and ThreatFox, uploaded lists; local lookups only; automatic updates off until turned on; freshness on Settings > Enrichment and Health)
- [x] Hash-chained partitions, scheduled verification, integrity report export (per ADR-0022: a ledger of every lake file plus an audit row chain, daily and on-demand checks, signed seals with optional off-server copies, signed JSON report)
- [ ] Object-storage tier for older partitions, queried in place (deferred by the owner 2026-10-17; in `docs/BACKLOG.md`)
- [x] Case handoff to TheHive / DFIR-IRIS / webhook (per ADR-0024: any alert target, webhook JSON or a short chat/email list; native TheHive and DFIR-IRIS not built, by the owner's choice)

