# PROJECT SPEC: Remnant

Working codename: **Remnant**. May change before first public release. The name lives in one config constant (see `CLAUDE.md` section 2) so a rename is a one-line change.

License: Apache 2.0.

Status: Slice 1 (build). Version 0.3. Last updated 2026-10-10.

### Internal flavor names (optional)

| Feature | Plain label (default) | Flavor name | Where flavor may appear |
|---|---|---|---|
| Ask mode | Ask | Séance | Command palette hint, docs, release notes |
| Saved searches | Saved searches | Grimoire | Same |
| Parser template library | Templates | Ossuary | Same |

Plain labels are the UI default. Flavor names are allowed only where they do not cost clarity: a parenthetical in docs, a palette alias, an easter egg. Nav items, buttons, API paths, and error messages use the plain label.

---

## 1. Problem statement

**Positioning (D71).** Remnant is presented as self-hosted AI usage monitoring: it finds the AI services, agents, and MCP servers people use in logs a team already has, lets the team approve or flag each one, alerts on new or unapproved use and on sensitive data heading to AI, and keeps tamper-evident evidence. The log platform below is the foundation that makes that possible and is useful on its own.

Small security teams and solo practitioners own log data they cannot afford to search well. Commercial SIEMs price by ingest volume, open-source SIEMs demand a full-time engineer to keep running, and both assume you already know how to parse every source you have. The result is logs collected and never read.

Remnant is a lightweight front end you strap onto log files you already have. It gives you:

- A fast, local query engine (DuckDB) over a Parquet lake you control
- A parser system where every log source is a reviewable YAML template mapped to OCSF
- An LLM assistant that writes parsers and queries, explains filtered results, and drafts reports, without ever reading your whole dataset
- Detection via Sigma rules against normalized events
- A hard boundary between local-only data and cloud model providers

### Target users

| User | Situation | What they need |
|---|---|---|
| Solo security lead | One person covering everything at a 50 to 500 employee company | Answers from logs in minutes, not a platform to babysit |
| Small IT/security team | 2 to 10 people, mixed skill, one shared VM | Individual accounts, shared saved searches, parsers someone else can review, per-user audit trail for compliance |
| Homelab / student | Learning detection engineering | Real tooling on real logs without a license |
| MSP or consultant | Drops into a client's log dump | Point at a folder, get queryable events same day |

### Non-users (for now)

- Enterprises needing multi-tenant RBAC, HA, or 24/7 streaming ingest at TB/day
- Teams that need case management, SOAR, or ticketing built in

---

## 2. Goals and non-goals

### Goals (v1)

| # | Goal | Measure |
|---|---|---|
| G1 | Bring your own data | Any text log can be onboarded with a YAML template, no code change |
| G2 | Bring your own model | Any OpenAI-compatible endpoint or Anthropic works through one interface |
| G3 | Local-first | Fresh install only enables local providers; local-only data cannot reach a cloud provider |
| G4 | Deterministic core | Query, parse, and detect without an LLM configured at all |
| G5 | Cited AI | Every AI claim references event IDs that exist in the result set it was given |
| G6 | Fast on a laptop | 50 GB Parquet lake, interactive queries, single container |
| G7 | Auditable | Every LLM call logged with user, provider, model, prompt hash, data classification, and tokens |
| G8 | Team-ready | Deploys as one VM for a security team: individual accounts, roles, per-source access, HTTPS by default. Also runs single-user on a laptop or VM |
| G9 | CLI first-class | Common pulls (tail, query, saved search, ask) work from a terminal with the same guardrails as the web UI |

### Non-goals (v1)

- Native syslog network listener (UDP/TCP/TLS): Slice 7, ADR-0021
- Agent-based endpoint collection
- Case management, SOAR (alert routing moved into Slice 4 by D26; design in ADR-0007)
- SAML SSO and field-level masking (later). Optional OIDC sign-in (Entra ID first) is in v1 per ADR-0013, D39; local accounts stay the default
- Hosted/SaaS mode
- Replacing Elastic, Splunk, Wazuh, or Graylog at scale
- Autonomous LLM actions (the LLM proposes, the user approves)

---

## 3. Architecture overview

### 3.1 Data flow

```
Files / folders (tail, watch)
        |
        v
+-------------------+
| Ingest reader     |  framing (newline, octet-count), encoding repair, multiline join
+-------------------+
        |
        v
+-------------------+
| Envelope parser   |  RFC 3164 | RFC 5424 | none  (syslog header, relay headers)
+-------------------+
        |
        v
+-------------------+
| Payload parser    |  template-selected: regex | kv | csv | cef | leef | json | xml
+-------------------+
        |
        v
+-------------------+
| OCSF normalizer   |  template mapping -> OCSF class fields + unmapped JSON + raw line
+-------------------+
        |
        v
+-------------------+
| Writer            |  buffer -> Parquet (partitioned source/day) -> compaction
+-------------------+
        |
        v
+==================================+
|  DuckDB query engine (read-only) |
+==================================+
     |            |            |
     v            v            v
  Sigma       Query mode    Ask mode
  (pySigma    (SQL editor,  (LLM drafts SQL,
   DuckDB     saved         user sees and
   backend)   searches)     approves)
```

### 3.2 Components

| Component | Tech | Responsibility |
|---|---|---|
| API | Python 3.12, FastAPI, Pydantic v2 | REST + SSE, auth, orchestration |
| Ingest | Python, watchfiles, pyarrow | Read, frame, parse, normalize, write Parquet |
| Lake | Parquet on local disk | Event storage, `source=<id>/day=YYYY-MM-DD/` partitions |
| Engine | DuckDB | All queries, Sigma evaluation, aggregations |
| Metadata DB | SQLite | Users, sources, templates, saved searches, settings, LLM audit log |
| Detect | pySigma + custom DuckDB backend | Sigma rule compile and run. Ships a compatibility field pipeline first (community rule field names mapped to OCSF columns), OCSF-native pipeline second. |
| LLM | Custom thin agent loop | Provider interface, tool calls, classification gate, redaction |
| EVTX (Slice 3) | `evtx` (Rust-backed PyPI package) | Native Windows event log files |
| Web | React 18, TypeScript, Vite, Tailwind, shadcn/ui, TanStack Table + Query, CodeMirror 6 | SOC console UI |
| Auth | Argon2 password hashes, server-side sessions in SQLite | Local accounts, roles, source groups, first-run admin setup |
| CLI | Python (Typer), Textual for the TUI (Slice 6) | Thin client over the HTTP API; never reads the lake directly |
| Install | Docker Compose on a VM (primary), `uv tool install` / `pipx`, systemd unit | One `app` service, optional `ollama` profile. Docker is optional |

Sigma conversion (Slice 4, `detect/sigma_backend.py`, `detect/pipelines/compat.py`): pySigma 1.5 with our own `TextQueryBackend` subclass. A rule's detection becomes a DuckDB WHERE condition on the `events` view; the runner wraps it and the result passes the query guard like any other SQL. Fields resolve to a text expression: a few known fields to their place per transport (`EventID`, including the `#text` of an EVTX EventID that carries Qualifiers, `Channel`, `Provider_Name`, `Computer` to `device_hostname`), every other field to `coalesce()` over `unmapped` at the top level, `winlog.event_data`, and `Event.EventData`, so one compiled rule works on NXLog, Winlogbeat, and native .evtx. Field names outside `[A-Za-z0-9_.-]` refuse the rule. Values are written as SQL literals by the backend (quotes doubled, `%`, `_`, `\` escaped) and matched with `ILIKE ... ESCAPE` (case-insensitive, `|cased` uses `LIKE`); numbers compare as text; `NOT` is `NOT coalesce((...), false)` so a missing field never makes a filter drop an event; regexes use DuckDB's RE2 (linear time) and patterns RE2 cannot compile refuse the rule at conversion; keywords match `raw`.

Rule scope (`detect/logsource.py`, ADR-0006 row 2): templates declare `sigma.logsource`, a list of `{product, service, category}` entries their events can satisfy. A rule applies to a template when one entry has every field the rule names with the same value; the entry may be more specific than the rule. `*` as a declared service or category stands for any value (the Windows templates declare `{product: windows, service: "*"}` and `{product: windows, category: "*"}`, because a Windows forwarder can carry any channel); product is always named. A rule with no product, service, or category runs nowhere. Starter declarations: Linux templates `product: linux` (plus `service: auth` and their own service), firewalls `category: firewall`, DNS templates `category: dns`, generic CEF, LEEF, and JSON templates none.

