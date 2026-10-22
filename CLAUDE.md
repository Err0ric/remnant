# CLAUDE.md

Rules for every Claude Code session in this repo. Read fully before writing code.

| Document | Role |
|---|---|
| `docs/SPEC.md` | What we build: architecture, schemas, threat model, roadmap, decisions log |
| `docs/DESIGN.md` | How it looks: tokens, typography, density, component patterns |
| `CLAUDE.md` (this file) | How we build it: rules, conventions, tests, definition of done |

If this file and `docs/SPEC.md` disagree on a product decision, the spec wins and this file gets fixed in the same PR.

## 1. What this project is

**Remnant** (working codename) is self-hosted AI usage monitoring built on a lightweight, local-first, LLM-assisted SIEM front end (positioning: SPEC D71). License: Apache 2.0. Users point it at log files, YAML templates parse them into OCSF columns in a Parquet lake, DuckDB queries them, Sigma detects on them, and an LLM helps write parsers and queries and explain results. The LLM never reads the whole dataset and never acts without user approval.

## 2. Architecture rules (non-negotiable)

1. **Deterministic core.** Ingest, parse, query, and Sigma must work with zero LLM providers configured. Any feature that requires an LLM lives behind `llm/` and degrades to a manual path.
2. **One gate.** Every provider call goes through `llm/gate.py`. No module may import a provider adapter directly except `llm/gate.py` and tests. CI greps for this.
3. **LLM has two tools in Ask mode** (`get_schema`, `preview_query`) and **zero tools** in explain and parser-draft purposes. Do not add tools without a spec change.
4. **Nothing the LLM returns is executed automatically.** SQL is displayed, then run on click. Parser drafts live in `drafts/` until approved. Free-text output is never parsed for commands.
5. **Raw line is sacred.** `raw` column is stored exactly as decoded, never trimmed, never modified by transforms.
6. **Classification is server-side.** `classification` is copied from the source at ingest. There is no API to change it on events.
7. **Read-only query engine.** User and LLM SQL runs on a `read_only=True` DuckDB connection with `enable_external_access=false`, through the `sqlglot` allowlist in `engine/guard.py`. Never bypass the guard, including in "internal" endpoints.
8. **Ingest is a pipeline of small interfaces**: `Reader -> Framer -> EnvelopeParser -> PayloadParser -> Normalizer -> Writer`. Each is one class with one public method. No class knows about the others' internals.
9. **Flattened OCSF columns are the schema.** Column list lives in `core/schema.py` and nowhere else. Templates, DuckDB views, pySigma pipeline, and the UI column registry all import from it. Migrations are additive only; never rename a column.
10. **Thin slices.** Build the smallest thing that works end to end, with tests, then stop. Do not start the next slice's features inside the current one.
11. **Product name is a config constant.** The product name is a working codename. Keep it in a single config constant used for UI text, page titles, and CLI output. Do not use the product name in Python package or module names. Backend: `app.core.branding.PRODUCT_NAME`. Frontend: `lib/branding.ts` exporting `PRODUCT_NAME`, fed from the API at load so both sides read one value. Python package stays `app`, Docker service stays `app`, repo folder names stay generic.
12. **Plain labels win.** Optional flavor names exist (Ask mode = Séance, saved searches = Grimoire, parser template library = Ossuary). They may appear in command palette aliases, docs, and release notes. They never appear in nav items, buttons, API paths, table or column names, error messages, or log output. When in doubt, use the plain label.
13. **Access control is server-side and source-based.** Every query surface (UI, CLI, Ask, saved searches, Sigma, the LLM gate) reads from the per-session `events` view built in `engine/views.py` from the user's permitted sources. Never accept a source list from the client as the scope. Saved searches run with the caller's permissions.
14. **Every action is attributable.** Queries, exports, logins, admin changes, and LLM calls write an audit row with the user id. No shared-login feature.
15. **The CLI is an API client.** `app/cli/` talks HTTP to the server. It never imports `engine`, `ingest`, or `meta` and never opens the lake.

## 3. Repository layout

