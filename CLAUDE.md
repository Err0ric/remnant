# CLAUDE.md

Rules for every Claude Code session in this repo. Read fully before writing code.

| Document | Role |
|---|---|
| `docs/SPEC.md` | What we build: architecture, schemas, threat model, roadmap, decisions log |
| `docs/DESIGN.md` | How it looks: tokens, typography, density, component patterns |
| `docs/handoff.md` | Where the last batch stopped: current main, open PRs, pending decisions |
| `docs/history.md` | Completed slice checklists (slices 1 to 8) and background on past rules |
| `CLAUDE.md` (this file) | How we build it: rules, conventions, tests, definition of done |

If this file and `docs/SPEC.md` disagree on a product decision, the spec wins and this file gets fixed in the same PR.

## 1. What this project is

**Remnant** (working codename) is self-hosted AI usage monitoring built on a lightweight, local-first, LLM-assisted SIEM front end (positioning: SPEC D71). License: Apache 2.0. Users point it at log files, YAML templates parse them into OCSF columns in a Parquet lake, DuckDB queries them, Sigma detects on them, and an LLM helps write parsers and queries and explain results. The LLM never reads the whole dataset and never acts without user approval.

## 2. Architecture rules (non-negotiable)

1. **Deterministic core.** Ingest, parse, query, and Sigma work with zero LLM providers configured. Anything needing an LLM lives behind `llm/` and degrades to a manual path.
2. **One gate.** Every provider call goes through `llm/gate.py`. Only `llm/gate.py` and tests import a provider adapter. CI greps for this.
3. **LLM tools.** Ask mode has two (`get_schema`, `preview_query`); explain and parser-draft have none. No new tools without a spec change.
4. **Nothing the LLM returns runs automatically, except an Ask query** that passes the guard and runs read-only on the caller's view (ADR-0042, `ask.auto_run`). SQL is displayed; parser drafts stay in `drafts/` until approved; side effects need approval; free text is never parsed for commands.
5. **Raw line is sacred.** `raw` is stored exactly as decoded, never trimmed or transformed.
6. **Classification is server-side.** Copied from the source at ingest; no API changes it on events.
7. **Locked query engine.** User and LLM SQL runs through the `sqlglot` allowlist in `engine/guard.py`, then DuckDB's own one-SELECT check, on a connection limited to the exact files its views read, with external access off and the configuration locked (ADR-0047, D225). Never bypass the guard, including in "internal" endpoints.
8. **Ingest pipeline of small interfaces**: `Reader -> Framer -> EnvelopeParser -> PayloadParser -> Normalizer -> Writer`. One class, one public method each; none knows another's internals.
9. **Flattened OCSF columns are the schema.** The column list lives only in `core/schema.py`; templates, views, the pySigma pipeline, and the UI registry import it. Migrations are additive; never rename a column.
10. **Thin slices.** Smallest end-to-end thing with tests, then stop. No next-slice features.
11. **Product name is a config constant**: `app.core.branding.PRODUCT_NAME` and `frontend/src/lib/branding.ts` (fed from the API). Never in package, module, service, or folder names.
12. **Plain labels win.** Flavor names (Ask mode = Séance, saved searches = Grimoire, template library = Ossuary) only in command palette aliases, docs, and release notes; never in nav, buttons, API paths, table or column names, errors, or logs.
13. **Access control is server-side and source-based.** Every query surface reads the per-session `events` view from `engine/views.py`. Never take a source list from the client as the scope. Saved searches run with the caller's permissions. Only SQL a person typed or edited goes to the Logs SQL endpoint from the browser; app lists are server-built.
14. **Every action is attributable.** Queries, exports, logins, admin changes, and LLM calls write an audit row with the user id. No shared logins.
15. **The CLI is an API client.** `app/cli/` talks HTTP; it never imports `engine`, `ingest`, or `meta` or opens the lake.

## 3. Repository layout