Rule files (`detect/rules.py`): at most 512 KB (SigmaHQ's largest, the vulnerable drivers list, is about 290 KB), one YAML mapping loaded through `core/safeyaml.py`, no correlation rules or collections, a logsource with at least one of product, service, or category. Windows rules are narrowed the way pySigma's reference Windows and Sysmon pipelines do it, because Sigma leaves the log out of the detection: `service: X` requires X's channel, a Sysmon category requires the Sysmon channel and its event ids (process_creation is Sysmon 1), a PowerShell category its channel and event id. Services and categories with no known channel are refused rather than run loosely. A `process_creation` rule also matches Security 4688 events when every field it uses is one 4688 records (`Image`, `ParentImage`, `CommandLine`, `LogonId`, `Computer`; read as `NewProcessName`, `ParentProcessName`, `CommandLine`, `SubjectLogonId`): 471 of SigmaHQ's 1,182 Windows process creation rules. A rule using any other field (`OriginalFileName`, `Hashes`, `User`, `ParentCommandLine`, process ids) stays Sysmon only, so a filter on a field 4688 lacks can never silently stop filtering. Every compiled rule passes the query guard before it is accepted.

Rule import (`detect/store.py`, `/api/rules`, ADR-0006 rows 1 and 5): an admin imports a file or folder under `paths.rule_roots` (`APP__PATHS__RULE_ROOTS`; Compose mounts `${RULES_DIR:-./rules}` read-only at `/rules`), kept separate from `allowed_roots` so a rule set is never watched as logs. Every `.yml`/`.yaml` file (hidden folders such as `.git` skipped; at most 10,000 files, 200 MB, 16 levels, 10 minutes) is opened with the log-file checks (regular file, still inside the roots when opened) and goes through `compile_rule`. Accepted files are stored in `rule_versions`, keyed by the sha256 of their exact bytes and immutable by trigger; `rules` points each rule id at the version last imported. New rules start disabled; re-importing keeps the enabled state and moves a changed rule to its new version; a second file with the same rule id in one import is refused. Refusals are kept per import with their reason. `POST /api/rules/import` and `POST /api/rules/enabled` are Admin only and audited (`rule.import`, `rule.enable`, `rule.disable`; a path outside the roots is audited as denied); every role can list rules and read a rule's YAML. Importing SigmaHQ `rules/` (3,142 files) takes about a minute and accepts 3,128.

Rule runs (`detect/runner.py`, ADR-0006 rows 2, 5, 6): `POST /api/rules/{id}/run {start, end}` (Admin and Analyst; a disabled rule only by an Admin; range at most 366 days). The sources read are the caller's permitted sources whose template declares a logsource the rule applies to; with none, the run is recorded as `no_data` and reads nothing. The stored YAML of the pinned version is compiled again and both queries (count, then up to 1,000 event ids, earliest first) go through the engine's guard, read-only connection, and a 60 s limit. `rule_runs` records the version (sha256), who, range, status (`ok`, `no_data`, `failed`), count, elapsed time, and the sources read; `rule_matches` the stored event ids with time and source. Rows are never edited (trigger); pruning old runs is allowed. Every run is audited as `rule.run`. A run, and its matches, are shown only to callers who may read every source it read, and match lists are filtered by the caller's sources. Every run carries the rule's title and author for display (DRL 1.1). `GET /api/rules` also lists, per rule, the sources a run would read for the caller, so rules that can only report `no_data` are visible before they are run. The Detection rules page (`features/detect/`) lists rules with level, log source, author ("author not stated" when empty), sources, and state; admins import and enable or disable selected rules; admins and analysts run a rule over the last hour to 30 days; a run shows its title, author, count, sources read, and matches, with Open in Search seeding the Search page with `WHERE event_id IN (...)` (ids checked as UUIDs, at most 500).

Compile rate (SigmaHQ release `r2026-07-01`, counted only when `compile_rule` accepts the rule and its condition executes against the real column set; `scripts/sigma_compile_rate.py`): `rules/linux` 210 of 210, `rules/windows` 2,389 of 2,403 (99.4%; refused: 8 for categories without a Sysmon event, `file_access` and `file_rename`, and 6 for services without a known channel, `iis-configuration`, `ldap`, `smbserver-connectivity`). Compiling is not matching: rules whose fields our templates do not produce (for example Sysmon process fields on Security logs) compile and run but find nothing until the compatibility pipeline maps them.

### 3.3 Storage layout

```
data/
  lake/
    source=linux_auth/day=2026-10-09/part-0001.parquet
    source=paloalto_traffic/day=2026-10-09/part-0001.parquet
  meta.sqlite
  templates/          user-approved templates (YAML)
  sigma/              user rules
config/
  app.yaml
```

### 3.4 Event table schema (Parquet)

Flattened subset of OCSF 1.3 as typed columns, plus escape hatches. Every event has all columns; unused ones are NULL.

| Column | Type | Notes |
|---|---|---|
| `event_id` | UUID string | Generated at ingest. The citation key. |
| `source_id` | string | Matches `sources` table |
| `template_id` | string | Template that parsed it |
| `template_version` | string | |
| `time` | TIMESTAMPTZ | OCSF `time`, UTC |
| `time_observed` | TIMESTAMPTZ | When ingested |
| `class_uid` | int | OCSF class |
| `category_uid` | int | |
| `activity_id` | int | |
| `severity_id` | int | 0 unknown .. 6 fatal |
| `status_id` | int | |
| `message` | string | OCSF message |
| `actor_user_name`, `actor_process_name`, `actor_process_pid` | string/int | Flattened `actor.*` |
| `src_endpoint_ip`, `src_endpoint_port`, `src_endpoint_hostname` | string/int/string | |
| `dst_endpoint_ip`, `dst_endpoint_port`, `dst_endpoint_hostname` | | |
| `device_hostname`, `device_ip` | string | The reporting device |
| `unmapped` | JSON (string) | Parsed fields with no OCSF target |
| `envelope` | JSON (string) | `{rfc, facility, severity, hostname, app_name, procid, msgid, relay_hops}` |
| `raw` | string | Original line, bytes decoded with replacement, never modified |
| `raw_bytes_invalid` | bool | True if non-UTF-8 bytes were replaced |
| `parse_status` | string | `ok`, `partial`, `envelope_only`, `failed` |
| `parse_errors` | string | Short reason when not `ok` |
| `classification` | string | `local_only` or `cloud_allowed`, copied from source at ingest |
| `owner_id` | string | Multi-user ready, v1 constant |

Tradeoff flagged: flattening OCSF loses nested structure fidelity but makes DuckDB queries, Sigma field mapping, and the UI table trivially fast. `unmapped` keeps everything. Full OCSF JSON export can be reconstructed from columns + `unmapped` if ever needed.

### 3.5 Ingest internals

| Concern | Decision |
|---|---|
| Interface | `Reader -> Framer -> Parser -> Normalizer -> Writer`, each a class with one method. Background workers can slot in behind `Writer` later without touching parsers. |
| Framing | Newline default. Octet-counted (`<len> <msg>`) auto-detected per file when first bytes match `^\d+ <`. |
| Multiline | Template-declared `multiline.start` regex. Lines not matching start are appended to the previous event. Hard cap 64 KB per event. |
| Truncated UDP | Lines over the source's `max_len` or ending mid-token are marked `parse_status=partial`, never dropped. |
| Encoding | Decode UTF-8 with `errors="replace"`, set `raw_bytes_invalid`. Templates can declare `encoding: latin-1`. |
| Relay headers | Envelope parser loops: if the MSG part itself begins with a valid syslog header, strip and count as `relay_hops`. Cap 3. |
| RFC 3164 year | Per source: `assume_year: current` or `rollover_safe` (if parsed date is more than 7 days in the future, subtract a year). |
| RFC 3164 timezone | Per source `timezone: UTC` default. Override to IANA zone. |
| Buffering | Flush at 50k events or 5 seconds, whichever first. |
| Compaction | Hourly job merges files under 32 MB within a partition into one file. Target 128 MB files. |
| Retention | Per source `retention_days`. Nightly job deletes whole day partitions. |
| Idempotency | File offset checkpoint in `meta.sqlite` per (source, path, inode). Rotation detected by inode change. |
| Read errors | A file that cannot be read is skipped for that pass and the source shows `Cannot read N of M files (name: reason)`; its other files are still read. A file gone since it was listed (rotation) is not an error. EVTX records the chunk headers list but that cannot be read are logged and shown on the Sources page, counted from the latest read of each file (not a running total, so a record looked for again is not counted twice); a chunk header whose id range is wider than a chunk can hold is ignored and counted as unreadable. An .evtx shorter than its header says is shown as waiting and read as it is once its size has not changed for 10 minutes. Ids after the checkpoint that no chunk header lists, between two chunks (a chunk Windows was still writing when the file was copied), hold the checkpoint just before them, so they are read once the header catches up; if the same gap is still there after 10 minutes it is passed and counted as unreadable. Any other error in one file is reported for that file and never stops the pass. |
| Generic message | The generic JSON and CSV parsers take `message` from a `message`, `Message`, `msg`, or `MSG` field; a row without one gets a `key=value` summary of its top-level values (time fields, empty and nested values left out, at most 300 characters). Every field stays in `unmapped`; `raw` is untouched. |
| Hostile names and swaps | A file name that is not valid UTF-8 is checkpointed by its bytes (`fsbytes:<hex>`) and shown with U+FFFD; discovery and draft samples skip such names and count them. Every open checks where the descriptor really points (`/proc/self/fd`) against the allowed roots, so a parent folder swapped for a link after the path was checked is refused. |
| EVTX budget | Per pass: 5,000 records, 256 chunks, and 32 MiB of rendered JSON; the highest ids wait for the next pass. |

### 3.6 Deployment and access model

**Deployment modes.** One codebase, two common shapes:

| Mode | Typical setup | Access |
|---|---|---|
| Team VM (primary) | Linux VM next to the log collector, Docker Compose or systemd, analysts connect from their browsers and terminals | HTTPS, individual accounts, roles, source groups |
| Single user | Laptop, homelab, or a personal VM | Same accounts model with one admin account. On a loopback bind with no users created, the app runs without login (local-only convenience) |

Docker is optional everywhere.

**First run.** When the app starts on a non-loopback address with no users, it enters setup-only mode: every route except setup is closed, and the log prints a one-time setup URL (random token, single use, 30 minute expiry, stored hashed). The setup page states clearly: *"You are creating the administrator account for this installation."* After the admin account exists the link is dead and normal login applies. There is no insecure-mode flag.

**Roles (v1).**

| Role | Can |
|---|---|
| Admin | Manage users, roles, source groups, sources, LLM providers, classification, retention. Everything an Analyst can |
| Analyst | Query, Ask, saved searches (private and shared), explain, run Sigma rules, view permitted sources |
| Auditor | Read-only: view permitted sources, run saved searches, view the audit log. No Ask, no provider calls, no edits |

**Per-source access (source groups).** The source is the separation boundary, because the lake is already partitioned by source.

- Groups are **not hardcoded**. Each installation builds its own, helped by discovery and auto-labeling (below). Admins can create, rename, merge, or delete any group
- Admins grant groups to users; nothing is granted automatically
- The engine builds each session's `events` view from the permitted sources only. Enforcement is server-side, in `engine/views.py`; the UI, CLI, Ask mode, Sigma runs, and the LLM gate all use that view
- Saved searches run with the permissions of the user running them, not the author
- Field-level masking is out of scope for v1

**Source discovery and auto-labeling (Slice 3).** Suggestions only; an admin approves every one.

| Step | How | LLM needed? |
|---|---|---|
| Discover | Admin points at a folder (for example a collector's `/var/log/remote/`). The engine walks it, groups files by host and naming pattern, samples each, and runs the deterministic envelope and format sniff (4.5) | No |
| Match | Each candidate is matched against templates by `app_name` and regex confidence. Unmatched candidates go to the parser draft flow | No (drafting a new template can use a local LLM) |
| Label | Each template declares a `category` derived from its OCSF class: `identity` (3xxx), `network` (4001, 4002), `dns` (4003), `system` (1xxx), `application` (6xxx), `findings` (2xxx). Vendor tags come from the template (`paloalto`, `windows`, `linux`) | No |
| Suggest groups | Proposed groups = categories that have at least one source, plus vendor groups on request. Shown as a checklist: create group, add sources | No |
| Flag sensitive | Optional hint: sources whose sampled values look like HR, payroll, or health systems (by template or hostname patterns) are suggested as `restricted`. Never auto-applied | Optional, local model only |

Guardrails: discovery never grants access, never changes classification away from `local_only`, and every accepted suggestion is audited.

Suggested groups (Slice 3): templates declare `category` (one of the six above, validated; empty for generic templates) and an optional `vendor`. `GET /api/groups/suggestions` (Admin) lists one suggestion per category and per vendor that has a configured source, with the sources not yet in a group of that name; listing changes nothing. `POST /api/groups/suggestions/accept {kind, key, source_ids}` re-derives the suggestion on the server, refuses any source outside it, creates the group if needed, and adds only the ticked sources: it never removes a source and never adds a person, so it grants no access by itself. Audited as `group.suggestion_accept` plus the usual group rows. The Users page shows it as a checklist, one button per suggestion.

Implementation (Slice 3): `POST /api/sources/discover {path}` (Admin, audited as `source.discover` with success, failure, or denied) walks a folder under `allowed_roots`, checking every file's real path against the roots, within limits: 5,000 files, 50,000 directory entries, 4 folder levels, 200 candidates, 60 seconds. Hidden entries, compressed files, and rotated copies of a live file (`auth.log.1`, `auth.log-20261008`) are skipped and counted, because the watcher follows the live file across rotation. Files are grouped by the path the source will see (a symlink by its own name): the deepest non-date folder above each file is its host, so a collector's per-host folders become one candidate (`*/sshd.log`, or `syslog/*/sshd.log` when a parent folder is scanned) listing the hosts, folders above the host stay literal, a lone folder cannot be told from a category and is listed as a host, date folders and dates in names become `*`, and glob characters in real names are escaped. Each suggested glob is checked against the folder; any extra files it would reach are reported so the admin narrows it first. Each candidate is sampled (at most 200 lines and 512 KiB from up to 3 files on different hosts; `.evtx` through the EVTX reader), sniffed, and matched (`templates/matcher.py`): templates whose `match` block accepts at least 20% of the sample are run over it and ranked by their own `min_confidence`, then parse rate, then OCSF columns filled per line, so a vendor template outranks a generic one that also parses. Files are opened non-blocking and must be regular files on the open descriptor (ingest uses the same rule), so a FIFO or device swapped in cannot stall a thread. One scan runs at a time. The admin adds the source through the normal form.

**Accountability.** Every query, saved search run, export, login, admin change, and LLM call is recorded with the user id in an append-only audit log (extends 6.4). Shared accounts are discouraged in the docs and there is no shared-login feature.

**HTTPS.** On by default for non-loopback binds. First start generates a self-signed certificate in `data/tls/`; admins can supply their own cert and key or run behind a reverse proxy (documented). HTTP is allowed only on loopback.

### 3.7 Connectors (Slice 7)

A connector pulls events from an API on a schedule and feeds the same pipeline as files: raw JSON line, generic or template parse, OCSF columns, Parquet.

| Concern | Decision |
|---|---|
| Shape | `ingest/connectors/<name>.py` with a `Connector` protocol: `pull(checkpoint, now) -> Pull`. Runs in the ingest worker, never in request handlers |
| Credentials | Stored in the settings store, encrypted with `data/.key`. Certificate auth preferred over secrets where the provider supports it. Never logged, never sent to an LLM |
| Permissions | Read-only, least privilege, documented per connector with the exact consent screen the admin will see |
| Checkpoints | Per connector and content type in `meta.sqlite`; replay-safe with de-duplication on the provider's event id |
| Raw retention | The provider's JSON is stored unmodified in `raw`, so templates can be improved and re-run later |
| Throttling | Honors provider rate limits and `Retry-After`; backoff with jitter; health shown on the Sources page |
| Classification | Connector sources default to `local_only` like any source |

Microsoft 365 was planned first (ADR-0002). Grafana Loki landed earlier, ahead of this slice (ADR-0011, D37), so a team can try the product on logs it already collects.

**API connector framework** (`ingest/connectors/base.py`, `registry.py`): a `Connector` has `poll_every` and `pull(checkpoint, now) -> Pull(records, checkpoint, behind_s, warnings)`. A record is one line for the parser (the provider's JSON, compact) and a fallback time. The ingest worker polls each `m365` or `anthropic` source no more often than `poll_every`, writes the records through the source's parser, and only then saves the checkpoint in `connector_checkpoints`, so a crash repeats a pull and never loses one. A feed that fails while others work is a warning on the Sources page; when every feed fails, or the provider answers 429 or 503, the source shows the error and waits: the provider's `Retry-After`, else the poll interval doubled per failure up to an hour. Requests go through `Https`: https only, to the connector's host allowlist, address checked with the webhook rules and pinned (a public service resolving to a private address is refused), no redirects, no proxy, 32 MB per reply. Credentials are write-only (`credentials` on create, `PUT /api/sources/{id}/credentials` to replace), encrypted with the install key, and never in audit details. `POST /api/sources/api/test` (admin, audited `source.api_test`) reads one small page per enabled feed before saving and returns each feed's result and, for a certificate, the thumbprint Entra shows. Non-admins see neither the settings nor feed warnings.

**Microsoft 365** (`connectors/m365.py`, source `kind: m365`, ADR-0002): settings are tenant and client id, cloud (commercial, GCC, GCC High), auth (certificate with a PS256 client assertion, or client secret), Management Activity content types, Graph feeds (`signins`, `directory_audits`, `alerts`), and `backfill_hours` (at most 168). Subscriptions start once; content is listed in windows of at most 24 hours no more than 7 days back, at most 100 blobs a poll, with the content ids at the resume instant kept so none is read twice. Graph feeds are read in time windows ending 20 minutes before now. The source uses the Automatic parser: `m365_management_activity` (6003, including Copilot interactions and DLP rule matches), `m365_signin` (3002), `m365_directory_audit` (3004 Entity Management, since directory audits cover groups, apps, roles, and policies, not only accounts), `m365_alert` (2004).

**Anthropic** (`connectors/anthropic.py`, source `kind: anthropic`, ADR-0015 row 10): an Admin, Analytics, or Compliance key; feeds `usage` (hourly buckets, finished hours only), `cost` (daily, finished days), `claude_code` (per user per day, read 2 h after the day ends), `analytics_users` (claude.ai per user, read from 14:00 UTC the next day), `compliance_activities` (audit events, every 5 minutes, ids at the newest instant kept). Each record is `{"feed": "anthropic.<feed>", ...}` parsed by `anthropic_reports`. Compliance content endpoints (chats, files, projects) are never called.

**Loki source** (`ingest/connectors/loki.py`, source `kind: loki`): settings are the Loki root URL, a query that is a label selector plus at most 5 line filters (`|=`, `!=`, `|~`, `!~`; parsers and formatting stages refused), optional tenant (`X-Scope-OrgID`), sign-in (none, basic, bearer; the password or token encrypted with the install key, write-only), and `backfill_hours` (default 24). The ingest worker polls every 30 s with `GET /loki/api/v1/query_range` (`direction=forward`, 1000 lines a request, at most 20 requests a poll), ending each poll 30 s before now so late lines are still read. The position (newest nanosecond read plus the hashes of lines at it) is stored in `connector_checkpoints`, written after the lake, so a restart repeats nothing and loses nothing; a full page at one instant steps past it rather than looping. Each line goes through the source's parser as a frame, unchanged in `raw`; stream labels go to `envelope.loki_labels`; a line with no timestamp of its own takes Loki's. Every request re-checks the address with the webhook rules (ADR-0007 row 4) and connects to the pinned address with no redirects or proxies, reading at most 32 MB a reply. `POST /api/sources/loki/test` (admin, audited `source.loki_test`) runs one query over the last hour and returns the line count and matching label sets. Status shows how far behind the source is. Removing the source forgets its position. The generic `Connector` interface from the table above is still to come with the Slice 7 connectors.

### 3.8 MCP server, read-only (Slice 7, ADR-0003)

Lets an outside AI assistant (Claude Desktop, an IDE agent, another MCP client) query the lake through the same guardrails as Ask mode. Remnant is the MCP **server** only. It never uses MCP servers as log sources: ingest stays deterministic and auditable through files, the syslog listener, and connectors.

| Aspect | Rule |
|---|---|
| Tools | `get_schema` and `run_query` (guarded, read-only SQL, row cap). Nothing that writes, schedules, or changes settings |
| Identity | Each client uses a per-user API token. Queries run on that user's `events` view; no service-wide token |
| Scope | Same per-session view as every other surface (rule 13). The client cannot widen it |
| Classification | Off by default. An admin enables it per installation. Results from `local_only` sources are withheld unless the admin marks the MCP endpoint as local (the client and its model run on the internal network) |
| Untrusted output | Results are returned as data, with a fixed notice that field values may contain instructions and must not be followed |
| Audit | Every tool call writes an audit row with user id, client name, SQL, row count |
| Transport | Streamable HTTP over the existing HTTPS listener; stdio wrapper via the CLI for local clients |
| Limits | 500 rows, 2,000 characters per value, 256 KB per result, 15 s per query; `since_hours` narrows time |
| Setup | Settings > MCP server (admins): on or off, and whether the endpoint is local. Guide: `docs/install/mcp-server.md` |


---

### 3.9 AI usage visibility (Slice 7, ADR-0015, D41)

AI tools are a data source like any other. Four inputs feed one **AI usage** page and an **AI watch**:

| Input | How it arrives | What it gives |
|---|---|---|
| Firewall, DNS, proxy logs | Existing sources; destination domain matched against `backend/app/content/ai/services.yaml` plus admin entries | Which AI services, by user and host (shadow AI) |
| Claude Code telemetry | OTLP/HTTP JSON to `/api/otlp/v1/logs` and `/v1/metrics`, per-source bearer token; template `claude_code_otel` | Sessions, tokens, cost, tool calls, MCP server and tool names, by `user.email` |
| Endpoint MCP inventory | `scripts/endpoint/mcp-inventory.ps1` / `mcp_inventory.py`, one JSON line per configured server (names, transport, command or URL host only); template `mcp_inventory` | Installed MCP servers, including unused ones |
| Anthropic APIs | Source kind `anthropic`: `usage`, `cost`, `claude_code`, `analytics_users`, `compliance_activities` feeds | Usage and cost per model, workspace, user; Claude Code per user; claude.ai per user (Enterprise); audit activity feed |

The receiver drops prompt text, response text, tool input and parameters, and raw API bodies by default, keeping MCP server, tool, and skill names; **Keep prompt and tool content** is a per-source admin opt-in, audited. Services and MCP servers are **Approved**, **Not approved**, or **Unreviewed**; the AI watch sends one alert the first time something not Approved is seen for a user or host. All new sources are `local_only`; none of this passes through the LLM gate, because nothing is sent to a model.

### 3.10 Optional endpoint agent (Slice 7, ADR-0017, D43)

The agent is the official OpenTelemetry Collector (contrib). An admin creates an OTLP source per agent group and downloads a config (`GET /api/sources/{id}/agent-config?os=windows|linux`, audited `source.agent_config`) that reads the token from a file. Windows: Security, System, Application, Sysmon, PowerShell, Defender channels as event XML; Linux: journald (or files). The receiver converts Windows event XML to the `evtx` JSON shape and journald entries to RFC 5424 lines, so `windows_evtx` and the Linux templates parse them; file lines are spooled as written. Health is the source's received time and quiet-source alert.

---

## 4. Parser template format

Templates are YAML, schema version 1. One template per source type. Templates ship in `templates/starter/`, user templates live in `data/templates/`. The LLM drafts into `data/templates/drafts/` and nothing in drafts is used until approved.

### 4.1 Schema

```yaml
schema_version: 1
id: string                 # snake_case, unique
name: string
version: semver
author: string
description: string
classification_default: local_only | cloud_allowed   # applied to sources created from this template

envelope:
  type: syslog | none
  syslog:                  # only when type: syslog
    rfc: auto | 3164 | 5424
    assume_year: current | rollover_safe
    timezone: UTC          # IANA name, used only for 3164
    strip_relay_headers: true
  optional: false          # true: lines without a syslog header are not flagged
  defaults: [time, device_hostname, actor_process_name, actor_process_pid, message]
                           # columns the header fills when the mapping leaves them empty

match:                     # how auto-detect picks this template for a sample
  app_name: [string]       # syslog APP-NAME / TAG values
  regex: string            # optional, tested against payload
  min_confidence: 0.8

framing:
  mode: lines              # lines | evtx (Windows .evtx, one frame per record)
  multiline:
    start: regex           # optional
  max_len: 8192

payload:
  format: regex | kv | csv | cef | leef | json | xml | plain
  encoding: utf-8
  # format-specific blocks:
  regex:
    patterns:              # first match wins, named groups become fields
      - string
  kv:
    pair_sep: " "
    kv_sep: "="
    quote: '"'
  csv:
    delimiter: ","
    columns: [string]      # positional names
    quote: '"'
  json:
    root: "$"              # JSONPath to the object
  cef: {}                  # standard, extensions become fields
  leef: {}
  xml:
    fields: { name: xpath }

transforms:                # applied after payload parse, in order
  - field: string
    op: to_int | to_lower | to_upper | strip | split | regex_extract | map | timestamp
        | join | replace | pick | find
    args: {}               # timestamp format may be a list, tried in order;
                           # join: { with: [fields], into, sep }; replace: { pattern, with };
                           # pick: { from: { value: field }, into } copies the named field;
                           # find: { key, equals, value, into } reads one entry of a list of
                           #   name/value objects (Graph modifiedProperties, additionalDetails);
                           # map and regex_extract take optional: true (no match, no change)

mapping:
  class_uid: int           # default OCSF class
  class_by:                # optional override by field value
    field: string
    values: { "value": class_uid }
  lookup:                  # optional shared table in templates/starter/maps/
    field: string          # key field, e.g. "Security:4624"
    table: string
    actor: { subject: [string], target: [string] }   # optional, see 4.4
  fields:
    <ocsf_column>:
      from: string | [string]   # parsed field, envelope.<x>, or a list: first with a value
      map: { }             # optional value map
      default: any
  severity:
    from: string
    map: { }

tests:                     # required, minimum 3
  - name: string
    input: string          # one full raw line
    expect:
      parse_status: ok
      class_uid: int
      fields: { column: value }
```

Validation rules enforced at load:

- `id` unique across starter + user templates
- Every `mapping.fields` key must be a known column from 3.4
- At least 3 `tests`, all must pass before a template can be approved
- `regex.patterns` compiled with a timeout guard (no catastrophic backtracking in tests)

### 4.2 Example: syslog source (Linux sshd)

```yaml
schema_version: 1
id: linux_sshd
name: Linux sshd authentication
version: 1.0.0
author: starter-pack
description: OpenSSH auth events via syslog (RFC 3164 or 5424)
classification_default: local_only

envelope:
  type: syslog
  syslog:
    rfc: auto
    assume_year: rollover_safe
    timezone: UTC
    strip_relay_headers: true

match:
  app_name: [sshd]
  min_confidence: 0.9

framing:
  max_len: 4096

payload:
  format: regex
  regex:
    patterns:
      - '^(?P<outcome>Accepted|Failed) (?P<method>\S+) for (?:invalid user )?(?P<user>\S+) from (?P<src_ip>[\da-fA-F:.]+) port (?P<src_port>\d+)'
      - '^Invalid user (?P<user>\S+) from (?P<src_ip>[\da-fA-F:.]+) port (?P<src_port>\d+)'
      - '^Disconnected from (?:authenticating |invalid )?user (?P<user>\S+) (?P<src_ip>[\da-fA-F:.]+) port (?P<src_port>\d+)'

transforms:
  - field: src_port
    op: to_int

mapping:
  class_uid: 3002          # Authentication
  fields:
    time:            { from: envelope.timestamp }
    device_hostname: { from: envelope.hostname }
    actor_process_name: { from: envelope.app_name }
    actor_process_pid:  { from: envelope.procid }
    actor_user_name: { from: user }
    src_endpoint_ip: { from: src_ip }
    src_endpoint_port: { from: src_port }
    activity_id:     { from: outcome, map: { Accepted: 1, Failed: 1 }, default: 99 }
    status_id:       { from: outcome, map: { Accepted: 1, Failed: 2 }, default: 0 }
    message:         { from: envelope.msg }
  severity:
    from: outcome
    map: { Accepted: 1, Failed: 3 }

tests:
  - name: accepted publickey 3164
    input: "Oct  9 20:41:12 bastion sshd[2231]: Accepted publickey for jordan from 10.20.1.5 port 51234 ssh2"
    expect:
      parse_status: ok
      class_uid: 3002
      fields: { actor_user_name: jordan, src_endpoint_ip: 10.20.1.5, src_endpoint_port: 51234, status_id: 1 }
  - name: failed password invalid user
    input: "Oct  9 20:41:15 bastion sshd[2240]: Failed password for invalid user admin from 203.0.113.9 port 40022 ssh2"
    expect:
      parse_status: ok
      fields: { actor_user_name: admin, src_endpoint_ip: 203.0.113.9, status_id: 2 }
  - name: 5424 envelope
    input: "<86>1 2026-10-09T20:41:12Z bastion sshd 2231 - - Accepted publickey for jordan from 10.20.1.5 port 51234 ssh2"
    expect:
      parse_status: ok
      fields: { device_hostname: bastion, actor_user_name: jordan }
```

### 4.3 Example: non-syslog source (nginx access log)

```yaml
schema_version: 1
id: nginx_access_combined
name: nginx access log (combined format)
version: 1.0.0
author: starter-pack
description: Plain file, combined log format, no syslog envelope
classification_default: cloud_allowed

envelope:
  type: none

match:
  regex: '^\S+ \S+ \S+ \[[^\]]+\] "[A-Z]+ '
  min_confidence: 0.8

payload:
  format: regex
  regex:
    patterns:
      - '^(?P<src_ip>\S+) \S+ (?P<user>\S+) \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+) (?P<proto>[^"]+)" (?P<status>\d{3}) (?P<bytes>\d+|-) "(?P<referer>[^"]*)" "(?P<ua>[^"]*)"'

transforms:
  - field: ts
    op: timestamp
    args: { format: "%d/%b/%Y:%H:%M:%S %z" }
  - field: status
    op: to_int
  - field: bytes
    op: to_int

mapping:
  class_uid: 4002          # HTTP Activity
  fields:
    time:            { from: ts }
    src_endpoint_ip: { from: src_ip }
    actor_user_name: { from: user }
    status_id:       { from: status, map: { "200": 1, "301": 1, "302": 1, "403": 2, "404": 2, "500": 2 }, default: 0 }
    message:         { from: path }
  severity:
    from: status
    map: { "500": 3, "403": 2 }

tests:
  - name: 200 GET
    input: '10.0.0.5 - - [09/Oct/2026:20:41:12 -0700] "GET /login HTTP/1.1" 200 512 "-" "Mozilla/5.0"'
    expect: { parse_status: ok, class_uid: 4002, fields: { src_endpoint_ip: 10.0.0.5, status_id: 1 } }
  - name: 403 POST
    input: '203.0.113.9 - - [09/Oct/2026:20:41:15 -0700] "POST /admin HTTP/1.1" 403 128 "-" "curl/8.0"'
    expect: { parse_status: ok, fields: { status_id: 2 } }
  - name: dash bytes
    input: '10.0.0.5 - jordan [09/Oct/2026:20:41:20 -0700] "HEAD /health HTTP/1.1" 200 - "-" "probe"'
    expect: { parse_status: ok, fields: { actor_user_name: jordan } }
```

### 4.4 Starter template pack (Slice 3)

| Template id | Envelope | Payload | OCSF class |
|---|---|---|---|
| `linux_sshd` | syslog | regex | 3002 Authentication |
| `linux_sudo` | syslog | regex | 3002 / 1007 |
| `linux_pam` | syslog | regex | 3002 |
| `linux_systemd` | syslog | regex | 1007 Process, manager messages 0 |
| `paloalto_traffic` | syslog | csv positional | 4001 Network Activity |
| `paloalto_threat` | syslog | csv | 4001 + severity |
| `paloalto_system` | syslog | csv | 3002 for admin auth-success / auth-fail, else 0 Base Event |
| `paloalto_globalprotect` | syslog | csv | 3002 |
| `paloalto_userid` | syslog | csv | 3002 logon / logoff for login / logout mappings, else 0 |
| `fortinet_fortigate` | syslog | kv | 4001 / 3002 by `subtype` |
| `unifi` | syslog | kv + regex | 4001 / 3002 |
| `cisco_asa` | syslog | regex per `%ASA-n-xxxxxx` id | 4001 / 3002 |
| `cisco_ios` | syslog | regex per `%FACILITY-n-MNEMONIC` | 3002 logins, 4001 ACL log, else 0 |
| `cef_generic` | syslog | cef | 0 until a vendor copy adds `class_by` on `signature_id` |
| `leef_generic` | syslog | leef | 0 until a vendor copy adds `class_by` on `event_id` |
| `json_over_syslog` | syslog | json | 0 (the application defines meaning) |
| `windows_nxlog_json` | syslog or none | json | by event id map (4624 -> 3002, 4688 -> 1007, etc.) |
| `windows_snare` | syslog or none | regex over the tab-delimited record (user and addresses are inside the expanded message) | same map |
| `windows_winlogbeat` | none | json | same map |
| `windows_evtx` | none | json over records read natively (`framing.mode: evtx`) | same map |
| `dns_bind` | syslog or none | regex | 4003 DNS Activity |
| `dns_unbound` | syslog or none | regex | 4003 |
| `dns_windows` | none | regex (debug log) | 4003 |
| `dns_powerdns` | syslog | regex (Authoritative and Recursor text and structured forms) | 4003 |
| `authelia` | syslog | regex over logrus text or JSON | 3002 attempts, 3003 access denied, else 0 |
| `tacacs_tac_plus` | syslog | regex (queries and tab-separated accounting) | 3002, 1007 command records, else 0 |
| `vault_audit` | syslog or none | json | 6003 API Activity |
| `vault_server` | syslog | regex | 0, severity from level |
| `openvpn_server` | syslog | regex (Access Server wrapper optional) | 3002 |
| `openldap_slapd` | syslog | regex per stats line | 3002 binds, 4001 connections, else 0 |

The last seven (2026-10-22, from trial lines that still parsed as generic) are built from vendor documentation and marked so in their descriptions and fixture READMEs: verify on real data.

All Windows templates share one lookup table, `templates/starter/maps/windows_eventid.yaml`, keyed `<channel>:<event id>`, so Sigma `logsource: product: windows` rules match regardless of transport. The table sets class, activity, and (where the event id decides it) status, plus which user is the actor: logon events take the Target* user, every other event the Subject* user, with no fallback between them; the other user field stays in `unmapped`. Status otherwise comes from the audit keyword (success or failure) and is left unset for non-audit events. Filtering platform events (5156, 5157) name the local side Source* in both directions, so templates pick the initiator by `Direction` (`%%14592` Inbound, `%%14593` Outbound). Sysmon events are not in the map until their field names are mapped. Templates reference it with `mapping.lookup` (`field`, `table`, optional `actor` refs); table values only fill columns the template left unset, and a `class_by` match still wins. Templates may limit which columns the syslog header fills with `envelope.defaults`, because Windows forwarders put the event provider in the tag.

Native `.evtx` files are read by `ingest/evtx.py` with the `evtx` library (Rust). Each record is rendered to compact JSON by the library and that JSON is the frame, so it is the event's `raw` (the binary file stays the original). Records are read in record-id order after the checkpoint's last id. Chunk headers give each chunk's id range, so only chunks holding newer ids are parsed, at most 5,000 records and 256 chunks per pass. A file whose signature (size, file header, and every chunk header, so new or replaced records always change it; mtime is not used) matches the one saved after a complete read is not re-parsed, and a file shorter than its header declares is a copy in progress and waits for a later pass. Files are identified by content, not inode (copy tools replace files): the record at the checkpoint id is re-read, and if its digest differs (another host's log, or a cleared log reusing ids) or every id is below the checkpoint, the file is read from the start. A native parser panic ends that file's batch, never the ingest loop. Records the library cannot render are counted, logged, and skipped. EVTX stores no rendered message, so `message` is the map's label when the event id is in it.

### 4.4.1 Automatic parser (ADR-0012, D38)

A source's parser is a template id, the generic parser for its format, or **Automatic** (`template_id: auto`, syslog and JSON sources only; no template may use the id `auto`). Automatic picks one template per line, deterministically and with no model (`templates/router.py`):

1. The syslog header is parsed with the source's settings. Templates whose `match.app_name` lists the line's APP-NAME/TAG are candidates; the first (by id) whose `match.regex` is absent or matches the payload wins.
2. Otherwise templates with a `match.regex` and no `app_name` are tried against the payload (the whole line for `envelope.type: none`): approved user templates first, then starter templates with a `vendor`, then catch-alls with none (`cef_generic`, `leef_generic`, `json_over_syslog`). Each search has the template regex timeout; a timeout counts as no match.
3. Otherwise the line takes the generic parser for the source's format.

Only approved templates are considered, never drafts, and never templates with multiline framing (routing is per line). Each row's `template_id` records which parser read it (`generic_syslog` for the fallback). A routed template that understands nothing of the payload (`parse_status` `failed` or `envelope_only`) is replaced by the generic parser for that line, with `auto_fallback:<template_id>` added to `parse_errors`, so time, host, and message are still filled. The registry is read when each pass starts, so a newly approved template is used from the next pass. Sigma treats an Automatic source as declaring every routable template's logsources, and a rule run adds `template_id IN (...)` for that source's rows, so a rule only reads rows parsed by a template that declares its logsource (never generic rows).

New drafts (blank skeleton or model-drafted) get a `match.app_name` naming the sample's syslog tag when at least 80% of sample lines share it (`templates/matcher.match_block`, no model), so an approved draft is routed to by Automatic sources; a model draft keeps a match block the admin already set. Admins change a source's parser with `PATCH /api/sources/{id}` (`template_id`, audited as `source.parser_change` with old and new values). Reading continues from the source's current position, so only lines read after the change use the new parser; stored events keep theirs. Re-parsing stored events is in `docs/BACKLOG.md`. New syslog and JSON sources default to Automatic in the Add source form.

### 4.5 LLM-generated parser flow (Slice 3)

1. User uploads or points at a sample file. Engine reads up to 200 lines.
2. Deterministic envelope detection runs first: RFC 5424 regex, then RFC 3164 regex, then none. Reports confidence and detected `app_name` values. No LLM involved.
3. Deterministic payload format sniff: JSON, CEF, LEEF, kv, csv, or plain. Reports confidence.
4. If a starter template matches with confidence >= `min_confidence`, offer it. Stop.
5. Otherwise the LLM receives: envelope result, format sniff, 20 payload samples (post-envelope strip, redaction applied if source is `cloud_allowed` and redaction enabled), the schema from 4.1, and the OCSF column list. It must return only the `payload`, `transforms`, `mapping`, and `tests` blocks.
6. Engine merges LLM output with the deterministic envelope block, validates schema, runs the tests, and runs the template over all 200 sample lines. Shows parse rate and a field-by-field preview table.
7. User edits in the YAML editor, re-runs preview, approves. Approval moves the file from `drafts/` to `data/templates/` and records `approved_by`, `approved_at`, and the LLM audit log id.

Implementation (ADR-0005, accepted): drafts are Admin only. `POST /api/templates/drafts` starts a draft from an existing template (`from_template`, id line rewritten) or from a skeleton that passes its own tests, with a sample that is either a file or folder under `allowed_roots` (path plus glob) or up to 200 pasted lines (256 KiB, kept with the draft and deleted with it). `PUT` edits the YAML or sample, `POST .../preview` validates, runs the inline tests and a pathological check, and parses the sample (first 50 rows shown) without saving, returning the sha256 of the YAML it checked, and `POST .../approve {sha256}` refuses (409) a draft saved since that preview, re-runs the same checks, refuses starter ids and replacements that do not raise the version, writes `data/templates/<id>.yaml` atomically, reloads the registry (restoring the previous file if the loader disagrees), and records the approval (version, sha256 of the exact YAML, approver, time, LLM call id) in the append-only `template_approvals` table. `GET /api/templates/{id}/source` returns a template's YAML; `DELETE /api/templates/{id}` removes a user template not used by any source; the check and the removal share a lock with adding a source that names a template, so the two cannot interleave. Every change is audited. The model step (5) is `POST /api/templates/drafts/{id}/ai-draft {provider_id}` (`llm/parser_draft.py`, prompt `parser_draft.v1`): its reply replaces the draft YAML and the call id is kept for the approval record.

A source with `classification: local_only` can only use a local provider for step 5. If none is configured, the UI shows the deterministic sniff result and an empty template skeleton to fill by hand.

---

## 5. Search modes

Both modes run on the same engine, the same read-only connection, and the same guardrails.

### 5.1 Query guardrails (both modes)

| Guard | Implementation |
|---|---|
| Read-only | DuckDB connection opened `read_only=True` on the lake view |
| Statement allowlist | Parse with `sqlglot`; only `SELECT` and `WITH ... SELECT`. Reject `ATTACH`, `COPY`, `INSTALL`, `LOAD`, `PRAGMA`, `SET`, `CREATE`, `EXPORT`, `CALL` |
| No file access | `SET enable_external_access = false` on the connection; `read_csv`, `read_parquet`, `glob` unavailable to user SQL |
| Row cap | Implicit `LIMIT 10000` added if absent; UI pages the rest |
| Timeout | 30 s default, configurable |
| Time range | UI always passes `time BETWEEN ? AND ?`; Ask mode is told the active range |

### 5.2 Query mode

- CodeMirror SQL editor with schema-aware autocomplete over `events` plus any saved views
- Run, explain plan, export CSV/JSON
- Results in TanStack Table with column chooser, sort, pin, cell copy, raw/parsed toggle
- Parameters: `{{param}}` syntax, prompted at run time

### 5.2.1 Simple search (ADR-0009, D35)

A Search tab for people who do not write SQL, with no model involved. `POST /api/search/compile {text, top?}` turns Kibana/Lucene-style text into SQL plus parameters (`search/simple.py`); the client then runs it through `POST /api/query`, which accepts `params` for `$name` placeholders (bound by the driver, never formatted in), so the guard, the per-session view, and the audit apply as for any query.

| Syntax | Meaning |
|---|---|
| `word`, `"a phrase"` | Appears in `raw` or `message`, ignoring case |
| `field:value`, `field:"a b"` | Field equals the value, ignoring case for text |
| `field:adm*`, `field:*` | Wildcard match (escaped `ILIKE`); the field has a value |
| `field:>=400`, `time:<2026-10-10` | Numbers and times; a bare date means that whole UTC day |
| `-term`, `NOT`, `AND`, `OR`, `( )` | Words side by side mean AND; upper-case operators only |
| `\*`, `\:` | Backslash makes the next character literal |

Field names: schema columns, the aliases `user`, `src_ip`, `dst_ip`, `src_port`, `dst_port`, `host`, `process`, `source`, `severity` (which also takes OCSF names: `severity:>=high`), and Sigma field names, resolved through the compatibility map (`EventID`, `TargetUserName`, ...) so they read `unmapped` as rules do; other names are looked up in `unmapped` with a note. Limits: 2048 characters, 50 terms, 20 levels of nesting. With `top`, the SQL counts the top 20 values of that field over the same search. Kusto KQL and SPL are not parsed; Ask translates them.

### 5.3 Ask mode

Ask is the "Ask in plain English" tab of the Search page (ADR-0008); the contract below is unchanged. Run copies the generated SQL into the SQL tab's editor and runs it there. The prompt (`ask.v4`) also accepts a Kusto KQL or SPL query as the question and translates it (ADR-0009). `ask.v3` added answer-shape rules (a count for "how many", one row per value for "which", events for "show"); `ask.v4` adds `count(DISTINCT ...)` for "how many different", INTERSECT and EXCEPT for "both" and "but not", hosts as `device_hostname`, and service ports as `dst_endpoint_port`. `ask.v3` and points the model at keys inside `unmapped`, which the context lists per OCSF class from the caller's scope. A reply cut off well short of its output limit is reported as a full context window, with the setting to raise on the model server. A reply in the wrong shape is asked for once more with a reminder of the JSON shape (the bad reply is audited, not sent back); unescaped backslashes in JSON strings are repaired before validation, and the prose fields (`explanation`, `assumptions`) are trimmed to fit, while `sql` stays strict.

1. User types plain text. Context sent to the LLM: schema (columns, types, sample distinct values capped at 20 per low-cardinality column), active time range, selected sources, last 3 turns.
2. LLM returns a structured response: `{sql, explanation, assumptions[]}`. The agent loop exposes exactly two tools: `get_schema()` and `preview_query(sql, limit=5)`. No other tools.
3. UI shows the generated SQL in a diff-highlighted block. Nothing runs until the user clicks Run (setting `ask.auto_run: true` allows auto-run for `cloud_allowed` sources only).
4. Follow-up refinement ("only failures", "group by source IP") edits the same conversation; each turn shows the new SQL.
5. Any result can be saved as a search; the saved search records the final SQL, not the prompt.

Ask mode never receives raw event rows except via `preview_query` (max 5 rows, redaction applied), and only when the source classification allows the provider.

### 5.4 Saved search format

Stored in `meta.sqlite`, importable and exportable as YAML.

```yaml
schema_version: 1
id: failed_ssh_by_src
name: Failed SSH logins by source IP
description: Top sources of failed sshd auth in the selected window
owner_id: local
tags: [auth, ssh, brute-force]
sources: [linux_auth]           # optional restriction
mode: query                     # query | ask (origin only; always runs as SQL)
sql: |
  SELECT src_endpoint_ip, count(*) AS failures
  FROM events
  WHERE class_uid = 3002 AND status_id = 2
    AND time BETWEEN {{start}} AND {{end}}
    AND actor_process_name = 'sshd'
  GROUP BY 1 ORDER BY 2 DESC
  LIMIT {{top}}
params:
  - { name: top, type: int, default: 25 }
  # start and end are always injected by the UI
origin:
  ask_prompt: "show me failed ssh logins grouped by source ip"   # optional, informational
  llm_audit_id: 00000000-0000-0000-0000-000000000000           # optional
  # simple_text: 'sshd "failed password"'   # optional: the Simple search the SQL came from
created_at: 2026-10-09T20:41:00Z
updated_at: 2026-10-09T20:41:00Z
```

### 5.5 Scheduled searches and dashboard (Slice 4)

Any saved search can be put on a schedule; results land on a Dashboard page.

| Aspect | Decision |
|---|---|
| What runs | The saved search's SQL. A prompt from Ask mode is turned into SQL once, reviewed, and saved; schedules never re-ask the LLM to write new SQL, so runs are deterministic and repeatable |
| Schedule | Cron-style or presets (hourly, daily at 07:00, weekdays), in the installation's timezone. Time range per run: "last interval" by default, or a fixed lookback |
| Who it runs as | The schedule owner, with permissions re-checked at every run. If the owner is disabled or loses access to a source, the schedule pauses and the dashboard says why |
| Results | Each run stores row count, duration, a capped result sample (default 500 rows), and `sources_in_scope`. Keeps the last 30 runs per schedule (configurable) |
| Conditions | Optional: flag a run when row count is above or below a threshold, or changed by more than N% from the previous run. Flags show on the dashboard; alert routing (email, Teams, Slack, webhook) is later |
| Optional summary | Per schedule, an "explain results" summary can run after each run through the gate, with citations (5.3, 6.2). Off by default; local providers only unless every source in scope is `cloud_allowed` |
| Dashboard | Grid of panels, one per schedule: last run time and status, row count, sparkline of counts across runs, flag badge, top rows, click through to the full result in Query mode. Personal and shared dashboards |
| Access | A viewer only sees a panel if they can read every source in that run's `sources_in_scope`. Otherwise the panel shows "restricted" with no data |
| Audit | Schedule create, edit, pause, delete, and every run are audited with the owner id |

Implementation (`search/cron.py`, `search/schedules.py`, `/api/schedules`): a schedule targets a saved search (`kind: search`) or an imported Sigma rule (`kind: rule`). Cron is five fields (`*`, numbers, ranges, lists, steps; day of week 0 to 7; day of month OR day of week when both are set) or a preset (`hourly` 0 * * * *, `daily` 0 7 * * *, `weekdays` 0 7 * * 1-5), in `schedules.timezone` (default UTC); an expression that never fires within five years is refused. Ranges are half-open, [start, end). A run ends `schedules.lag_seconds` (default 120) before its fire time, or before now if the run is more than 5 minutes late, so events that arrive a little late are still inside some run; it starts `lookback_minutes` before its end, or by default where the last successful run ended (first run, or after more than 31 days: one interval of the schedule). A failed run does not move the start forward, so the next run covers its range again. The row count of a saved-search run is a `count(*)` over the search, not the size of the stored sample. The server checks every 30 s and runs at most 20 due schedules per check; a late server runs each missed schedule once, not once per missed slot. Admins and analysts create schedules; the owner or an admin may change, pause, resume, run now (audited `schedule.run_now`), or delete. Each run first re-checks the owner (exists, enabled, not an auditor; a schedule made in no-accounts local mode pauses once accounts exist), the target (saved search still visible to the owner and its SQL and parameter definitions unchanged, by sha256; rule present and enabled), and the owner's sources (any source the schedule read when made or resumed and now lost pauses it). Resuming takes a new snapshot of all three, so a change is accepted only on purpose. A paused run is recorded with its reason and audited as `schedule.pause`. Rule schedules run through the rule runner (so a `rule.run` row and audit exist too) and keep the match list as the sample. Runs keep row count, duration, sources read, up to `schedules.sample_rows` (500) rows, threshold flags (`above`, `below`, `change_pct` against the previous successful run), and the newest `schedules.keep_runs` (30) per schedule. Listing shows a viewer their own, shared, or (admins) all schedules; a run's numbers and rows are returned only when the viewer may read every source it read, otherwise it is marked `restricted`.

UI: Detect > Schedules lists schedules (when, range, last run, state with the pause reason) with Run now, Pause or Resume, and Delete for the owner or an admin, and a New schedule form (saved search or enabled rule, preset or custom cron, range, flag, shared). General > Dashboard shows a panel per visible schedule: last run time, count (`text-kpi`), bars of the last 30 counts, flag badge and reason, the first 5 sample rows, and Open in Search (rule panels: the matched event ids; saved-search panels: the SQL with the run's range and the schedule's parameters filled in as literals, run as the viewer through the guard; offered only when the viewer can see the saved search). A run the viewer may not fully read shows "Restricted" and no data. Dashboards are objects (ADR-0034, D96; `search/dashboards.py`, `/api/dashboards`): named, personal or shared (shared ones visible to everyone, changed by the owner or an admin), holding panels with a section, a position, a size (tile, third, half, full), and a view (table or bars). A new schedule goes on the creator's own first dashboard ("My dashboard", made when needed), or on the one named in the request when the creator may change it. A panel can be added only for a schedule the user can see; a panel whose schedule the viewer cannot see shows "Restricted". The panel's number is the schedule's headline: row count (default), sum or count distinct of a result column over the whole result, or the first row's value, with a label; each run stores it, and a column missing from the result shows "No value" rather than a wrong number. Needs attention lists panels whose latest run is flagged and readable by the viewer, newest first; Acknowledge (anyone who sees the dashboard and may read the run, only for the latest flagged run) clears it until the next flagged run. Audited: `dashboard.create`, `.update`, `.delete`, `.panel_add`, `.panel_update`, `.panel_remove`, `.acknowledge`. Migration 46 moved each owner's panels to a "My dashboard" with their D82 width and view and put shared schedules on one shared "Shared panels" dashboard.

Alert routing (ADR-0007, D33; `alerts/`, `/api/alert-targets`): targets are email (SMTP), Slack, Teams, or a generic webhook. Admins create, change, delete, and test them; analysts may list them (name, kind, host, health) to pick them for schedules. The URL (which carries the token), SMTP password, and webhook signing key are encrypted with the install key and never returned; a webhook's signing key is returned once, when it is created. Address rules, checked on save and again before every send, with the connection made to the approved address (no redirects, no proxies, 10 s, reply read at most 64 KB and not kept): Slack `https://hooks.slack.com`; Teams Workflows hosts only (`*.logic.azure.com`, `*.api.powerplatform.com`; connector URLs were retired in 2026); webhooks `https`, or `http` when every address is private or loopback; no credentials in URLs; link-local, AWS IPv6 metadata, unspecified, and multicast addresses always refused; SMTP needs STARTTLS or implicit TLS verified against the server name unless the relay is on this host. Alerts are summaries (what fired, kind, count, flag reason, range, and a link to `server.public_url`, or `https://<first public name>:<port>`); names are escaped per format (Slack text cannot mention or link, Teams cards cannot link, email HTML is escaped and the subject is one line); webhooks carry `X-Signature-256: sha256=<HMAC-SHA256 of "<timestamp>.<body>">` and `X-Signature-Timestamp`. A target that fails 10 times in a row is marked failing (still tried). Changes and test sends are audited (`alert_target.*`). Schedules carry up to 10 targets (`target_ids`, chosen by the owner, unknown ids refused). A schedule run queues one delivery per target when it is flagged, when a rule schedule without a threshold has at least one match, or when the schedule pauses itself (with the reason); a pause by a person, a quiet run, and on-demand rule runs send nothing. The schedule loop sends due deliveries every 30 s; a failure is retried after 1, 5, and 15 minutes, then the delivery is failed. `GET /api/schedules/{id}/deliveries` shows status, attempts, target name, and the last error (never the URL or the message); the newest 200 per schedule are kept. UI: Settings > Alert targets (admins: add with kind-specific fields, URL entered as a hidden field, signing key shown once, Send test with the result, health, delete); the New schedule form lists targets to send alerts to; the Schedules page has an Alerts column that opens the schedule's delivery log.

### 5.6 CLI

A first-class alternative to the web UI for quick pulls. The CLI is a thin client over the HTTP API: same auth, same query guard, same source permissions, same classification gate, same audit log. It never opens the lake or `meta.sqlite` directly.

| Command | Purpose | Slice |
|---|---|---|
| `remnant login` | Store an API token for a server (OS keychain, fallback file at 0600) | 1 |
| `remnant tail <source> [-n 10] [-f]` | Last N events, optionally follow | 1 |
| `remnant query "<sql>"` | Run SQL through the guard | 1 |
| `remnant query --match '<simple search>'` | Run a Simple search (ADR-0009): compiled by the server, values bound, notes printed to stderr | 4 |
| `--since 1h`, `--where "<expr>"`, `--format table\|json\|csv\|raw` | Quick filters and pipe-friendly output | 1 |
| `remnant search <saved_search> [--param value]` | Run a saved search | 2 |
| `remnant ask "<question>"` | LLM drafts SQL, CLI prints it and asks `Run? [y/N]`. Never auto-runs | 2 |
| `remnant tui [--source id] [--since 1h]` | Interactive terminal UI (Textual, optional `tui` extra): query box (SQL or Simple search, runs on Enter), results table, tail pane with a source picker. Ctrl+L query, Ctrl+T pause tail, Ctrl+Q quit | 6 |

Rules: tokens never accepted as a command-line argument (keeps them out of shell history); log content is printed with terminal control sequences stripped; `--format raw` prints the `raw` column only.

The command name is the one place the codename is user-facing in scripts. If the product is renamed before release, the old command ships as an alias for one release.

### 5.7 Natural-language accuracy (Slice 2 onward)

The promise is "type what you need, get accurate results quickly." That is measured, not assumed.

| Component | What it does |
|---|---|
| Eval harness | `backend/evals/nl_queries/`: 100 questions plus 10 follow-up conversations (earlier turns sent as `earlier_turns`, as the Search bar's Refine does), a deterministic synthetic fixture lake, and reference SQL whose result is the expected answer. Runs per provider and model; reports exact-match rate, executable rate, latency. CI proves the harness (every reference runs, an oracle scores 100%, a wrong model scores 0%); model runs are on demand until a small local model is available in CI |
| Semantic layer | A versioned YAML vocabulary that maps analyst language to OCSF: "failed login" = `class_uid 3002 AND status_id = 2`, "admin" = privileged role values per template, "external IP" = not RFC 1918. Supplied to the model with the schema; templates can extend it. Shipped as `llm/semantic/base.v1.yaml`; every predicate passes the guard at startup or the server refuses to start |
| Verified examples | Saved searches marked "verified" become few-shot examples, retrieved by similarity to the question. Local to the installation. Only admins verify, only shared searches without parameters qualify, any edit clears the mark, and a user only gets examples they can already see |
| Self-check loop | Generated SQL goes through the guard, then a `preview_query`. Empty results, parse errors, or implausible counts trigger up to two automatic refinements before the user sees the SQL. Every attempt is audited |
| Answer view | Results plus a short summary with event-id citations (Slice 4 rules), and the assumptions list. The SQL is always one click away |
| Model guidance | Published table of which local models pass which share of the eval suite, so users pick a model on evidence |

Accuracy targets for v0.1 on the bundled suite: 90% executable, 75% exact on the reference local model, every answer showing its SQL.

---

### 5.8 Overview (ADR-0008)

The landing page after login and for `/` when the viewer has no Dashboard panel, and for unknown paths (ADR-0031: with a panel, `/` opens the Dashboard). `GET /api/overview` returns, read as the viewer: events per readable source per hour for the last 24 hours (through the guard and the per-session `events` view, by `coalesce(time, time_observed)`); per readable source, its ingest state, when it last received an event (`time_observed`, looked up over the last 7 days), files waiting, records skipped, and the error (replaced by a generic line for non-admins, as on the Sources page); rule runs with matches and flagged saved-search schedule runs from the last 24 hours, newest 20, leaving out any run that read a source the viewer cannot read; paused schedules the viewer can see, with the reason; and, for admins only, alert targets whose last send failed and deliveries that failed after every retry in the last 24 hours. Answers are cached per viewer and set of readable sources for 60 s; each computed answer writes one `overview.view` audit row with the sources read. A rule detection opens its matched events in Search; a flagged search opens the Dashboard.

### 5.9 Investigation (Slice 7, ADR-0016, D42)

- **Search bar**: tabs are **Search** and **SQL**. The Search bar's AI toggle (sparkle) sends plain English to Ask; the SQL is shown and runs on click. Off, the bar takes Simple syntax.
- **Facets**: source, host, user, source IP, destination host, severity, status, class, parse status; top 10 values for the current search via `POST /api/search/facets` (guarded subquery, caller's view, audited `query.facets`). Click to add `field:"value"`, Alt-click to exclude.
- **Suspicious presets**: `backend/app/content/presets/suspicious.yaml`, editable Simple searches under a **Suspicious** menu.
- **Investigations page** (`/investigations`, `search/entities.py`, `api/entities.py`): entity risk and an investigator graph.
  - `GET /api/entities/risk` (audited `investigate.risk`): the newest 20,000 rule matches on sources the caller may read, one per rule and event, joined in DuckDB to events still in the caller's view and range (ids bound as a list parameter). Score: 10 per critical, 5 high, 2 medium, 1 other, plus 3 per flagged schedule run in the range whose sample names the entity and that read nothing outside the caller's sources. Top 50 users, source IPs, and hosts, each with its parts, rule titles, and a Search handoff.
  - `GET /api/entities/graph` (audited `investigate.graph`): lanes as SVG columns of cards. Entity mode for a user, IP (either side), or host (device or source host): Entity, Sources, Activities (message and OCSF class), Targets (destination host or IP). AI flow, for everyone or one person, MCP server, or catalog service: People, AI clients (Claude Code, MCP clients from the inventory, "Browser or app" for network logs), Tools and MCP servers, Destinations (catalog services, `api.anthropic.com`, MCP URL hosts). Cards carry events, rule matches, highest severity, and badges (rule matches, High severity, Not approved, Sensitive data); at most 5 entity cards and 15 per other lane, largest first, with "N more". Each card has Search SQL built server-side with values as quoted literals; Search runs it through the guard as usual.
  - Users are merged by identity (ADR-0018, Settings > Identities): risk rows add up, with the logged names listed; an entity search for a user finds every name of that person; AI flow People cards merge with the email form shown.
  - Selecting a card dims everything outside its connected path and opens a detail panel with **Open in Search** and, where it applies, **Investigate this** (a target host or IP, a person, an MCP server, or a service).

## 6. Model provider interface and classification gate

### 6.1 Provider interface

One Python protocol. Two implementations in v1.

```python
class Provider(Protocol):
    id: str                      # "ollama-local", "anthropic"
    locality: Literal["local", "cloud"]
    def chat(self, messages, tools=None, response_schema=None, max_tokens=..., temperature=...) -> ProviderResponse: ...
    def models(self) -> list[str]: ...
    def health(self) -> ProviderHealth: ...
```

| Adapter | Covers | Locality rule |
|---|---|---|
| `OpenAICompatibleProvider` | Ollama, LM Studio, llama.cpp server, vLLM, OpenAI, Groq, Together, Mistral, OpenRouter | `local` only if `base_url` host resolves to loopback, link-local, RFC 1918, or a user-declared `trusted_local_hosts` entry. Everything else is `cloud`. |
| `AnthropicProvider` | Anthropic Messages API | Always `cloud` |

`AnthropicProvider` (`llm/providers/anthropic.py`, provider kind `anthropic`, chosen when the provider is added and fixed after): `POST {base_url}/messages` with `x-api-key` and `anthropic-version: 2023-06-01`; system turns go to the top-level `system` field; the gate's OpenAI-style tool specs become Messages tools (`name`, `description`, `input_schema`); an assistant tool request becomes `tool_use` blocks and tool results become `tool_result` blocks in one user turn; `stop_reason: max_tokens` is recorded as `truncated`; `GET {base_url}/models` lists models. Locality is `cloud` whatever the URL resolves to, so `https` and the cloud acknowledgment are always required and `local_only` data is always blocked. Both adapters share `llm/provider_http.py` (pinned address, no redirects, 64 KB cap). There is no JSON mode; the gate's `answer_json()` extracts and validates the answer as for other providers.

**Thinking control** (`llm_providers.reasoning`, migration 25): for OpenAI-compatible providers an admin can set Thinking to Off, Low, Medium, or High, sent as `reasoning_effort` (`none` for Off); unset sends nothing and the model decides. Tested on Ollama 0.34.1 with qwen3.5:9b: a short JSON answer took 4.2 s and 360 tokens with the model default and 0.2 s and 6 tokens with Off, and an Ask-shaped request returned valid JSON in 1.9 s with Off where the default had run out of output tokens. The Anthropic adapter ignores it. When an answer is cut off at the output limit, the error says where to change it.

Fresh install: provider list contains one disabled entry pointing at `http://ollama:11434` (compose profile) and `http://host.docker.internal:11434`. The settings page offers to add cloud providers behind a confirmation that explains the classification gate.

### 6.2 Data classification gate

Every source carries `classification: local_only | cloud_allowed`. Default on creation is `local_only`. Admins change it on the Sources page (`PATCH /api/sources/{id}`, audited `source.classify` with the old and new label); the form says what each label means. Only events ingested after the change take the new label, so moving to `cloud_allowed` does not release events already stored, while moving to `local_only` blocks cloud use of the source at once (by configuration). A block is shown where it happened (Ask, Explain, parser drafting) with the sources named, and recorded in `llm_calls` (`classification_result = blocked`), which the audit log viewer filters on.

The gate sits in exactly one place: `llm/gate.py`, called by the agent loop before any provider call. It never lives in the UI.

```
request = {provider, purpose, sources_in_scope[], payload}
if provider.locality == "cloud" and any(src.classification == "local_only" for src in sources_in_scope):
    raise ClassificationBlocked(sources=...)   # hard block, logged, surfaced in UI
if redaction.enabled and provider.locality == "cloud":
    payload = redact(payload)                  # IPs, emails, usernames, hostnames per config
audit_log.write(...)
return provider.chat(payload)
```

`sources_in_scope` is derived from the query or the sample, never from a user-supplied list, so the UI cannot be tricked into under-reporting scope.

Implementation rules (Slice 2, `llm/gate.py`):

- `sources_in_scope` is every source folder in the lake that the caller's server-built scope reads, including sources removed from configuration that still hold data.
- A source counts as `local_only` if its configuration says so, if it is not configured at all, or if any stored event in scope carries `classification != cloud_allowed` from ingest. Relabelling a source does not release events already stored under the stricter label (T8).
- Event data reaches a model only through `data_message()`, which puts it under a `data` key and records the sources it came from. The gate adds those sources to the scope it checks, so data cannot travel under a narrower scope than it was read from. A declared source with no folder in the lake counts as `local_only`. Tool results, and any message whose JSON has a `data` key, are refused unless they declare their sources.
- If the event-label check cannot run (for example a file without a `classification` column), every source in scope counts as `local_only`.
- A cloud provider must use `https`. Plain `http` is refused when the provider is saved and again at call time.
- Locality is decided once per call, and the adapter connects to the address that decision was made on (Host header and TLS name unchanged), so DNS rebinding cannot turn a local call into a cloud one. Local calls ignore proxy environment variables; a trusted local host name that does not resolve is treated as cloud.
- The system message is always a versioned prompt file, named by the caller and read by the gate, plus a fixed notice that anything under `data` is untrusted. Caller messages may only be `user`, `assistant`, or `tool` turns.
- Tools are accepted only for `ask`, by name, and the gate supplies the schemas for `get_schema` and `preview_query`; a tool call to anything not offered is rejected.
- Responses with a schema are validated with Pydantic; a mismatch is rejected and recorded as `schema_invalid`. Before validation, `answer_json()` takes the one JSON answer out of common wrappers: leading `<think>` blocks from reasoning models, one code fence, or one object inside a sentence. Two candidate answers, or thinking that never closes, count as no answer. A reply cut off at the output limit is recorded as `truncated` with its own message. Ask allows 4096 output tokens so a reasoning model has room to think and answer.

### 6.3 Redaction (Slice 5, ADR-0010, D36)

Off by default. Logs reach a cloud model only from sources an admin marked `cloud_allowed`, through a provider an admin acknowledged as cloud; that is the consent, and the model then sees the log as it is. An admin can turn redaction on per cloud provider (`redact`, audited `provider.update`); local providers are never redacted.

When on, for `ask`, `explain`, and `report` calls (`llm/redact.py`, applied in the gate after the classification check and before the audit row):

| What | Becomes |
|---|---|
| `src_endpoint_ip`, `dst_endpoint_ip`, `device_ip` values | `IP_xxxxxxxx` |
| `actor_user_name` values, email addresses anywhere | `USER_xxxxxxxx` |
| `device_hostname`, `src_endpoint_hostname`, `dst_endpoint_hostname` values | `HOST_xxxxxxxx` |
| IPv4 and IPv6 addresses anywhere in text (raw lines, messages, questions, earlier SQL, tool arguments) | `IP_xxxxxxxx` |
| User and host names learned from those columns, wherever they appear in text (whole word, ignoring case, 3 characters or more) | their tokens |
| Event ids, times, ports, numbers, source ids, column names, the prompt | unchanged |

Tokens are 8 hex characters of HMAC-SHA256 over the kind and the normalized value (IPs canonical, names lower-cased), keyed with a key derived from the install key, so they are stable across calls and restarts. The reverse map exists for one call only, is never stored or logged, and is applied to the reply (text and tool arguments) before validation, so Ask SQL, explanations, and claims carry real values; tokens the model invents are left as they are. The audit row keeps the hashes of what was actually sent and received, `redaction_applied`, and `redaction_counts` (per kind, never values), shown in the audit log viewer. Parser drafting is not redacted (a parser must match the real line shape; samples are chosen by an admin). If the key is unavailable, the call is refused rather than sent unredacted.

### 6.4 LLM audit log

Table `llm_calls` in `meta.sqlite`:

`id, ts, owner_id (the acting user), provider_id, model, locality, purpose (ask|parser_draft|explain|report), sources_in_scope (json), classification_result (allowed|blocked), redaction_applied (bool), prompt_sha256, prompt_tokens, completion_tokens, latency_ms, response_sha256, cited_event_ids (json), citation_check (pass|fail), error`

Prompts and responses are stored in full only if `llm.store_bodies: true` (default false). Hashes are always stored.

Also stored: `prompt_ref` (`<prompt file>@<sha256 prefix>`), `finished_at`, and `error` (`classification_blocked`, `cloud_without_tls`, `provider_disabled`, `request_invalid`, `provider_error`, `internal_error`, `schema_invalid`, `truncated`, `tool_not_offered`). The row is written before the provider is called, so a failed audit write stops the call (fail closed). It is completed once with the outcome and then frozen by trigger; deletes and `INSERT OR REPLACE` are refused (the same replace guard now covers `audit_log`). Citation results (Slice 4) are computed inside the gate before the row is completed.

### 6.5 Audit log viewer (Slice 5)

Settings > Audit log, for admins and auditors only (`/api/audit/...`, analysts get 403). Two tabs: **Activity** (`audit_log`: time, user, action, outcome, address, and the detail as text) and **AI calls** (`llm_calls`: user, purpose, provider and model, locality, result, tokens, latency, prompt reference, sources in scope, redaction, citation check, and the hashes; prompt and response bodies are never returned, even when `llm.store_bodies` kept them). Filters: action prefix (activity) or purpose (AI calls), outcome (`blocked` for classification blocks), time, and a user picked from the list. Newest first, 100 per page, paged by id. Export CSV writes everything matching the filters, up to 50,000 rows, with the same formula escaping as query exports. Reading writes `audit.view` and exporting writes `audit.export`, each with the filters used. Both tables refuse updates and deletes by trigger (tested); there is no delete endpoint. Migration 21 adds indexes on `audit_log` time, action, and user.

---

## 7. Security threat model

Assumptions: the app runs on a trusted host, the user is trusted, log content is hostile, model providers are honest-but-curious, and the network between app and provider may be observed.

### 7.1 Threats and controls

| ID | Threat | ATLAS | ATT&CK | Control | Slice |
|---|---|---|---|---|---|
| T1 | Log line contains instructions that hijack the LLM when it explains events or drafts a parser | AML.T0051.001 LLM Prompt Injection: Indirect | T1565 Data Manipulation, T1562.001 Impair Defenses | Event content is passed as structured data under a `data` key with explicit delimiters and a system instruction that content is untrusted. LLM has no write tools. Outputs are structured JSON validated against a schema; free text never becomes an action. | 2, 4 |
| T2 | Injected instruction tries to make generated SQL exfiltrate or alter data | AML.T0051.001 | T1059 Command and Scripting Interpreter | Statement allowlist, read-only connection, `enable_external_access=false`, no `ATTACH`. SQL always shown before run. | 2 |
| T3 | Sensitive logs sent to a cloud provider | AML.T0057 LLM Data Leakage | T1041 Exfiltration Over C2 Channel (analogous), T1567 Exfiltration Over Web Service | Classification gate in one code path, scope derived from query not user input, default `local_only`, fresh install has no cloud providers, redaction, audit log. | 5 |
| T4 | LLM fabricates findings | AML.T0048.002 Societal Harm (misinformation, analogous), no direct ATT&CK | n/a | Citation requirement: response schema requires `event_ids[]` per claim; engine verifies every id exists in the result set handed to the LLM; failures are shown as "unverified" and logged `citation_check=fail`. | 4 |
| T5 | LLM-drafted parser is malicious or broken (regex DoS, wrong mapping hides events) | AML.T0051.001, AML.T0043 Craft Adversarial Data | T1562.001 | Drafts are inert until approved. Regex compiled with timeout and tested against pathological inputs. Tests must pass. Approval recorded. Diff shown vs starter if replacing. | 3 |
| T6 | Prompt or system instruction extraction | AML.T0056 LLM Meta Prompt Extraction | T1552 Unsecured Credentials (if secrets in prompt) | No secrets in prompts. System prompts are in the repo, not secret. Provider keys live in env / settings store, never in messages. | 2 |
| T7 | Malicious model or provider endpoint (user points at a hostile OpenAI-compatible URL) | AML.T0010 AI Supply Chain Compromise, AML.T0040 AI Model Inference API Access | T1195 Supply Chain Compromise | Provider responses treated as untrusted: strict JSON schema, size caps, no code execution. Locality is computed from the URL, not declared by the user. TLS required for non-local. | 2 |
| T8 | Local-only / cloud flag spoofed through API | AML.T0057 | T1565 | Classification is a server-side column copied at ingest; the API has no endpoint to reclassify events, only sources (re-ingest required). | 5 |
| T9 | Web UI exposed on LAN without auth | n/a | T1190 Exploit Public-Facing Application, T1078 Valid Accounts | Non-loopback bind with no users enters setup-only mode (one-time, expiring, single-use setup link). No insecure flag. Argon2 passwords, per-user API tokens. HttpOnly, Secure, SameSite=Strict session cookie. CSRF token on all non-GET. Rate limit on login. HTTPS by default off loopback. | 1 |
| T10 | Stored XSS from log content rendered in UI | n/a | T1189 Drive-by Compromise (analogous) | React escapes by default. Raw view uses a text node, never `dangerouslySetInnerHTML`. CSP: `default-src 'self'`, no inline scripts. | 1 |
| T11 | Path traversal via source folder config | n/a | T1083 File and Directory Discovery, T1005 Data from Local System | Source paths must be under configured `allowed_roots`. Resolved with `realpath`, symlinks outside roots rejected. | 1 |
| T12 | Dependency compromise | AML.T0010 | T1195.001 | Lockfiles (`uv.lock`, `pnpm-lock.yaml`), Dependabot, pinned base images, SBOM in release. | 6 |
| T13 | Audit log tampering | n/a | T1070 Indicator Removal | Audit table is append-only via SQLite trigger; no delete endpoint; export to file supported. Each row carries a chain hash over its content and the previous row, checked with the lake (D59). | 5, 8 |
| T14 | Denial of service via malformed log (huge line, multiline bomb, zip bomb style repetition) | n/a | T1499 Endpoint DoS | 64 KB event cap, 8 KB default `max_len`, 200-line sample cap, per-file read rate limits. | 1 |
| T15 | Analyst reads sources they are not cleared for (directly, via Ask mode, via a shared saved search, or via the LLM) | AML.T0057 (when via LLM) | T1213 Data from Information Repositories, T1078 | Source groups enforced server-side in the per-session `events` view; every surface uses that view; saved searches run as the caller; gate receives scope from the view. Access changes audited. | 2 |
| T16 | Setup link intercepted or reused to claim the admin account | n/a | T1078, T1550 Use Alternate Authentication Material | Link token is random, single use, expires in 30 minutes, stored hashed, printed only to the server log, invalidated once an admin exists. | 1 |
| T17 | Log content injects terminal escape sequences into CLI output | n/a | T1059 (analogous) | CLI strips control sequences from all event fields before printing. | 1 |
| T18 | Shared or orphaned accounts break attribution | n/a | T1078 | No shared-login feature, per-user audit, admin can disable users, API tokens per user and revocable. | 2 |
| T19 | Scheduled search keeps running after the owner loses access, or runs with someone else's rights | n/a | T1078 | Runs as the owner, permissions re-checked each run, schedule pauses on loss of access, audited | 4 |
| T20 | Dashboard panel leaks results to a viewer without access to the underlying sources | AML.T0057 (when a summary is shown) | T1213 | Panel visibility checked against `sources_in_scope` of the run for each viewer; restricted panels show no data | 4 |
| T21 | Connector credentials stolen and used to read the tenant | n/a | T1528 Steal Application Access Token, T1552 Unsecured Credentials | Read-only least-privilege permissions, certificate auth preferred, secrets encrypted at rest, never logged or sent to an LLM, credential rotation documented | 7 |
| T22 | Stored logs altered to hide activity | n/a | T1565.001 Stored Data Manipulation, T1070 Indicator Removal | Hash-chained ledger of every lake file, verified daily and on demand; changed, missing, and inserted files reported; signed seals and report (D59, ADR-0022) | 8 |
| T24 | Someone in the tenant, or with any Microsoft account, signs in without being invited | n/a | T1078.004 Valid Accounts: Cloud Accounts | Single-tenant issuer checked exactly; accounts found only by `iss` + `sub` bound through an admin's invite; optional required group checked every sign-in; refusals audited (ADR-0013) | 6 |
| T25 | Login CSRF, a stolen callback URL, or a replayed authorization code | n/a | T1550.001 Application Access Token, T1557 Adversary-in-the-Middle | PKCE, `state`, `nonce`, flow cookie bound to the browser, single-use 10-minute flows, server-side code exchange (ADR-0013) | 6 |
| T26 | Forged or substituted ID token | n/a | T1606 Forge Web Credentials | Signature against the provider's keys with an algorithm allowlist; `iss`, `aud`, `azp`, time, and `nonce` checked (ADR-0013) | 6 |
| T27 | Identity provider outage or misconfiguration locks everyone out | n/a | T1499 (impact, analogous) | Administrators keep password sign-in when SSO is on; `app-admin reset-password` on the host (ADR-0013) | 6 |
| T28 | SSO client secret leaks | n/a | T1552.001 Credentials In Files | Environment only, never logged or returned by an API; rotation in the setup guide; the secret alone signs nobody in without a bound invite and, if set, group membership (ADR-0013) | 6 |
| T29 | An attacker stops a log source to hide activity | n/a | T1562.006 Indicator Blocking | Quiet-source alert after the set period; state on Sources and Overview (ADR-0014) | 6 |
| T30 | Someone turns the quiet-source watch off first | n/a | T1562.001 Impair Defenses | Administrators only; every change audited with the old and new setting (ADR-0014) | 6 |
| T31 | Staff paste sensitive data into unapproved AI services | AML.T0057 LLM Data Leakage | T1567 Exfiltration Over Web Service | Shadow-AI view from network logs; AI watch alert on first sighting of a service not Approved (ADR-0015) | 7 |
| T32 | A rogue or poisoned MCP server is installed and used by an agent | AML.T0053 AI Agent Tool Invocation, AML.T0086 Exfiltration via AI Agent Tool Invocation | T1195 Supply Chain Compromise | MCP inventory from telemetry and endpoint configs; allowlist; alert on first sighting of a server not Approved (ADR-0015) | 7 |
| T33 | Telemetry or inventory fields carry text that instructs a model | AML.T0051.001 LLM Prompt Injection: Indirect | n/a | Stored as data, rendered as text, sent to a model only through the gate (ADR-0015) | 7 |
| T34 | The OTLP endpoint is flooded or fed forged records | n/a | T1499 Endpoint DoS, T1565.001 Stored Data Manipulation | Per-source token; body, record, and rate caps; records land only in the token's source (ADR-0015) | 7 |
| T35 | An ingest token or Anthropic key leaks | n/a | T1528, T1552 Unsecured Credentials | Tokens hashed, shown once, revocable; keys encrypted and write-only; read-scoped keys recommended (ADR-0015) | 7 |
| T36 | Usage data about named people is read by someone without a need | AML.T0057 (if sent to a cloud model) | T1213 | `local_only` default; source groups; content dropped at the door unless an admin opts in, audited (ADR-0015) | 7 |
| T37 | Facet, risk, or graph queries used to read sources outside the caller's groups, or to slow the engine | n/a | T1213, T1499 | Server-built SQL over the caller's view; guarded subquery; fixed columns; timeouts and node caps (ADR-0016) | 7 |
| T38 | Attacker-controlled values in facet values or graph labels inject markup | n/a | T1189 (analogous) | Text nodes only; CSP unchanged (ADR-0016) | 7 |
| T39 | A compromised endpoint sends forged or flooding records under its group token | n/a | T1565.001, T1499 | Records land only in that group's source; caps and rate limits; token rotation (ADR-0017) | 7 |
| T40 | The agent config or token file leaks from the deployment tool | n/a | T1552.001 | Config holds no secret; token file separate, service-account readable, write-only to one source, revocable (ADR-0017) | 7 |
| T41 | A crafted user name is merged into a real person's activity, hiding or framing them | n/a | T1036 Masquerading | Merges only by administrator-listed domains and accepted aliases; suggestions show evidence, never automatic; Search keeps exact names (ADR-0018) | 7 |
| T42 | The outbound proxy or a wrong CA bundle intercepts connector tokens | n/a | T1557 Adversary-in-the-Middle | Proxy and CA are administrator config; certificate names still checked; proxy only for fixed public hosts (ADR-0018) | 7 |
| T43 | A watched device's name or address shown to people who cannot read the sources it appears in | n/a | n/a | Device states are computed in each viewer's scope; only names and addresses chosen by an administrator are listed; alert targets shown to administrators only (ADR-0019 row 7) |
| T44 | A silent sensor or collector (blinded on purpose) goes unnoticed | n/a | T1562.001 Impair Defenses, T1562.006 Indicator Blocking | Watched devices alert on silence and on a sharp drop in volume, as the system, audited `device.quiet` and `device.resumed` (ADR-0019 rows 4 and 5) |
| T45 | A wrong address mapping blames the wrong person | n/a | n/a | Shown as "at that time" with its source; only successful logons, User-ID logins, and VPN sessions; 12-hour limit (ADR-0020 row 1) |
| T46 | A viewer learns who had an address from sources they cannot read | n/a | n/a | Mappings computed in the viewer's own scope; lookups audited `address.lookup` |
| T47 | An attacker using stolen credentials is shown under the victim's name | n/a | T1078 Valid Accounts | The mapping reports what the logs say; the logon events stay one click away in Search |
| T48 | Log injection or flooding of a syslog listener from outside the LAN | n/a | T1565.001, T1499 | Private senders only by default, per-address drop counts, 100 connections and 512 MB spool per source (ADR-0021 rows 4 and 7) |
| T49 | A sender claims another device's host name | n/a | T1565.001 | The sender's address is kept in `device_ip` next to the claimed host (ADR-0021 row 5) |
| T50 | Syslog read in transit | n/a | T1040 | TLS listener with the server certificate; UDP and plain TCP documented as plain text (ADR-0021 row 6) |
| T51 | One query exhausts server memory (an analyst, or a log line that steers Ask's preview or self-check SQL) and the kernel kills the server, stopping ingest and alerts | AML.T0029, AML.T0051.001 | T1499 | Service memory limit (systemd MemoryHigh/MemoryMax, Compose mem_limit) with restart, per-query DuckDB memory sized so every allowed query fits, thread and concurrency limits, literal size caps in the guard, out-of-memory reported as a failed query (D58, D79, D80) |
| T52 | Someone with write access to the server rewrites the lake ledger and the audit chain together, so verification passes | n/a | T1565.001, T1070 | Daily seals with both chain heads sent to alert targets off the server; a rewritten chain no longer matches the heads already sent (D59) |
| T53 | A poisoned or broken threat intel feed floods searches with false matches or hides real ones | n/a | T1565.001 | Fixed HTTPS feed hosts, size caps and format checks before a swap, previous file kept, entry counts and age shown (D62) |
| T54 | The enrichment update path is used to send data out | n/a | T1041, T1567 | Fixed host list, no event data in any request, off on a fresh install, every download audited (D62) |
| T55 | An analyst sends events they can read to a destination outside the network | n/a | T1567 | Only admin-created alert targets; events from local_only sources withheld unless every target address is private; 1 to 100 events; every send audited with event ids (D63) |
| T56 | A report carries data to someone who should not see it | n/a | T1567 | Built from the owner's scope and re-checked each scheduled run; local_only figures only to targets whose every address is private, otherwise headline figures and a link; every generation, download, and send audited (ADR-0025) |
| T57 | An attacker reads, forges, or alters the record of agent sessions | AML.T0010 ML Supply Chain Compromise | T1546 Event Triggered Execution, T1565.001 | Per-source OTLP token; HTTPS off loopback; content off by default; plugin pinned and hashed on the source page; lake files hash-chained (ADR-0026, ADR-0022) |
| T61 | The hooks plugin, as code on every tool call, is tampered with or turned into a channel out | AML.T0010 ML Supply Chain Compromise | T1546 Event Triggered Execution, T1195.002 | Observe only (async, exit 0, prints only `{}`, never the receiver's response); destination and token from an admin-only machine config when deployed (D118); destination and token fixed at download, config read as data; one short script, version pinned, SHA-256 shown before publishing; HTTPS required; metadata by default; pilot list (ADR-0026 amendment) | 9 |
| T62 | Agent sessions carry injected instructions in tool output, or move company data to AI services | AML.T0051.001 LLM Prompt Injection: Indirect, AML.T0057 LLM Data Leakage | T1567 Exfiltration Over Web Service | What the hooks plugin monitors: each session's tools, paths, web hosts, and programs in order (Sessions view); tool output stored only as data when kept, never placed in a prompt as instructions; sensitive-data categories counted when content is sent (ADR-0026) | 9 |
| T63 | A device reports a forged company Claude account email to hide personal use | AML.T0057 LLM Data Leakage | T1036 Masquerading, T1565.001 | The email is labelled as reported by the device; a company email with no Entra sign-in in the window is shown as not confirmed; the Anthropic usage report corroborates; personal use through `claude.ai` still needs Entra (ADR-0030 amendment 2026-10-29) |
| T64 | The Windows hook runs PowerShell with ExecutionPolicy Bypass on every tool call, a pattern that hides or imitates malicious PowerShell | AML.T0010 ML Supply Chain Compromise | T1059.001 PowerShell, T1546 | `-NoProfile`; exec form with a fixed script path; script SHA-256 shown before publishing; optional Authenticode-signed script run with AllSigned; EDR exclusions by script hash, never by command line (ADR-0026 amendment 2026-10-29 row 17) |
| T58 | Reverse proxy collapses every client into one address: one person's failed logins lock everyone out, and audit rows lose the client address | n/a | T1110 Brute Force, T1078 Valid Accounts | `server.trusted_proxies` (ADR-0027); address taken from `X-Forwarded-For` only when the peer is a listed proxy, walked from the right | 8 |
| T59 | A client forges `X-Forwarded-For` to dodge the login limiter or plant a false address in the audit log | n/a | T1110, T1070 Indicator Removal | Header ignored unless the TCP peer is listed; rightmost untrusted entry only; catch-all ranges refused; request log keeps the TCP peer too (ADR-0027) | 8 |
| T60 | One user, a burst of scheduled summaries, or a loop starves everyone else of the model | AML.T0029 Denial of ML Service | T1499 Endpoint Denial of Service | Per-provider queue with a wait budget, one Ask or Explain per user at a time, cancels free their place, waits and retries audited (ADR-0028) | 8 |
| T23 | An outside assistant reading results over MCP follows instructions planted in log fields, or sends `local_only` data to a cloud model | AML.T0051.001 LLM Prompt Injection: Indirect, AML.T0057 LLM Data Leakage | T1213 Data from Information Repositories | Read-only tools only; per-user token and scope; `local_only` results withheld unless the endpoint is marked local; data-not-instructions notice on every result; every call audited; off by default | 7 |

### 7.2 Trust boundaries

```
[Log files: HOSTILE] -> ingest -> [Lake: data, not instructions]
[Lake] -> engine -> [Result set: data] -> gate -> [Provider: honest-but-curious]
[Provider response: UNTRUSTED] -> schema validation -> citation check -> [UI]
[Browser] -> auth + CSRF -> [API]
[MCP client: UNTRUSTED] -> per-user token -> [events view] -> classification check -> [Result set: data]
```

---

### 7.3 AI feature mapping (CLAUDE.md security rule 12)

| Feature | What the model sees | What the model can do | ATLAS | Controls |
|---|---|---|---|---|
| Ask mode (Slice 2) | Schema, up to 20 sample values per low-cardinality column, the top 30 keys of `unmapped` per OCSF class (with up to 5 sample values for keys of at most 20 values), time range, up to 3 earlier turns, preview rows (5, values capped at 300 characters), all under `data` with declared sources | Return `{sql, explanation, assumptions}`; call `get_schema` and `preview_query` | AML.T0051.001 (values in logs, previews), AML.T0057 (scope sent to a cloud model), AML.T0056 (prompt is public, no secrets) | Gate classification check over declared sources; guard and read-only engine on every preview; 5-row cap; schema-validated answer; SQL shown, never run for the analyst; every call in `llm_calls`; auditors have no Ask |
| Parser draft (Slice 3, ADR-0005) | The column list, the deterministic envelope result and format guess, up to 20 payloads (syslog header removed, 2,000 characters each) and 5 full lines, all sample data under `data` with declared sources: a pasted sample under the reserved id `draft_sample_local_only` (no source may use the `draft_sample` prefix, and the gate treats it as `local_only` regardless), a file sample under every source whose own path, glob, and symlink resolution would read each sampled file, plus the reserved id for any file no source reads | Return only `payload`, `transforms`, `mapping`, and `tests`; no tools | AML.T0051.001 (instructions in sample lines), AML.T0043 (crafted lines steering a regex or mapping), AML.T0057 (samples sent to a cloud model) | Admin only; one draft at a time; schema-validated reply with extra keys refused; id, envelope, version, and classification default set by the server; draft inert until a preview passes tests and the pathological check and an admin approves; regex timeouts; approval records the `llm_calls` id and whether the approved bytes are unchanged from the model's output; refusals link the audit row to the `llm_calls` row; every call audited |
| Explain these events (Slice 4) | Up to 50 events the analyst picked, only those in sources they may read, each reduced to 16 columns (event id, source, time, class, activity, status, severity, message, actor user and process, source and destination address and port, device host, values cut at 500 characters) plus `raw` cut at 2,000, and an optional question of up to 500 characters, all under `data` with the events' sources declared | Return `{claims: [{text, event_ids}]}` (1 to 10 claims); no tools | AML.T0051.001 (instructions in the events steering the explanation), AML.T0057 (events sent to a cloud model); also T4 (7.1), a confident but false claim about the events, which citations and the verified label address | Admin and Analyst only; ids validated as UUIDs and fetched through the guard inside the caller's scope; gate classification over the events' sources; schema-validated answer; the gate records `cited_event_ids` and `citation_check` (pass only when at least one id is cited and every cited id was sent); each claim is marked verified only when it cites at least one sent id and nothing else, and the UI labels the rest "unverified"; answer shown as text, never run; one request per user at a time; every call in `llm_calls` and audited as `explain.request` |

Explain in the UI: on Search and Ask results, an event's details offer "Select for Explain"; the results header offers "Explain N selected", or "Explain" for the first 50 rows when nothing is selected. Rule run panels offer "Explain matches". The panel picks an enabled provider (local first, with its badge) and an optional question, lists claims in order with each cited event (the last 12 characters of the id, since UUIDv7 ids share their leading time digits; a cited id that was not sent is shown in red), labels claims that fail the check "unverified", and offers "Open cited events in Search" (sent ids only) and "Download report (Markdown)": a report draft built in the browser from the answer, with every claim, its event id references, unverified claims marked, the events sent, the sources, and the `llm_calls` id. No report object is stored yet (Q2 stays open).

## 8. Slice roadmap

Each slice ships working end to end, with tests, before the next starts. Definition of done per slice is in `CLAUDE.md`.

| Slice | Scope | Not in scope | Key risk |
|---|---|---|---|
| 0 | This spec, `CLAUDE.md`, design brief, repo skeleton, CI | Code | Over-designing |
| 1 | Read JSON, CSV, and syslog files and folders with tail/watch. RFC 3164 and 5424 envelope parse. Raw line preserved. Parquet lake + compaction + retention. DuckDB read-only query. Query mode with SQL editor and results table. First-run admin setup, login, HTTPS by default (3.6, T9, T16). CLI `login`, `tail`, `query`. Windows JSON (NXLog, Winlogbeat) and Snare via generic JSON/CSV paths. | Any LLM. Templates beyond a built-in generic JSON, CSV, and syslog-envelope-only parser. | Framing and encoding edge cases eating the slice |
| 2 | Provider interface, OpenAI-compatible adapter, Ollama in compose profile. Ask mode with visible SQL and approve-to-run. Saved searches with params, tags, YAML import/export, private or shared. Basic LLM audit log (hash level). Multi-user: invites, Admin/Analyst/Auditor roles, source groups, per-user audit (3.6, T15, T18). CLI `search`, `ask`. NL accuracy track (5.7): eval harness, semantic layer, verified examples, self-check loop. | Anthropic adapter (small, can land here if time allows). Redaction. | Local models producing bad SQL; mitigated by schema-rich prompt and preview tool |
| 3 | Source discovery and auto-labeling with suggested groups (3.6). Starter template pack (4.4). Template engine with all payload formats. LLM-generated parser flow (4.5). Native EVTX via `evtx` library. Template test runner. | Sigma | Template count; ship fewer, tested, rather than all untested |
| 4 | Sigma rule loading and pySigma DuckDB backend with the compatibility field pipeline (community `windows` and `linux` rule fields mapped to OCSF columns). Rule run on demand and on schedule. Scheduled saved searches and Dashboard page (5.5). Alert routing: email, Microsoft Teams, Slack, generic webhook. "Explain these events" with event-ID citations and citation verifier. | Alert routing. OCSF-native Sigma pipeline (later). | Compatibility pipeline coverage; measure against the SigmaHQ core rule set and report the compile rate |
| 5 | Classification gate (6.2), redaction (6.3), full audit log (6.4), audit export. Anthropic adapter if not already done. | | Making the gate the only path; grep the codebase for direct provider calls |
| 6 | Light mode, keyboard shortcuts, command palette polish, CLI `tui`, single-user and team VM install guides, docs site, rsyslog / syslog-ng / Vector pointing guides, tested-scale statement in README, first tagged release, SBOM. | | Scope creep |
| 7 (v0.2) | Connector framework (3.7) with the Microsoft 365 connector first (ADR-0002): Office 365 Management Activity API and Microsoft Graph sign-ins, directory audits, and security alerts. AI usage visibility (3.9, ADR-0015): OTLP receiver, Claude Code telemetry, AI catalog and shadow-AI view, MCP inventory and allowlist, AI watch, Anthropic connectors. Investigation (5.9, ADR-0016): AI toggle in the Search bar, facets, Suspicious presets, entity risk, investigator graph. Native UDP/TCP/TLS syslog listener. Read-only MCP server (3.8). Then Okta, Google Workspace, AWS CloudTrail. | Write-back or response actions | API throttling and latency; least-privilege app permissions |
| 8 (v0.3) | Enrichment (GeoIP/ASN, threat intel feeds such as abuse.ch, MISP, OTX; asset and identity lookups). Log integrity: hash-chained partitions and verification. Storage tiering: older Parquet to S3-compatible object storage, queried in place. Case handoff to TheHive, DFIR-IRIS, or ticketing. | Built-in case management | Enrichment freshness and licensing of feeds |
| Later | Background ingest workers. SAML SSO; CLI device-code sign-in for SSO users. Field-level masking. Scheduled reports. | | |

---

## 9. Decisions log

| # | Decision | Rationale | Date |
|---|---|---|---|
| D1 | ~~Single user v1~~ Superseded by D15 and D16. Kept: non-loopback always requires auth, no insecure flag | | 2026-10-09 |
| D2 | Parquet lake + DuckDB engine, SQLite for metadata | Retention by partition delete, portable, no writer/reader contention | 2026-10-09 |
| D3 | Target 50 GB single node, ingest behind an interface | Honest about scope, no premature workers | 2026-10-09 |
| D4 | Windows via syslog/JSON in Slice 1, native EVTX in Slice 3 using `evtx` | Covers most collectors first; one OCSF map for all transports | 2026-10-09 |
| D5 | Flattened OCSF columns + `unmapped` JSON | Query speed and Sigma mapping over nested fidelity | 2026-10-09 |
| D6 | Custom thin agent loop, no LangChain or similar | Two tools, one gate, full control of what reaches the provider | 2026-10-09 |
| D7 | pySigma with a custom DuckDB backend | Reuse the Sigma ecosystem; backend is a small subclass of the SQL backend | 2026-10-09 |
| D8 | CodeMirror 6 over Monaco | 10x smaller, enough for SQL | 2026-10-09 |
| D9 | `sqlglot` for SQL allowlisting | Real parser beats regex for statement classification | 2026-10-09 |
| D10 | Working codename Remnant, held in one config constant | Rename before release must be a one-line change | 2026-10-10 |
| D11 | Apache 2.0 license | Patent grant, matches OCSF/pySigma/DuckDB ecosystem, no friction for MSP and consultant users | 2026-10-10 |
| D12 | Cloud provider badge stays purple | Purple is reserved as the single "data is leaving the box" signal | 2026-10-10 |
| D13 | Sigma compatibility pipeline ships first, OCSF-native pipeline later | The value of Sigma is the existing community rule corpus | 2026-10-10 |
| D14 | Optional flavor names (Séance, Grimoire, Ossuary) allowed only where clarity is not hurt | Plain labels in nav, buttons, API, errors | 2026-10-10 |
| D15 | Primary deployment is a team VM; single-user on a laptop or VM is also supported; Docker optional | Real use is a security team on a VM next to the collector | 2026-10-10 |
| D16 | Multi-user in v1: individual accounts, Admin/Analyst/Auditor roles, per-user audit | Compliance requires per-user attribution; shared logins are not acceptable | 2026-10-10 |
| D17 | Per-source access via source groups, enforced server-side in the per-session events view | The lake is already partitioned by source, so the source is the natural boundary | 2026-10-10 |
| D18 | First-run setup link creates the admin account, with explicit wording on the setup page (ADR-0001) | Secure by default without manual token setup | 2026-10-10 |
| D19 | HTTPS by default off loopback, self-signed on first start, bring-your-own cert supported | Team access is always over the network | 2026-10-10 |
| D20 | SSO later, local accounts in v1 | Keeps v1 shippable | 2026-10-10 |
| D21 | CLI as a thin API client (tail, query in Slice 1; search, ask in Slice 2; TUI in Slice 6) | Quick pulls from a terminal with the same guardrails | 2026-10-10 |
| D22 | Source groups are per-installation, suggested by discovery and OCSF-category auto-labeling, never auto-granted | Every environment is different; hardcoded groups would not fit | 2026-10-10 |
| D23 | Saved searches can be scheduled; results show on a Dashboard. Schedules run saved SQL, never re-ask the LLM; run as the owner with permissions re-checked | Deterministic, auditable recurring checks | 2026-10-10 |
| D24 | Visual direction "Workspace": Sentinel/Splunk-style shell (top bar, labeled grouped nav, breadcrumbs, command bar), dark first with a full light theme, blue accent, Source Sans 3 / Source Code Pro, event detail expands inline under the row, separate Investigation page pattern with KPI cards and a plain-language finding. Supersedes the teal SOC-console brief | A polished commercial look that reads well for a whole team, not just power users | 2026-10-10 |
| D25 | NL accuracy is a measured feature: eval harness, semantic layer, verified examples, self-check loop (5.7) | The product promise depends on it; competitors are adding NL search, so accuracy is the differentiator | 2026-10-10 |
| D26 | Alert routing (email, Teams, Slack, webhook) moves into Slice 4 | A SIEM that cannot notify is a search tool | 2026-10-10 |
| D27 | Connector framework with Microsoft 365 first (Slice 7, ADR-0002) | Cloud identity and email logs are core for the target users | 2026-10-10 |
| D28 | Enrichment, log integrity, storage tiering, and case handoff in Slice 8 | Answer quality, audit defensibility, and growth beyond one disk | 2026-10-10 |
| D29 | Read-only MCP server in Slice 7 (ADR-0003); Remnant never consumes MCP servers as log sources | Lets teams query logs from the assistant they already use, without a second path around access control or the classification gate | 2026-10-10 |
| D30 | The gate treats unconfigured sources and events stored as `local_only` as local-only, requires https for cloud providers, and writes its audit row before any call | Fails closed when configuration and stored data disagree, or when the audit cannot be written | 2026-10-10 |
| D31 | Access defaults per ADR-0004: admins see all sources; ungrouped sources and ungrouped users see nothing; invite links; disable, never delete; the last admin is protected | Deny by default, attributable forever | 2026-10-10 |
| D32 | Sigma per ADR-0006: rules imported by an admin from a folder as pinned snapshots (none bundled, none fetched); a rule runs only on sources whose template declares a matching logsource; fields without a column read from `unmapped`; case-insensitive; rule author and title on every match (DRL 1.1) | Local-first, fewer false positives, license compliance | 2026-10-10 |
| D33 | Alert routing per ADR-0007: admin-managed targets (email, Teams Workflows, Slack, webhook) with encrypted write-only secrets; summary-only alerts with a link back; alerts on flagged schedule runs, rule schedule matches, and self-pauses, never on on-demand runs; vendor host checks, pinned resolution, no redirects, metadata ranges refused, `http` only to private or loopback webhooks; HMAC-signed webhooks; 3 retries with visible failures | Keeps log content and attacker-written text out of chat and mail, limits SSRF, and makes silent alert failures visible | 2026-10-11 |
| D34 | Search and Overview per ADR-0008: Ask is a tab of the Search page (Run copies the SQL into the editor and runs it; nothing runs without a click); a read-only Overview page is the landing page, built through the per-session view, one audit row per load | Asking in plain English is a way to search, not a separate tool; a home page shows whether ingest, detections, and alerts are healthy | 2026-10-11 |
| D35 | Simple search per ADR-0009: a Search tab whose Kibana/Lucene-style text is compiled to SQL on the server without a model (names from the schema, aliases, and the Sigma field map only; values bound as parameters; wildcards as escaped `ILIKE`); Kusto KQL and SPL go through Ask; counts by Top values clicks; Simple is the first-time default tab | Searching works with no SQL and no AI provider, and typed or clicked text never becomes SQL text | 2026-10-11 |
| D36 | Redaction per ADR-0010 as reviewed: off by default, because marking a source `cloud_allowed` is the explicit consent to send real log content; available per provider as an opt-in (columns and raw text, 8-hex HMAC tokens, per-call reverse map, counts audited) | Logs leave only by explicit choice, and then as they are; teams that want tokens can have them | 2026-10-11 |
| D37 | Grafana Loki as a pull source per ADR-0011, built ahead of Slice 7 as the first connector: label selector plus line filters, 30 s polling with a lag, checkpoint by timestamp and line hash, 24 h back-fill by default, webhook address rules, encrypted credentials | Lets a team try the product on logs it already collects, with no new plumbing | 2026-10-11 |
| D75 | Interface fixes from the overnight QA run (2026-10-21): the Setup checklist's core steps include collecting AI telemetry, reviewing AI services, and turning on the AI watch; the AI calls detail shows the provider name and chain hash; the Overview axis shows every 6 hours on a phone; a user with no readable sources is told so instead of being asked to add one; the AI usage header counts Claude Code users by that name and says when there is nothing earlier to compare with; the README diagram shows the optional model and the read-only MCP path |
| D76 | Loki stream labels stand in for a stripped syslog header: when a line has no complete header of its own, an envelope (`rfc: labels`) is built from the stream's labels (`hostname`/`host`, `app_name`/`appname`/`program`/`service_name`, `proc_id`/`pid`, `severity`/`level`, `facility`; per-source `label_map`), so Automatic routing and templates work on Loki data. A real header in the line wins, nothing is guessed from a line without one, and the leading space a receiver leaves is ignored for matching and parsing only; `raw` is unchanged. `linux_sshd` also matches `sshd-session` and `sshd-auth` | First install on real Loki data (2026-10-21): every one of ~40,000 Linux lines and ~8,900 firewall lines in 24 hours went to the generic parser | 2026-10-21 |
| D77 | Trusted proxies (ADR-0027): `server.trusted_proxies`, IPs and CIDRs, default empty. Only when the TCP peer is listed is `X-Forwarded-For` read, walked from the right, and the first untrusted address becomes the client address for the login limiter, audit rows, and request logs. One ASGI middleware rewrites the client address; `X-Forwarded-Proto` and `Host` are not trusted. Invalid entries and catch-all ranges refuse to start; the effective list is logged at startup | First install behind an HA nginx pair (2026-10-21): every user shared the proxy's address, so one person's failed logins locked out everyone | 2026-10-21 |
| D78 | Model queue (ADR-0028): one queue per provider in the gate around each model call, `max_concurrent` (1 to 16; default 1 for local, none for cloud) and `wait_budget_s` (10 to 600, default 120) per provider. Busy answers (503, 429, "busy", or a refused connection from a server that answered a health check in the last 10 minutes) are retried with backoff and Retry-After inside the budget; then `provider_busy` (HTTP 503). Before each retry the provider (enabled, same address, same locality) and, for cloud, the classification are checked again on the same row; cloud providers are not retried unless `max_concurrent` is set. A closed request leaves the queue (`cancelled`). The health check takes no slot and reports Busy, not Down. `llm_calls` records `queue_wait_ms` and `busy_retries` (outside the chain hash) | First install with a single-request Ollama host (2026-10-21): a busy server read as a provider failure, and nothing stopped two requests at once | 2026-10-21 |
| D79 | Query threads (install trial, 2026-10-21): a DuckDB connection sizes its worker threads from the core count the OS reports, which inside an LXC is the host's, and `SET threads` afterwards starts more. Connections now open with `threads` and `memory_limit` set at creation. `server.query_threads` (0: usable CPUs from affinity and the cgroup CPU quota, at most 4) and `server.max_concurrent_queries` (0: 4) bound them; a query that waits its timeout for a slot gets 503 `busy` with Retry-After. glibc malloc arenas are capped at 4 unless `MALLOC_ARENA_MAX` is set (the startup line names which), because under the address-space cap a burst failed to start a worker thread and left the request hanging (see D80). A failure to start a thread returns 503 `busy` with a request id; the server recovers on its own once threads can start again (tested). The startup log prints the per-query threads, the limit, and the peak. |
| D80 | Process memory is enforced by the service manager, not RLIMIT_AS (owner, 2026-10-21; supersedes the address-space part of D58). The install trial showed `server.memory_limit_mb` 4096 applied as a 4 GB address-space cap, and bursts of "can't start new thread" from host-core DuckDB threads, thread stacks, and glibc arenas: address space counts reservations, not use, so the cap fails threads while memory is free and leaves requests hanging. Now `memory_limit_mb` is a budget (default 75% of detected memory) that sizes query memory: DuckDB `memory_limit` per query is budget / (`max_concurrent_queries` + 1), so every allowed query fits with a share left for ingest. The process limit is systemd `MemoryHigh=` / `MemoryMax=` in the team-VM unit (absolute sizes, 6G / 7G for 8 GB, since inside an LXC a percentage can be of the host's memory; percentages only on full VMs and bare metal; `systemctl show -p MemoryMax` checks it) and `mem_limit` (`APP_MEM_LIMIT`) in Compose; past MemoryMax the service is ended and restarted instead of hanging. `server.address_space_cap` (default false) restores the old cap, with headroom for thread stacks (8 MB per thread at the computed peak plus 256 MB). |
| D81 | Non-usage catalog kind (install trial, 2026-10-21): vendor hosts that other websites load, such as ad and measurement tags (`bzr.openai.com`, `bzrcdn.openai.com`), were counted as ChatGPT use. Catalog entries can have `kind: non_usage`; their domains are longer than the vendor's, so they win the longest-match, and their matches are then left out of service use, the AI watch, the change comparison, and the investigator's AI flow. The AI usage page lists them apart under "Not counted as AI use"; admins can add their own with that kind. |
| D82 | Dashboard panels (install trial, 2026-10-21): fixed narrow panels hid useful columns behind a sideways scrollbar. Each panel is a third, a half, or the full width (schedules `panel_width`, migration 43), set by the owner or an admin and seen by everyone; a panel shows the first 3, 5, or 10 columns for its width with "Showing N of M columns", truncates long values with the full text on hover, and opens the full result in Search from any row (a rule's row opens that event). A result whose rows are a label and a number can be shown as bars instead (`panel_view`), label and count on one shared scale. |
| D83 | Landing page (ADR-0031, owner, 2026-10-21; supersedes the landing part of D34): Dashboard is first in the nav (General) and leaves Detect; `/`, the product mark, and sign-in open the Dashboard when the viewer sees at least one panel, Overview otherwise or when the list cannot be loaded; unknown paths still open Overview. The Dashboard opens with a one-line health strip from Overview's data (sources with errors, quiet sources, paused schedules, failing alert targets) and a link to Overview. A merged Home page is in the backlog |
| D84 | Parser changes and saved searches (install trial F36): after DNS lines moved from the generic parser to `dns_bind`, `message` no longer held the whole line and searches using `message LIKE` returned zero with no warning. A schedule run that returns zero when its last run with rows returned some compares, for the sources it read, the templates seen since that earlier run's start with those in this run's range (one grouped query, as the owner, only on a drop to zero); a new template on a source is recorded on the run (`parser_change`, migration 44) and shown on the Dashboard panel: "Parser changed for X at T (old to new). Searches on message may no longer match: use raw or parsed fields." Not a flag: no alert. `docs/searching.md` recommends `raw` or parsed columns for text matching, never `message`. A later Ask prompt version should prefer `raw` too (needs the accuracy suite; backlog) |
| D85 | Event time zones (install trial, 2026-10-21): Palo Alto templates read Generated Time (the firewall's local time, no zone) as UTC unless the source's zone was set, so a Pacific firewall's events landed 7 hours early. The Palo Alto templates (1.1.0) take `time` from the high-resolution timestamp with its UTC offset when present (found by pattern among the trailing fields, since its position varies by release; the PAN-OS 9.1 placeholder year 1969 is ignored), else Generated Time in the source's zone. Every template's zone-less times (transforms and mapped strings, not only RFC 3164 headers) use the source's zone (tested for every starter template); an ambiguous local time at the end of daylight saving is read as the first occurrence. A source's zone can be changed (`PATCH /api/sources/{id}` `timezone`, audited `source.timezone`); only new lines use it. Ingest keeps the last 300 `time_observed - time` differences per source; when they are steady (10th to 90th percentile within 10 minutes), at least 50 minutes, and within 5 minutes of a whole or half hour, Sources and Health say "Event times look N hours early (or late); check this source's time zone". Stored events keep their times; re-parsing from `raw` is in the backlog |
| D86 | Editing saved searches and schedules (install trial F37): Saved searches has Edit for your own searches (opens it in Search, Save changes updates it). Schedules has Edit (owner or admin): name, when, range, flag, alerts, sharing, and what it runs (`kind`, `target_id`, `params` on `PATCH /api/schedules/{id}`, checked as the owner like a new schedule). Run history is kept. A change to what it runs, its parameters, or its range is noted on the schedule (`definition_change`, migration 45) and recorded on the next run, shown on Schedules and the Dashboard ("Changed: Now runs the saved search X; Range changed from last 1 day to last 1 hour"). Editing your own saved search updates your own running schedules of it at once (audited `schedule.update` with the change); other people's schedules of it still pause until they review and resume, which also notes the change |
| D87 | Endpoint agent hardening (overnight brief): the generated collector config keeps read positions (Windows event log bookmarks) and the sending queue on disk, compacts it at start, and retries without a deadline (`max_elapsed_time: 0`, up to 20,000 queued batches), so laptops off the VPN buffer and send on reconnect. `GET /api/sources/{id}/agent-config?server_name=` adds `tls.server_name_override` for agents that connect by address to a certificate issued for a name (validated hostname, audited). Sysmon event 22 maps to DNS Activity in `windows_evtx` 1.1.0 (`QueryName` to `dst_endpoint_hostname`), so endpoint DNS reaches AI usage; other Sysmon events stay unmapped. The install guide covers split-tunnel VPNs and Sysmon DNS |
| D88 | Small UI items (install trial): F40, when API calls stop reaching the server (a network error, or a 502, 504, or 503 that is not the server's own "busy"), a banner under the top bar says "Can't reach the server. Showing data from HH:MM. Retrying in the background." Pages keep what they last loaded; the next answer clears it. F27, Add source offers the Loki address existing Loki sources use (the sign-in is not copied) |
| D89 | Add to dashboard (docs/ux-next-click.md part c, owner brief 2026-10-22): one step from a result to a Dashboard panel. Search has **Add to dashboard** (an unsaved query is saved first with the Save form; an open search is used as is when unchanged) and Saved searches has it per row. It creates the schedule with defaults (hourly, last 24 hours, private, a third wide), starts the panel as bars when the current result is a label and a count, and runs it once so the panel fills at once; Change opens the full schedule form. Schedules still run saved searches (SPEC 5.5), so nothing about what runs or with whose access changes |
| D90 | Search history (docs/ux-next-click.md part f, owner request 2026-10-22): **New search** in the Search command bar resets the page (closes the open saved search, clears both editors, last 24 hours, Simple tab) and asks first when edits are neither saved nor run. Each run records the tab and query, or the saved search id and parameter values, plus the time range in the address fragment (never the query string, so search text stays out of reverse proxy and SSO access logs; browser history is the remaining exposure, docs/searching.md), so Back and Forward step through earlier searches and the address can be bookmarked or shared; the server still scopes every run to the reader's own sources, so a shared address reveals nothing new. Queries over 4,000 characters are left out of the address. **Recent searches** (last 10 runs) sit at the top of Open, kept in browser storage only. The page labels its state "Unsaved search" or "Open: name" |
| D91 | Invite, reset, and setup links behind forward-auth (owner report 2026-10-22): the one-time code stays in the fragment (out of proxy and SSO logs). A forward-auth login redirect drops the fragment, so a page opened without a code says "This link lost its code during sign-in. Open the invite link again now that you're signed in" instead of a bare failure; the setup page says the same. The Users page's link panel explains it and offers Copy message with the note. Visits without a code, wrong codes, rejected passwords, and abandoned single sign-on starts never spend a link (tested); docs/install/tls.md explains it |
| D92 | Microsoft 365 Test connection and journal (install finding F41): Test checks the audit API by listing the tenant's subscriptions (read only, works on a new app) and **never starts a subscription**, because that is a change in the tenant; the source starts them on its first run. A missing subscription reads "Works. No subscription yet for ...; it starts when the source is added." Management Activity API errors show Microsoft's AF code with a plain hint for the common ones and Microsoft's message otherwise; unknown replies show the first 200 characters. A subscription found missing or turned off (AF20022, AF20023) during a pull is started again. Every API connector logs `connector_notice`, `connector_pulled`, `connector_feed_failed`, and `connector_failed` with the source id, never event content. First-run history for M365 defaults to 168 hours (F43) |
| D93 | Change retention and connector settings after a source is added (install finding F44): **Change** next to Retention (1 to 3650 days, applied by the nightly job, audited `source.retention_change` with old and new value; a shorter value warns that older days go on the next run) and **Edit settings** for API and Loki sources (M365 feeds and first-run hours, Anthropic feeds and days, Loki query and hours; audited `source.settings_change` with only what changed). The stored credential is kept. Settings that go with the credential (tenant, app, cloud, sign-in method, key type, Loki address and sign-in) are refused with a pointer to Replace credentials or a new source |
| D94 | AI usage at scale (install finding F46): the Services query matches catalog domains once per distinct host, reduces events to one row per service, person, machine, address, and hour inside DuckDB, and joins the who-had-this-address lookup to that small result; nothing holds a row per event. Queries spill to `<data>/tmp/duckdb` (emptied at start) instead of DuckDB's default `.tmp` in the working directory, which read-only containers cannot write. A memory failure has its own code (`query_memory`); AI usage then shows the last 24 hours with "Showing the last 24 hours instead." Reviewed and left as they are: MCP servers and Claude usage (read only telemetry templates), Agents and Overview volume (small groups). A scale test runs 30 days of busy DNS within a 256 MB share without spilling; the full 300k a day for 30 days runs with `-m scale`. A daily rollup table is in the backlog, not needed for these sizes |
| D95 | Left nav order (install finding F48): General (Dashboard, Overview), Investigate, Detect, AI, System (Health), Settings pinned at the foot. Health's collectors tab is **Endpoint agents** (URL `#agents` unchanged); **Agents** means AI agents only. Role hiding unchanged. Whether Overview keeps a slot is open: proposed in ADR-0034 |
| D96 | Dashboards at scale (ADR-0034, accepted 2026-10-22): a dashboard object with named, personal or shared dashboards; panels with section, order, size (tile, third, half, full), headline value and label; a Needs attention strip with audited Acknowledge. Overview folds into Health > Sources and the Needs attention strip after it lands. Supersedes SPEC 5.5's "no separate dashboard object yet" |
| D97 | AI Watch and the AI rollup (ADR-0035, accepted 2026-10-22): an hourly AI rollup per source built by the compaction job, read through a per-session view with the same source access and `local_only` handling as `events`; AI Watch at the top of the Dashboard (KPIs, review queue, 30-day chart, top services); review queue actions admin only and audited |
| D98 | Query library (ADR-0033, accepted 2026-10-22): shipped packs in `library/<pack>/`, Library on Search, Add a pack on the Dashboard, every query tested on template fixtures in CI. `m365_management_activity` removes a trailing period from `message` so queries match operation names exactly |
| D99 | Hooks plugin built (ADR-0026 amendment, owner 2026-10-22): async observe-only command hooks for session start, prompt submit, before and after each tool call, and stop; one `sh` script; metadata by default, content only when the source keeps it; pilot list; server address and a new source token written at download (`POST /api/sources/{id}/claude-plugin`, audited); posts to `/api/otlp/v1/logs`; `claude_hooks` template; Agents and a Sessions timeline read the records. Covered: Claude Code (terminal, IDE, desktop Code tab) and Cowork on the person's computer; not covered: chat |
| D100 | Dashboard layout (ADR-0034, owner 2026-10-22): sections are stored in their own order in `dashboard_sections` (migration 47), so an empty section exists and sections reorder without touching panels. Edit layout: drag a panel within or between sections, a **Section** list and **Earlier** / **Later** on each panel for keyboard use, and add, rename, reorder, and delete sections (a deleted section's panels move to No section). The owner or an admin changes a layout. `PUT /api/dashboards/{id}/layout` sends the whole arrangement, audited `dashboard.layout` with before and after; renames are audited `dashboard.section_rename`. DB-IP attribution (CC BY 4.0) shows once per results table as muted text and on **About and licenses**, which lists every outside data source with its license (F52) | ADR-0034, F52 |
| D101 | Live mode on Search (ADR-0036, accepted 2026-10-22): a Live toggle follows an event-row query over server-sent events through the guard and the per-session view; 2 streams per user across browser, CLI, and TUI (the refusal names the open ones and offers Stop); one administrator time limit for everyone, default 30 minutes, audited; Pause ends the server stream and Resume restarts from the last event with up to 1,000 rows of backfill; per-source freshness shown; shared links never start Live; the stream ends when access changes; audited start and stop | ADR-0036 |
| D102 | Parser change note on a schedule (F53, amends F36): shown only when the panel had rows on its last run and has none now, an administrator changed the parser of a source the run read (an audited `source.parser_change` after that run), and, for a saved search, the query returned rows from that source over the earlier run's range. The template mix shifting under Automatic is not a parser change | F53 |
| D103 | Updating a systemd install (F50): `scripts/update-systemd.sh` stops the service, pulls, rebuilds the UI, syncs packages with umask 022, runs `chmod -R a+rX` on the install folder, starts the service, and checks for the "listening on" line; `--aide` re-baselines AIDE (off by default). `app-server` starts through `app.launch`, which checks with the standard library only that the service user can read its code, packages, and web UI, and otherwise prints one line naming the file and the fix and exits 78. `release-checks` runs the script under umask 077 | F50 |
| D104 | Overview folds into Health (F55; ADR-0034 rows 11 to 16): KPI strip (events with change against a usual day, sources healthy with gaps and longest wait, needs attention, alert delivery for admins), a status line for detections, paused schedules, and delivery, and Health > Sources as one row per source with an hourly area sparkline in local time, 24 h total, rate per minute (received in the last 15 minutes), and last received. A gap is 2 or more empty complete hours, or a silence until now, from a source that sent in at least 75% of the other complete hours; it needs no history and is written out in words. A source with no events in 24 hours or with a gap is not counted healthy. The Overview page and its heatmap are removed; `/overview` opens Health > Sources | F55, ADR-0034 |
| D105 | Scheduling rules in bulk (F58): **Schedule selected** on Detection rules creates one schedule per selected enabled rule from one form (how often, range, alert targets), skipping disabled rules and rules the user already schedules. `POST /api/schedules` takes `add_panel` (default true); the bulk form sends false unless the user asks for panels. Each schedule is audited `schedule.create` as before | F58 |
| D106 | Health tabs and the Events comparison (F59, F60): **Sources** lists every source that brings events, read or pulled (files, syslog, OpenTelemetry, Loki, Microsoft 365, Anthropic), with the D104 rows; **Enrichment feeds** lists GeoIP and threat intel feeds, each judged by its own update interval. The Events tile compares with a usual day only after 7 full days of history, only over sources with those 7 days; newer sources are left out and counted ("leaving out 1 new source"); before that it says "Not enough history yet (N of 7 days)" | F59, F60 |
| D109 | Pivot links (product pass step 2): every IP, user, host, and AI service value in the UI links to its Investigations page, addressed in the URL fragment (`#ip=`, `#user=`, `#host=`, `#service=`) so Back and shared links work and the value never reaches server or proxy logs; one component (`EntityLink`) decides by column name. Search result rows are focusable rows rather than buttons so values inside can be links; the one-shot "Investigate" handoff is replaced by the address. (D107 and D108 are kept for ADR-0029 and ADR-0030) | Product pass, docs/ux/journeys.md |
| D110 | Entity summary (product pass step 2): `GET /api/entities/summary?kind=&value=` returns, over the caller's view through the guard, the event count, sign-in attempts, succeeded and failed (OCSF Authentication 3002 with `status_id`), distinct users, hosts, and addresses, first and last seen, sources, up to 20 activity groups by outcome, class, user, and target with one real example line and its Search SQL, up to 20 hosts and users touched, and GeoIP country and network for an address. Audited `investigate.summary` with `sources_in_scope`. The page leads with a finding sentence built from these numbers | Owner critique, docs/ux/journeys.md journey 3 |
| D111 | Daily AI rollup built (ADR-0035 Part 1): after each compaction, every closed UTC day of every source is reduced to AI usage's hourly rows (service, person, machine, address, device, hour, count, first and last) with the source and its classification, written to `<data>/rollup/ai/source=<id>/day=<date>/part-0.parquet` with a manifest of the catalog domains and the day's event files. A day is rebuilt when either changes (late events, compaction, catalog domains), newest first, at most 60 days per run; removed when its source day is removed. Reads use an `ai_rollup` view built per query from the caller's sources like `events`, reachable only from server-built SQL (user SQL gets "Unknown table"). AI usage > Services reads closed days from it for ranges of 2 days or more and the rest from events, with the same answer. Not in the integrity ledger (derived) | ADR-0035 |
| D112 | Navigation by task and one Close (ADR-0037, accepted 2026-10-22): nav is Dashboard, Alerts, Investigate, AI usage, Health, Detect, Settings; the top of the Dashboard is the morning answer (sentence, Needs you, Sources, New); one `alert_items` queue for flagged schedule runs, rule matches, AI Watch items, and gaps on sources with Alert if quiet on, closed with a reason (note required for False positive and Needs follow-up), reopenable, audited; mute is admin only, at most 30 days, expires on its own, shown as "N muted"; alert messages link to `/alerts#item=`, source names to `/health#source=`; Alert if quiet is on by default for new sources (60 min, 3 h for Microsoft 365 and API connectors) | One queue and one verb for everything that fires; the owner's answers on label, mute, and gaps | 2026-10-22 |
| D113 | AI Watch review items (ADR-0035 Part 2 queue, built on ADR-0037): every AI watch check raises `ai_watch` alert items whether or not its messages are on (a service or MCP server not approved or not reviewed yet, sensitive data per person and day, agent changes), with a High or Medium severity; Close replaces Dismiss; Approve and Not approved on an item use the admin-only review endpoints and close its items with that decision; items carry their sources for the Restricted rule | One queue; the watch's on switch now means messages, not detection | 2026-10-22 |
| D114 | AI Watch on the Dashboard (ADR-0035 rows 10, 12, 13): `GET /api/ai/watch/summary?days=7|30` on the caller's view: unapproved services, users of unapproved AI (a person, else the device or address), new agents and MCP servers (from AI Watch items the viewer may read), app consent grants (M365 `Consent to application`), and Claude Code sensitive-data signals, each against the previous period of the same length; AI use per UTC day for 30 days by review status from the rollup; top 10 services. Telemetry and M365 sources are known by kind or template, so a file read with those templates counts; a missing source is named, an unreadable one is Restricted. Audited `ai.view` | One view of AI use without a saved search | 2026-10-22 |
| D115 | People and devices are never one number (owner, 2026-10-22): a count of people counts named people only; devices or addresses with no person matched are a separate line ("3 more devices not matched to a person", linked to the list). Applies to AI Watch's people card (amends D114's "users"), AI Watch review items ("2 people: ...; 3 devices not matched to a person: ..."), and the AI flow's first lane (People, Addresses, Devices not matched to a person). ADR-0029 will move most devices into people | A device is not a person; mixing them hides how many people actually use AI | 2026-10-22 |
| D116 | AI Watch review state and first seen (owner, 2026-10-23; amends D113, D114): hourly, one rule for everything AI Watch tracks (owner, 2026-10-23): every AI service and MCP server in use in the last 7 days that is not approved, every agent in use (Close is its decision), and every person and day with sensitive-data signals gets an `ai_watch` item if it has none ("AI service not reviewed: X" or "not approved"), so use from before the watch's cursor is never skipped; an item closed by a person or a decision stays closed. "New in 24 hours" is first seen in the data (not seen in the 30 days before), from the summary API's `new` list, never an item's creation or a review decision | An unreviewed service leaves an open item until someone decides; a decision is not a sighting | 2026-10-23 |
| D117 | AI Watch at scale (install finding F63, amends D94 and D111): a query with a time range opens only the lake's day folders it touches (the writer files events by UTC day), and AI use queries leave the days the rollup covers out of `events` altogether (`skip_days`) instead of filtering them row by row, so closed days are read from the rollup and only today and unbuilt days from events; a range with a start and no end uses the rollup too. Each rollup day's manifest records when every service, MCP server, and agent was first seen that day (the first-seen index); days built before it get it without a rebuild. New in 24 hours is first seen in the summary's own rows or the index, so the summary runs one events query for services (top services come from the same rows). MCP servers, agents, and the signal cards still read events, but only telemetry and Microsoft 365 days in range. People are resolved on the aggregated rows (D94), never per event. A memory failure is 503 `query_memory` (a server limit, not a bad request), logged at WARN with the request id and the query's name; Dashboard sections and Alerts that fail to load say so in place with Retry. The `-m scale` test (300k DNS events a day for 30 days plus DHCP and sign-ins, the default share of a 4 GB server) requires the summary within 10 s: 33 s and 43 s before, 1.2 s after on 2 vCPU |
| D118 | Hooks plugin per platform (ADR-0026 amendment 2026-10-29, owner): one plugin each for Windows (PowerShell 5.1 `send.ps1`, `-NoProfile`, exec form, no Git Bash), macOS and Linux (`send.sh`), and Cowork (Node, after a reachability check), each gated so a session is sent once; a machine-wide managed config (`siem-claude-hooks/hooks.conf`, admin-only write, deployed by endpoint management) wins over the bundled config, which is then not read at all, and environment variables change the destination only with `DEV_ENV_OVERRIDE=1` in that file; the Claude account email (managed config, then `CLAUDE_CODE_USER_EMAIL`, then `oauthAccount.emailAddress` from `.claude.json`) is sent apart from the OS user; PostToolUseFailure and SessionEnd added, Stop is a turn end; every script prints `{}` and exits 0 within 2 s and never reads the receiver's response into output; failed sends counted and reported as dropped on Health; `CA_FILE`, no skip-verify; content capped at 4 KB first and last per field and secrets masked on the receiver; optional Authenticode-signed script run with AllSigned |
| D119 | Claude account tiers (ADR-0030 amendment 2026-10-29, owner; amends C2 for Claude Code and Cowork only): a company-domain account email reported by the hooks plugin is Company, confirmed with a matching Entra sign-in, Company, reported without a sign-in source, or Company, not confirmed when a sign-in source has none (approved, flagged, alert off by default); an email outside the company domains is Personal Claude account; no email is Not checked, never company; company domains are the ADR-0018 organization email domains; the email clears hook records and `api.anthropic.com` use from that device, while `claude.ai` still needs Entra; the Anthropic usage or compliance report corroborates |
| D120 | Hooks plugin offline queue (ADR-0026 amendment 2026-10-29 b, owner): a record that cannot be sent waits in `${CLAUDE_PLUGIN_DATA}/spool` (one file per record, metadata only, at most 10,000 records and 7 days, oldest dropped first and counted as lost) and goes out after the next record that reaches the server, oldest first, 50 to a request, for at most 15 s in the background; every record carries `install_id` and `seq`; the server keeps the original time, shows queued, late, lost, and missing (sequence gaps per install over 8 days) per machine on Health, says "delivered N h late" on session steps, and shows a resent record once; the receiver stays off the internet; integrity comes from the sequence numbers, not the user-writable spool |
| D121 | M365 columns and release safety (F66, owner, 2026-10-29): six additive columns (`resource_name`, `resource_uid`, `resource_type`, `status_detail`, `privileges`, `metadata_correlation_uid`); the engine reads them as typed NULL from files written before they existed. A template may declare `changes:` (version, note, columns whose meaning changed); `template_versions` records the first load of each version, and Sources lists recent changes with that day and the saved and scheduled searches that filter on a changed column. There is no re-parse: stored events keep their mapping, and each release note says what changes for existing installs. New transform `find`. |
| D122 | One count per Microsoft 365 operation (F66, owner, 2026-10-29): a record reported by Graph and the Management API counts once, keyed by `metadata_correlation_uid`, else person, minute, and operation name (trailing period ignored); every M365 count uses this key (`app/ai/consents.py` first). Consents with status 2 are blocked attempts, shown apart and never in the grant count. An app with no name is named from another record of its id, else from the person's M365 sign-in at most 60 seconds before. |
| D123 | Areas with tabs and one page grammar (ADR-0038, owner, 2026-10-29): the rail lists 7 areas (Dashboard, Alerts, Investigate, AI usage, Agents, Microsoft 365, Health) plus Settings; tabs in the page header with real URLs `/<area>/<tab>` and redirects from old paths; Detect folds into Alerts; one time window per page; KPI strip with neutral delta pills; outcome bars never red for routine failures; one card-state component; list-detail only for queues; AI usage Review is the Alerts queue filtered to AI Watch; Investigate tabs Search, People & devices, Saved searches; Microsoft 365 approved countries is an admin list, empty by default. |
| D124 | Who had an address on closed days (owner, 2026-10-29, after #276 ran out of memory): the AI rollup keeps a per-day identity file (`ident.parquet`: logon, User-ID, VPN, DHCP, and sign-in-on-a-machine observations, first and last of each mapping per hour), read through the server-only `ai_ident` view; AI use queries join it to the rollup and never open closed days' events. Days built before it are re-checked each maintenance tick (20 s budget, logged `rollup.recheck.*`); until then pages show "Rebuilding people for N of M days" and never fail. |
| D125 | Grouped rail and centered search per ADR-0038 edit 10 (amends D52): a 240px rail in four collapsible groups (Monitor, Investigate, AI, System) listing every sub-page, Microsoft 365 under Monitor; a wide centered search in the top bar that finds pages and, once built, entities; one freshness line in the top bar; per-user density in the user menu (comfortable from 1440px by default); one time window per Dashboard page; "external" means outside the Internal networks list, which takes private and public entries and defaults to the private ranges | Owner feedback from a 2000px monitor (2026-10-30): the rail was cramped into a corner, the search was tucked away, and two freshness lines disagreed | 2026-10-30 |
| D107 | Who had an address (ADR-0029, accepted 2026-10-23 with conditions): DHCP leases and VPN and logon sessions as intervals with ends and labelled caps; matches chain (DHCP to device, sign-in on that device to person) and each person shown says how it was matched and links to the evidence; an admin can correct a match (audited, sticks); names follow source access and the View people in AI usage permission (admins by default); stored alert text carries references, not names; unmatched devices stay apart (D115) | Every name checkable and correctable; least privilege by default | 2026-10-23 |
| D108 | Approved for company accounts (ADR-0030, accepted 2026-10-23 with conditions): use is approved only with an Entra / M365 company sign-in to the app by the same person (and device when the sign-in has a device id) within a per-service window that defaults to the app's session lifetime; otherwise Possible personal account (per person or unmatched device, per service, per day); Can't verify company accounts where the evidence cannot exist; both count as unapproved on AI Watch; report-only until an admin turns on alerts; non-interactive sign-ins as an optional beta feed filtered to the evidence apps; review decisions never change on upgrade (one-click notice) | Company-workspace-only policy without proxy decryption, without flagging every SSO user | 2026-10-23 |
| D74 | Smaller fixes from the overnight QA run (2026-10-21): Health and Sources take each source's newest stored event at start; AI usage makes no New / No longer seen comparison when the earlier period holds no AI data at all; the MCP audit row counts rows actually sent; a new AI agent is alerted once, like a change; rule import names the YAML error and its line; the Verify now note says 30 seconds; version 0.3.0 |
| D73 | AI review and matching fixes (overnight QA, 2026-10-21): an MCP rule can be any server name as configs write it (spaces included; no control characters; `*` only at the end for a prefix); MCP People counts one person once across names using the identity map; threat intel domains match the destination host the way AI usage reads it (DNS query names and proxy URLs in `unmapped`); Sigma `query` and `QueryName` read DNS template fields |
| D72 | Telemetry values (overnight QA, 2026-10-21): non-finite numbers are dropped at the receiver; a cost point below 0 or above 1,000,000 USD is dropped, and cost and token sums ignore such values already stored; timestamps more than a day in the future fall back to the time observed or received; the sensitive-data scan reads values before the 8 KB storage cut, and for values over 64 KB reads the first 48 KB and last 16 KB; each AI usage tab renders behind an error boundary |
| D71 | Positioning (owner, 2026-10-20): lead with AI usage monitoring ("See the AI your company actually uses"); the log platform is the foundation. Public text describes the product on its own terms, with no comparisons to other products. Vendors the product integrates with or tracks are named as usual |
| D70 | Rail order (owner, 2026-10-20): main rail General (Overview, Health), **AI** (AI usage), Investigate (Search, Investigations, Saved searches), Detect (Detection rules, Schedules, Dashboard). Settings in setup order: Start here (Setup checklist), Data (Sources and connectors, Templates, Enrichment, Identities), Access (Users and access), AI (AI providers, MCP server), Alerts (Alert targets), Records (Audit log). Settings still opens on Sources. Supersedes the grouping in D44; URLs unchanged |
| D69 | Integrity fixes from the first upgraded install (2026-10-20): a seal records the ledger entry its checked head belongs to, not the ledger length when it is stored, so writes during a check no longer fail the next one; seals are compared with the chains by hash; the start-up baseline records every unrecorded lake file until the first baseline or seal, so ingest writing first no longer turns older files into adopted ones |
| D68 | Claude hooks plugin per ADR-0026: session start, prompt submit, before and after each tool call, and stop are sent as OTLP log records to an existing OpenTelemetry source; observe only (never blocks, 2-second timeout, always exits 0); metadata by default, content only with the source's keep-content setting, capped at 8 KB; destination fixed at install; each record has a `role` (user, tool_call, tool_result, session) |
| D67 | Reports per ADR-0025: Executive (2 pages at most) and Detailed, for last month by default or any range up to 366 days, each figure compared with the period before; numbers only from the engine through the guard in the owner's scope; PDF rendered on the server (WeasyPrint) plus an in-app preview and a CSV of figures; optional AI summary from aggregates only, citing figure keys; monthly or weekly schedules as the owner, PDF attached for email targets. Built in order: executive with custom range, detailed, schedule and delivery, AI summary. Answers Q2 |
| D66 | AI usage compares the range with the period of the same length just before it (owner, 2026-10-20): services and MCP servers seen in the range but not before are marked **New**; those seen before but not in the range are listed under **No longer seen** with their review status and last sighting, approved ones first, so access nobody uses can be reviewed. Read as the viewer over the same sources; none for All time. Display only: no alert. Empty states link to Sources. |
| D65 | Overview event volume is a heatmap (owner, 2026-10-20): one row per source, a cell per hour, shaded against that source's busiest hour. Each hour is compared with the same hour on up to 7 earlier days (median, once a source has 3 days of history): **busy** at 3 times typical and 20 more events, outlined; **quiet** when typical is 20 or more and the hour has a quarter or less, striped (never the unfinished hour). Sources with marks are listed first. A cell opens that source and hour in Search. Read as the viewer through the guard, like the rest of the Overview. Display only: no alert. |
| D64 | Integrity hardening after an independent review: searches read only `source=*/day=*/part-*.parquet` and other `.parquet` files under the lake are reported as stray; files dated in the future are judged at once; compaction, retention, and the sweep keep any file whose content no longer matches the ledger, and a recovery manifest is honored only when its output holds every input's event ids; each check compares the chains with the newest seal that still verifies; adopted files stay listed for 7 days; seals cannot be updated and sign their findings; ledger, audit, and AI call chain writes take the database write lock first; one verification at a time (409); feed downloads stream with the size cap and one update runs at a time | Security review of D59 to D62 (2026-10-17) | 2026-10-17 |
| D63 | Event hand-off per ADR-0024: select 1 to 100 events in Search, **Send**, choose an existing alert target, add a note. Webhooks get the events as signed JSON (raw capped at 4 KB); chat and email a short escaped list with event ids. Events re-read from the caller's view; local_only events only to targets on private addresses; audited as `handoff.send`. Native TheHive and DFIR-IRIS integrations not built | Slice 8 case handoff, slimmed by the owner; T55 | 2026-10-17 |
| D62 | Enrichment feeds per ADR-0023: DB-IP Lite country and ASN (GeoIP), abuse.ch Feodo Tracker and ThreatFox plus uploaded lists (threat intel), all looked up locally. Upload always works; automatic updates are off on a fresh install and turned on with one switch (recommended by the setup checklist): GeoIP checked daily, lists every 4 hours with conditional requests, only from a fixed host list. GeoIP shows as muted text after public addresses in results; threat intel as a `threat_intel` table in SQL, one marker on matched values, one facet group, two presets. Freshness on Settings > Enrichment and Health | Slice 8 enrichment; T53, T54 | 2026-10-17 |
| D61 | AI call records join the integrity chain: each `llm_calls` row gets `chain_seq` and `chain_hash` when it is completed (the row is frozen from then on), so the chain follows completion order and calls still in flight are not judged. Verification reports edited or removed records, and completed records with no hash after chaining started. Seals carry `llm_head` and `llm_rows`; seals made before keep verifying without them | Closes the backlog item from the gate review; T13 | 2026-10-17 |
| D60 | Slice 8 order (owner, 2026-10-17): GeoIP/ASN enrichment next, from local database files only (no IP is sent to an outside lookup service); threat intel feeds and case handoff to be explained and decided before building; object-storage tiering deferred to the backlog because querying in place needs DuckDB external access, which the query connection keeps off (rule 7). `v0.1.0` tagged | Owner decisions after the integrity work | 2026-10-17 |
| D59 | Log integrity per ADR-0022: every lake file the product adds or removes is a row in `lake_ledger` (SHA-256, size, reason), each row hashed with the one before; files present before the feature start as `baseline`. Audit rows carry `chain_hash`. Verification runs daily (`maintenance.integrity_interval_s`) and on demand (admins): changed or missing files and a broken chain fail; files never recorded are adopted and reported as warnings; files newer than 2 minutes are left for the writer. Each run is sealed (HMAC-SHA256 under a key derived from the install key) in `integrity_seals`; failures alert chosen targets, and an optional daily seal message carries both chain heads off the server. Admins and auditors see status and download the signed JSON report on the Audit log page, Integrity tab | Slice 8 log integrity; T22, T13, T52 | 2026-10-17 |
| D58 | Query memory: the server caps its own address space at start (`server.memory_limit_mb`, default 75% of the machine or container: the smallest of `/proc/meminfo`, this process's cgroup limit, and physical RAM, since LXC containers show the host's RAM to `sysconf`; the startup line names the source), each query gets a third of that as DuckDB `memory_limit` and at most 4 threads, the guard refuses literal sizes past 100 million rows (`range`, `generate_series`) or 10 million items (`repeat`, `lpad`, `rpad`, `list_resize`), and out-of-memory becomes a failed query. Login lockout is per account and address, with a 10 times higher bar per account from any address. CLI CSV is spreadsheet-safe like the server export. Outbound address rules also refuse NAT64 and 6to4 forms and 100.100.100.200 | Second independent review (2026-10-17): one guarded query, or a prompt-injected log line steering Ask, could get the server killed for memory (T51); one address could lock any account out | 2026-10-17 |
| D57 | Security review fixes (2026-10-17, independent reviewer): syslog spool writes roll back on a short write and a damaged spool file is set aside, never resynced inside message bodies; listener memory capped at 32 MB per source; TLS handshakes only after the sender and connection checks; linear-time stream framing; MCP rejects non-finite `since_hours` and batches over 20; address lookups treat zone-less times as UTC and audit failures; lake sweep skips linked folders; Sources warns when Docker hides syslog sender addresses. Runtime dependency audits fail CI (docs/security/dependencies.md) | Findings with concrete exploit or failure paths; none reached data outside a caller's scope | 2026-10-17 |
| D56 | MCP server per ADR-0003 built as: `POST /api/mcp` (Streamable HTTP, answered as JSON, no server stream), protocol versions 2024-11-05 to 2025-11-25, no SDK dependency; settings page (off, endpoint local) admin-only and audited `mcp.settings`; per-user API token required (browser sessions refused, Origin checked); `run_query` capped at 500 rows, 2,000 characters per value, 256 KB per result, 15 s; local-only means not cloud_allowed by source setting or by any stored event, as for cloud providers; `remnant mcp` relays stdio clients through the CLI token | Smallest server that real clients accept; same scope, guard, and classification rules as every other surface | 2026-10-16 |
| D55 | Native syslog listener per ADR-0021: `kind: syslog`, one port and protocol (UDP, TCP, TLS) per source, messages spooled with their sender and read through the source's parser; private networks only unless an admin lists senders; sender fills `device_ip` when the message has none; no new ports published by default | Small sites can point devices straight at Remnant without a relay daemon, with the same parsing and `raw` guarantees as files | 2026-10-16 |
| D54 | Page tabs as left-nav sections: AI usage and Health list their tabs under the nav item while open; the tab is kept in the URL hash (`/ai#mcp`), so links, Back, and the palette open it directly. Role rules are the same as the page's | Easier jumping between AI usage views on the test install | 2026-10-16 |
| D53 | Field clicks filter in SQL and Ask mode too: the server adds the condition to the SQL on screen with sqlglot (never string pasting), the editor shows it, and it runs through the guard and audit as usual | On the test install the facet sidebar looked broken after an Ask or SQL search, where it only counted | 2026-10-16 |
| D52 | App shell: 48px top bar that stays in view; the palette opener is a compact "Jump to" button; the host badge is replaced by an optional admin-set `server.environment_label` (24 characters, letters, digits, spaces, `.()-`; served by `/api/meta` before sign-in, so nothing sensitive); Settings pinned to the foot of the left nav | Feedback from the test install: the bar looked small, the search looked like a text field, and showing the server IP added nothing the address bar does not | 2026-10-16 |
| D51 | Lake durability: part files and compaction manifests are flushed to disk before being renamed into place, and the folder after. An empty or unreadable part file (from a crash before this, or a disk fault) is moved to `data/quarantine/<source>/<day>/`, never deleted: empty files on every maintenance pass, unreadable ones at start-up and when compaction meets them. The Health page counts them | A power cut left 52 empty files on a test install, which failed every query over that day and stopped compaction and retention | 2026-10-16 |
| D50 | People behind addresses, agent identities, allowed-data labels per ADR-0020: addresses resolved at query time from successful logons, User-ID, and GlobalProtect (newest within 12 hours, per viewer scope); agents with owners and 30-day baselines; services labelled with an allowed data level. No browser extension for now | Shadow AI named by person and machine with logs already collected; deterministic and explainable | 2026-10-16 |
| D49 | Health page per ADR-0019: one page with Unhealthy, Needs attention, Paused, and Healthy counts over sources, connectors, per-machine agents, watched devices, alert targets, and schedules. Watched devices are judged by appearing in events already collected (event time capped at received time), never by connecting to them; ping and port checks are left to uptime tools | One answer to "is anything broken?" without turning the SIEM into a network monitor | 2026-10-15 |
| D48 | Investigations layout revised per ADR-0016 row 5 (owner review): a landing with an Investigate picker and a Most active table (Users, IP addresses, Hosts) replaces the left list; a chosen entity opens a full-width graph whose lanes hold titled groups (event class, MCP servers or built-in tools, AI services or other hosts, people or addresses), joined by right-angled links over a dotted canvas, with off-path cards faded and details in a side panel. The setup checklist moves from Overview to Settings, Help, Setup checklist | Closer to the data-access lane layout the owner preferred; the Overview stays about data and detections | 2026-10-15 |
| D47 | Ask prompt `ask.v5` adds follow-up rules (keep the last query's conditions; "these" means its rows; "show me", "count them", "break that down by X", "what about Y") and person-name matching (case-insensitive, email and `DOMAIN\\` forms). The server's version is the `llm.ask_prompt` setting, default `ask.v4` until the accuracy suite shows `ask.v5` at least as good on the reference local model | Analysts ask follow-ups like "ok show me all of these for Steve"; a prompt change ships only with measured accuracy | 2026-10-15 |
| D46 | Optional outbound proxy (`network.https_proxy`, credentials from the environment) and extra CA bundle per ADR-0018, used only by the fixed-host API connectors and Teams or Slack alerts; Loki, generic webhooks, SMTP, and model providers stay direct | Proxied networks can use the cloud connectors without weakening the private-address rules for admin-entered URLs | 2026-10-14 |
| D45 | One person under several names per ADR-0018: case and `DOMAIN\` always ignored; addresses in administrator-listed organization domains merge with the bare name; aliases by hand or by accepted suggestion; applied when Investigations and AI usage read, never to stored events or Search | Split names hid one person's activity and risk; merging must be explainable and reversible | 2026-10-14 |
| D44 | Left rail holds daily work (General, Investigate, Detect) and one **Settings** entry; Sources and connectors, Templates, Users and access, Audit log, AI providers, and Alert targets move to a Settings area with its own sub-nav (Data, Access, Integrations). URLs unchanged | The rail grew past a dozen items as connectors and the investigator landed; admin pages are visited rarely | 2026-10-14 |
| D43 | Optional endpoint agent per ADR-0017: the official OpenTelemetry Collector with a Remnant-generated config per agent group (an OTLP source); token read from a file; Windows event XML converted by the receiver to the `evtx` shape, journald to RFC 5424, file lines as written, so existing templates apply; no Remnant agent binary | Endpoint telemetry without a homegrown privileged agent | 2026-10-14 |
| D42 | Investigation per ADR-0016: one Search bar with an AI toggle (plain English goes to Ask; generated SQL shown, run on click) beside a SQL tab; facet sidebar with counts from a guarded subquery on the caller's view; Suspicious presets as editable Simple searches; Investigate page with entity risk (users, IPs, hosts ranked by rule matches) and an investigator graph (entity to sources, activities, targets; AI flow mode), plain SVG, 60-node cap | Analysts expect one bar, clickable field counts, and a picture of an entity's activity; all deterministic | 2026-10-14 |
| D41 | AI usage visibility per ADR-0015: AI service catalog with Approved / Not approved / Unreviewed; shadow AI from network logs by destination domain; OTLP/HTTP JSON receiver with per-source tokens that drops prompt, response, and tool content by default; Claude Code telemetry template; MCP inventory from telemetry and an endpoint script (names only, never arguments or environment); MCP allowlist; AI usage page; AI watch alerts on first sighting of anything not Approved; Anthropic usage, cost, Claude Code, analytics, and compliance activity connectors (never chat content); all `local_only` by default | Teams need to see AI use and cost like any other system, without sending what people typed anywhere | 2026-10-14 |
| D40 | Built-in quiet-source alerts per ADR-0014: an administrator sets, per source, a quiet period (5 minutes to 7 days) and alert targets; the server sends one alert when the source receives nothing for that long and one when events resume; measured on received time, kept across restarts; reads times only, never event content; settings audited | A stopped source is a detection gap that looks like a quiet network; one schedule per source did not scale and paused when its owner left | 2026-10-12 |
| D39 | Optional OIDC single sign-on per ADR-0013 (supersedes D20 for OIDC): off by default, configured on the server; one tenant's issuer only; invite first, then the Entra identity (`iss` + `sub`) is bound through the invite link; optional required Entra groups checked every sign-in; roles and source access stay in the app; with SSO on, only administrators may use a password (break-glass) | Teams can use their identity provider's MFA and conditional access without a second password, while installs with no identity provider work as before | 2026-10-11 |
| D38 | Automatic parser per ADR-0012: a source's parser can be `auto`, which routes each line to one approved template by syslog app name, then payload regex (user templates, then vendor templates, then catch-alls), then the generic parser; a routed template that fails falls back to generic. Admins can change a source's parser; only new lines use it. Default for new syslog and JSON sources | Mixed streams (a host's syslog file, a Loki selector) are the common case; one template per source left most columns empty | 2026-10-11 |

---

## 10. Open questions

| # | Question | Needed by |
|---|---|---|
| Q1 | OCSF version pin: 1.3 now, how do we handle column additions on upgrade? Proposal: additive migrations only, never rename. | Slice 1 |
| Q2 | Report drafting format: Markdown export only, or also a stored report object? | Answered by D67 (ADR-0025): stored PDF reports |
| Q3 | Should `cloud_allowed` be per source or per source plus field mask? | Slice 5 |
| Q4 | Default access for a new source: all Analysts, or Admin-only until granted? Proposal: Admin-only (deny by default), with a one-click "grant to all analysts". | Slice 2 |
| Q5 | Auditor role: can it see raw lines, or parsed fields only? | Slice 2 |