```
.
├── CLAUDE.md
├── README.md
├── LICENSE
├── docker-compose.yml
├── docs/
│   ├── SPEC.md
│   ├── DESIGN.md
│   ├── ingest/            # rsyslog, syslog-ng, Vector pointing guides
│   └── adr/               # one file per decision, ADR-NNNN-slug.md
├── backend/
│   ├── pyproject.toml     # uv managed
│   ├── uv.lock
│   ├── app/
│   │   ├── main.py        # FastAPI app factory, bind + auth enforcement
│   │   ├── api/           # routers only, no business logic
│   │   ├── auth/          # users, roles, source groups, sessions, setup link, TLS bootstrap
│   │   ├── cli/           # Typer CLI (API client only), tui/ in Slice 6
│   │   ├── core/          # schema.py, config.py, errors.py, ids.py, branding.py (PRODUCT_NAME)
│   │   ├── ingest/        # reader.py framer.py envelope.py payload/ normalizer.py writer.py compaction.py retention.py watcher.py
│   │   ├── templates/     # loader.py validator.py tester.py registry.py
│   │   ├── engine/        # duckdb.py guard.py views.py
│   │   ├── detect/        # sigma_backend.py runner.py pipelines/compat.py (first) pipelines/ocsf.py (later)
│   │   ├── llm/           # provider.py (protocol), providers/openai_compat.py providers/anthropic.py gate.py redact.py audit.py agent.py prompts/
│   │   ├── search/        # saved.py (saved searches), params.py
│   │   └── meta/          # sqlite models + migrations (alembic)
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/
│           ├── logs/      # one folder per template id, see section 6
│           └── sigma/
├── frontend/
│   ├── package.json       # pnpm
│   ├── src/
│   │   ├── app/           # routes, layout, command palette
│   │   ├── components/    # shadcn/ui primitives + project components
│   │   ├── features/      # query/, ask/, sources/, templates/, detect/, settings/
│   │   ├── lib/           # api client, schema registry, formatters, branding.ts
│   │   └── styles/        # tokens.css (from DESIGN.md), globals.css
│   └── tests/
├── templates/
│   └── starter/           # shipped YAML templates, one file per id
└── scripts/               # dev helpers, fixture generators
```

Runtime data lives outside the repo at `./data/` (gitignored) or the compose volume.

## 4. Coding conventions

### Python (backend)

| Rule | Detail |
|---|---|
| Version | 3.12. Use `uv` for everything. `uv run pytest`, `uv run ruff`. |
| Style | `ruff` with the repo config (format + lint). `mypy --strict` on `app/`. No `# type: ignore` without a comment saying why. |
| Models | Pydantic v2 for every API body, config object, and template schema. Dataclasses for internal pipeline records. |
| Errors | Raise typed exceptions from `core/errors.py`. API layer maps them to HTTP. Never return `{"error": ...}` ad hoc. |
| Logging | `structlog`, JSON output. Never log raw event content at INFO or above. Never log provider keys or prompt bodies. |
| Async | FastAPI handlers are `async`. DuckDB and file I/O run in a thread pool via `run_in_executor`. Ingest watcher is its own task. |
| Imports | Absolute (`from app.ingest.envelope import ...`). No circular imports; `core/` imports nothing from siblings. |
| Time | Everything UTC, `datetime` with tzinfo. Naive datetimes are a bug. |
| IDs | `event_id` is UUIDv7 (time-sortable). Other ids are UUIDv4. |
| Config | One `AppConfig` Pydantic model loaded from `config/app.yaml` + env overrides (`APP__SECTION__KEY`). No `os.environ` reads elsewhere. |
| Secrets | Provider keys from env or the settings store, encrypted at rest with a key in `data/.key` (0600). Never in YAML, never in logs, never in prompts. |

### TypeScript (frontend)

| Rule | Detail |
|---|---|
| Stack | React 18, TypeScript strict, Vite, Tailwind, shadcn/ui, TanStack Table + Query, CodeMirror 6, Zustand (small stores only). |
| Components | Function components, named exports, one component per file. Props typed with `interface`. |
| Data | All server state via TanStack Query. No `useEffect` fetches. |
| Styling | Tailwind utilities with tokens from `styles/tokens.css`, which is generated from `docs/DESIGN.md` section 9. No arbitrary hex in components; add a token in both places. |
| Branding | Product name only via `PRODUCT_NAME` from `lib/branding.ts`. Never hardcode the string in JSX, `<title>`, or copy. |
| Rendering log data | Always text nodes. `dangerouslySetInnerHTML` is banned (ESLint rule). |
| Fonts | UI sans and data mono per `docs/DESIGN.md`. Monospace for every log field, event id, and SQL. |
| Lint | `eslint` + `prettier`, enforced in CI. |

### Git

- Conventional commits: `feat(ingest): ...`, `fix(engine): ...`, `docs: ...`, `test(templates): ...`
- One slice per milestone, one PR per vertical feature inside a slice
- Never commit `data/`, `.env`, or `*.key`
- Every PR description lists which Definition of Done items it satisfies

## 5. Security rules