`backend/app/`: `main.py` (app factory, bind and auth), `api/` (routers only), `auth/`, `cli/`, `core/` (schema, config, errors, ids, branding; imports no siblings), `ingest/`, `templates/`, `engine/` (duckdb, guard, views), `detect/`, `llm/` (gate, providers, redact, audit, prompts), `search/`, `meta/` (sqlite and migrations). Tests in `backend/tests/{unit,integration,fixtures}`. `frontend/src/`: `app/`, `components/`, `features/`, `lib/`, `styles/` (tokens.css from DESIGN.md sections 2 and 11). `templates/starter/` ships YAML templates; `scripts/` holds dev helpers. Runtime data lives in `./data/` (gitignored) or the compose volume.

## 4. Coding conventions

### Python
- 3.12, `uv` for everything. `ruff` format and lint; `mypy --strict` on `app/`; no `# type: ignore` without a reason.
- Pydantic v2 for API bodies, config, and templates; dataclasses for pipeline records.
- Typed exceptions from `core/errors.py`, mapped to HTTP in the API layer; never ad hoc `{"error": ...}`.
- `structlog` JSON. Never log raw event content at INFO or above, provider keys, prompt bodies, or data values.
- Async handlers; DuckDB and file I/O in a thread pool. Absolute imports, no cycles.
- UTC datetimes with tzinfo. `event_id` UUIDv7, other ids UUIDv4.
- One `AppConfig` from `config/app.yaml` plus `APP__SECTION__KEY` env overrides; no other `os.environ` reads.
- Provider keys from env or the settings store, encrypted with `data/.key` (0600); never in YAML, logs, or prompts.

### TypeScript
- React 18, strict TS, Vite, Tailwind, shadcn/ui, TanStack Table and Query, CodeMirror 6, small Zustand stores.
- Function components, named exports, one per file, `interface` props. Server state only via TanStack Query.
- Tokens from `styles/tokens.css`; no arbitrary hex (add a token in DESIGN.md and tokens.css).
- Product name only via `PRODUCT_NAME`. Log data always as text nodes (`dangerouslySetInnerHTML` banned). Mono for log fields, ids, and SQL. Times in the app's local format with UTC on hover; seconds only in log and event tables (DESIGN.md section 3).
- `eslint` and `prettier` enforced in CI.

### Git
- Conventional commits. One PR per vertical feature; no stacked PRs (branch from current `origin/main`); batch small related fixes in one PR. Every PR description lists the Definition of Done items it satisfies.
- Never commit `data/`, `.env`, `*.key`, or the publish denylist.
- **CI minutes are limited: one CI run per PR.** Open every PR as a draft (`-F draft=true`, REST API). Path filters: backend job for `backend/`, `library/`, `templates/`, `scripts/`; frontend job for `frontend/`; docs-only PRs run none. `slow` tests (over 8 s) are skipped in PR CI and run by the queue's local suite (D216; never add `not slow` to the queue). Scale tests run only from the `scale` workflow. `release-checks` runs by hand before a release and whenever an install guide's install or update commands change.
- **Remotes (D207):** `origin` is the private dev repository; `public` is publish-only with push URL `DISABLED`. `main` tracks `origin/main`. Run `sh scripts/dev/session-check.sh` first in every session and after any restart; it restores this layout and installs the pre-push guard. `session-check.sh --verify` changes nothing and fails when the layout is wrong or `origin/main` shares any commit with the public `main`; the queue and `publish.sh` run it themselves and stop on failure. Background: `docs/history.md`.
- **Publishing:** only `scripts/publish/publish.sh`, never through a remote. Fetch the denylist from the Project doc `claude/publish-denylist.md` into a temp file outside the repo and pass `REMNANT_DENYLIST`; the script stops with `NOT PUBLISHED` on a missing denylist, a failed scan, or a failed layout check. After a publish, write `docs/SPEC.md`, `docs/DESIGN.md`, and `CLAUDE.md` (as `docs/CLAUDE.md`) back to the Project when changed.
- **Release notes and decisions** are one file per change (ADR-0044): `docs/release-notes.d/<pr>-<slug>.md` (or `new-<slug>.md`) with a `### Title (date)` heading, bullets, one `- What you will notice: ...` line, and a last `- What changes for existing installs: ...` line; decisions in `docs/decisions.d/D<nnn>-<slug>.md`, one table row. Run `python3 scripts/docs/assemble.py`; never hand-edit the Unreleased section or SPEC section 9 (rows D1 to D208 only for a status change).
- **Merging:** only `scripts/dev/queue.sh <branch> <pr> ...` from the queue worktree. It checks the layout, rebases (a code conflict stops it), runs `assemble.py --prep` (numbers notes and decisions, which may renumber a decision), runs the local suites, and for app changes the speed check and smoke test (section 9), marks the PR ready, waits for the CI run of the exact commit it pushed, and squash-merges. Never push to `main`; never rewrite `main` (GitHub signs the squash commits).

## 5. Security rules

1. All log content is untrusted: escape on render, parameterize SQL, never `eval`, never format into a shell.
2. Prompts put event data under a `data` key in JSON; the system prompt says `data` may contain instructions to ignore. Prompts are versioned files in `llm/prompts/`, referenced by hash in the audit log.
3. Provider responses are untrusted: Pydantic-validated, rejected on failure, capped at 64 KB.
4. Citation check for `explain` and `report`: every cited `event_id` must be in the set sent; otherwise `citation_check=fail` and the UI says "unverified".
5. Template regex uses the `regex` module with a timeout; template tests include a 10 KB garbage line.
6. Source paths resolve under `allowed_roots` with `os.path.realpath`.
7. No users: setup-only mode on every bind, one-time 30-minute setup link (ADR-0001, D245); no insecure mode and no mode without sign-in; HTTPS off loopback.
8. Session cookie HttpOnly, Secure off loopback, SameSite=Strict; CSRF token on every non-GET; login rate-limited.
9. CSP `default-src 'self'`; no inline scripts or CDN assets.
10. The audit table has a `BEFORE DELETE` trigger that raises; no delete endpoint.
11. Lockfiles; base images pinned by digest; no dependency newer than 14 days (`exclude-newer`, `minimumReleaseAge`, pinned pnpm). Dependabot opens security updates only (D224).
12. Map every new AI-facing feature to MITRE ATLAS (and ATT&CK) in SPEC section 7 before merging.

## 6. Testing expectations

| Layer | Minimum |
|---|---|
| Envelope parser | Table-driven: 3164 with and without year, timezone offset, 5424 with structured data, relay-wrapped, headerless, truncated, non-UTF-8, octet-counted |
| Payload parsers | kv with quoted and escaped values, CSV with embedded commas, CEF with escaped pipes, LEEF v1 and v2, nested JSON, XML |
| Templates | Each starter template has `tests/fixtures/logs/<id>/` with `sample.log` (50+ synthetic lines), `expected.jsonl` (first 10), `pathological.log`; parse rate at least 95%, no exceptions; inline `tests:` run |
| Engine guard | Accepts `SELECT`, `WITH`; rejects every statement type in SPEC 5.1, `read_csv`, `ATTACH`, nested `COPY` |
| Gate | Cloud plus `local_only` in scope raises; redaction only for cloud; every call audited |
| Citation check | Valid ids pass; one bad id fails; empty list fails for explain |
| API | Auth off loopback, CSRF on POST, query LIMIT and timeout |
| Ingest | Watcher end to end: events land with correct `raw` and partition |
| Frontend | Raw/parsed toggle; Ask runs only by id (and on click with auto-run off); Ctrl+K palette |