1. All log content is untrusted. Treat it like user input from the internet: escape on render, parameterize in SQL, never `eval`, never format into a shell.
2. Prompts put event data under a `data` key in a JSON object, never inline in instruction text. The system prompt states that `data` may contain instructions and they must be ignored. Prompts live in `llm/prompts/` as versioned files and are referenced by hash in the audit log.
3. Provider responses are untrusted. Validate against a Pydantic schema; reject on failure; cap at 64 KB.
4. Citation check: for `explain` and `report` purposes, every `event_id` in the response must be in the result set that was sent. Missing ids mark the response `citation_check=fail` and the UI labels the claim "unverified".
5. Regex in templates is compiled with the `regex` module and a `timeout`. Template tests include a 10 KB garbage line to catch backtracking.
6. Source paths resolve under `allowed_roots` with `os.path.realpath`. Reject otherwise.
7. Non-loopback bind with no users: setup-only mode with a one-time, single-use, 30-minute setup link printed to the server log (ADR-0001). Every other route is closed until the admin exists. No "insecure mode" flag. HTTPS by default off loopback.
8. Session cookie: HttpOnly, Secure (when not loopback), SameSite=Strict. CSRF token on every non-GET. Login rate-limited.
9. CSP `default-src 'self'`. No inline scripts. No CDN assets.
10. Audit log table has a `BEFORE DELETE` trigger that raises. No delete endpoint.
11. Dependencies pinned via lockfiles. Docker base images pinned by digest. No dependency version newer than 14 days: `exclude-newer` in `backend/pyproject.toml` and `minimumReleaseAge` in `frontend/pnpm-workspace.yaml` enforce it at resolution; the pnpm version is pinned in `frontend/package.json`.
12. Map every new AI-facing feature to MITRE ATLAS in `docs/SPEC.md` section 7 before merging.

## 6. Testing expectations

### Required per layer

| Layer | Test type | Minimum |
|---|---|---|
| Envelope parser | Unit, table-driven | 3164 with/without year, with timezone offset, 5424 with structured data, relay-wrapped, headerless, truncated, non-UTF-8, octet-counted |
| Payload parsers | Unit per format | kv with quoted values and escaped quotes, CSV with embedded commas, CEF with escaped pipes, LEEF v1 and v2, JSON with nested root, XML |
| Templates | Fixture-driven | Every template in `templates/starter/` has `tests/fixtures/logs/<template_id>/` containing `sample.log` (min 50 lines, real-shaped, synthetic values), `expected.jsonl` (parsed output for the first 10 lines), and `pathological.log` (long lines, garbage, multiline fragments). A single parametrized test loads all templates and asserts parse rate >= 95% on `sample.log` and no exceptions on `pathological.log`. Each template's inline `tests:` block also runs. |
| Engine guard | Unit | Allowlist accepts `SELECT`, `WITH`; rejects every statement type in SPEC 5.1; rejects `read_csv`, `ATTACH`, nested `COPY` in CTE |
| Gate | Unit | Cloud + local_only in scope raises; local + anything passes; redaction applied only for cloud; every call writes an audit row |
| Citation check | Unit | Valid ids pass, one bad id fails, empty list fails for explain purpose |
| API | Integration (httpx) | Auth enforcement on non-loopback, CSRF on POST, query endpoint respects LIMIT and timeout |
| Ingest end to end | Integration | Write fixture to temp folder, start watcher, append lines, assert events appear in DuckDB with correct `raw` and partition |
| Frontend | Vitest + Testing Library | Table renders raw/parsed toggle, Ask panel does not run SQL without click, command palette opens on Ctrl+K |

### Fixtures

- Synthetic only. No real customer data, no real public IPs beyond RFC 5737 (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`), no real hostnames or usernames.
- Each fixture folder has a `README.md` stating the source product, version, and collector used to shape it.
- Generator scripts in `scripts/fixtures/` are preferred over hand-written files for anything over 50 lines.

### Commands

```
uv run pytest                      # all backend tests
uv run pytest -m templates         # template fixture suite only
pnpm test                          # frontend
make ci                            # lint + type + test both sides, what CI runs
```

CI must be green before a slice is called done.

## 7. Definition of Done per slice

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
- [x] Microsoft 365 connector per ADR-0002: Management Activity API content types and Graph sign-ins, directory audits, alerts; setup guide with exact permissions; templates mapping to OCSF (tested against fake endpoints; live tenant pending)
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

## 8. How to work in a session

1. Read `docs/SPEC.md` sections relevant to the task and the slice's DoD above. For any UI work also read `docs/DESIGN.md`.
2. State the plan in 5 lines or fewer before editing.
3. Write the test first for parsers, guards, and the gate.
4. Keep PRs under ~400 lines of non-fixture diff.
5. If a decision is needed that the spec does not cover, write `docs/adr/ADR-NNNN-slug.md` (context, decision, consequences, ATLAS/ATT&CK impact if AI-facing) and stop for review.
6. No em dashes anywhere in code comments, docs, or UI copy.
7. Do not add features from a later slice. Note them in `docs/BACKLOG.md` instead.
8. Product decisions (name, license, pipeline order, and the like) are recorded in `docs/SPEC.md` section 9. Do not change one in code without a matching row there.