**Fixtures and everything published are synthetic.** Only reserved identifiers: `example.com/.org/.net`, names under `.example`, `.test`, `.invalid`, `.internal`; `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, RFC 1918, `2001:db8::/32`; people alice, bob, carol, dave, erin, frank, grace, heidi, ivan, judy, mallory, ana, dana, jordan, j.doe. Integrated product names are fine; real organizations, people, hosts, evaluated vendors, and named commercial comparisons are not (`scripts/publish/allowlist.py` enforces it). Each fixture folder has a `README.md` (product, version, collector); prefer generators in `scripts/fixtures/` over 50 lines. Never use the real clock with fixed event dates (`app.core.clock`, `pin_now`).

```
uv run pytest -n auto                       # all backend tests
uv run pytest -m "not scale and not slow"   # a PR's CI run (-m replaces the default "not scale")
pnpm test                                   # frontend
make ci                                     # what CI runs
```

## 7. Definition of Done

Slices 1 to 8 are done (checklists in `docs/history.md`). Deferred by the owner and in `docs/BACKLOG.md`: Okta, Google Workspace, and AWS CloudTrail connectors; the object-storage tier. The current slice is Slice 9 (v0.4), per SPEC section 8 (D218) and the ranked `docs/BACKLOG.md`; firewall user-to-IP attribution follows ADR-0048, slice 0 first.

## 8. How to work in a session

1. Run `sh scripts/dev/session-check.sh` first, and again after any restart. Read `docs/handoff.md`, then the SPEC sections the task touches; for UI work, `docs/DESIGN.md`.
2. One agent at a time unless the owner asks for parallel tracks.
3. Start long runs (queue, suites, benchmarks) in the background and wait for completion; no polling or "waiting" messages.
4. Reports: 15 lines at most. Lead with what merged, what failed, and what needs the owner's decision.
5. Write the test first for parsers, guards, and the gate. Keep PRs under about 400 lines of non-fixture diff.
6. A decision the spec does not cover gets `docs/adr/ADR-NNNN-slug.md` (with ATLAS/ATT&CK impact if AI-facing) and stops for review.
7. No em dashes anywhere in code, docs, or UI copy. Later-slice ideas go to `docs/BACKLOG.md`.
8. At the end of a batch, update `docs/handoff.md`; start the next batch in a new session from it.

## 9. Owner rules for every PR (2026-11-08)

Users are internal and not technical: nothing breaks, nothing gets slower, and security changes are invisible to them.

1. **Speed check.** `scripts/bench_compare.py` compares clean exports of `origin/main` and the PR commit on the full-size synthetic lake (about 481,000 events): Dashboard, Logs, Ask library route, People & devices, person page, AI usage, Alerts, and the Identities searches. Put its table in the PR. Flag a page only if it is more than 10% AND at least 100 ms slower, or more than 200 ms slower regardless; a flag counts only when the fastest round or server CPU (10% more) confirms it, after re-timing for twice the rounds. A flagged page needs the owner's OK (`REMNANT_SPEED_OK=<pr>`). Standing rule: if a clean re-time at the maximum rounds comes back within the rule, the override may be applied and listed in the next report; otherwise stop and ask.
2. **Smoke test.** `scripts/smoke.py` opens every route in headless Chromium as Admin, Analyst, and Auditor in parallel and fails on a console error, blank panel, or unexpected 4xx/5xx. Any failure stops the queue.
3. **Plain release notes.** One `- What you will notice:` line: what a user will notice, or "nothing visible" (`assemble.py --check` enforces it).
4. **Rollback.** A change to install data, config, or update steps says in its release note how to go back, pointing to `docs/install/` (`update-systemd.sh --rollback`, D226).
5. **Proportionate security.** Keep fixes that close real exposure; anything else that adds friction for normal users or costs speed goes to the owner as a choice instead of being built.

By hand: `cd backend && uv run python ../scripts/bench_compare.py --before origin/main --after HEAD` (commit first), then `cd frontend && pnpm build` and `cd backend && uv run python ../scripts/smoke.py --lake ../data/bench/lake` (once per machine: `uv run playwright install chromium`).

Large lake, by hand before a release and when a PR touches the Dashboard sections, AI usage, or People & devices: the same table on 30 days at the work install's rate (about 10.7 million events), in its own folder, through `scripts/dev/heavy.sh`: `cd backend && uv run python ../scripts/bench_compare.py --before origin/main --after HEAD --lake ../data/bench/lake-prod30 --real-shape 0.313 --real-days 30`. The queue and `smoke.py` keep the default lake. Every bench lake is kept compacted with its rollups built, as an install runs, and is built again each UTC day.

## 10. Local development workflow

Roles and standing orders for development sessions, when present: @.claude/factory.md
