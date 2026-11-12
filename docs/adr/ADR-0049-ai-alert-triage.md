# ADR-0049: AI alert triage

Status: **Accepted** 2026-11-09 (owner), with five review fixes recorded in section 9. Threats T79 to T86 are in SPEC 7.1. Decision rows are numbered by `assemble.py --prep` in the PR whose build item needs them.

## 1. Context

A solo or small security team spends 20 to 60 minutes pivoting on each alert: who owns the address, what the user signed in to, what the host talked to, whether this fired before. Remnant already holds every piece: Alerts (`alert_items`, ADR-0037, ADR-0043, D200), who had an address (ADR-0029, D107, ADR-0048), person facts (D197), enrichment (D62), entity risk (ADR-0016), the AI rollup, the guarded engine (rule 7), the one LLM gate (rule 2), citation checks (security rule 4), and an audit row for every call (rule 14).

Goal: an alert gets a code-built evidence pack and a suggested verdict with cited IDs in under 2 minutes, and a human decides. Agreement is measured before any more trust is given.

Non-goals: no automatic actions (never isolate, block, disable, or close); no auto-close at any confidence (Phase 3 can only produce a *proposal* for a later ADR, as an owner decision); not a chat; no cloud model by default.

## 2. Decision summary

| # | Area | Decision |
|---|---|---|
| 1 | Intake | CEF over the existing syslog listener (ADR-0021), TCP or TLS recommended. Webhook later, reusing the OTLP per-source token model |
| 2 | Evidence | Code-built pack, 7 entity-based pivots, caller's view, about 6k-token budget, works with no model; stored as element IDs and a hash, rebuilt on display |
| 3 | Verdict | 3 model verdicts plus code-only `insufficient_evidence`; word confidence; downgrade-only checks with an asymmetric bar; zero tools |
| 4 | Display | Triage section in the alert detail pane, list tag and filter, no sort or summary strip change, bulk close blocked under a verdict filter; names only for viewers with View people |
| 5 | Phase 2 | System principal `triage` with no sign-in path, events view from `engine/views.py`, admin-chosen evidence group, fair queue, budget, kill switch |
| 6 | Phase 3 | Close reasons mapped to sides, blind sample, per alert type rates with upper bounds, two trust steps, automatic demotion |
| 7 | Sizing | Targets, not hardware; triage eval set is a Phase 1 deliverable and the Phase 2 gate |

## 3. Decision detail

### 3.1 Phase 0: external alert intake

- CEF over the native syslog listener (ADR-0021). TCP or TLS recommended in the install guide; UDP documented as lossy and plain text (T50).
- A template marks a source as an alert source with `emits: alerts`. Templates with `emits: alerts` need **admin approval through the existing template flow** (ADR-0005). Alert sources map to OCSF Detection Finding (2004), the same class as Remnant's own detections.
- Required fields for alert creation: source product, external alert ID, event time, title or rule name, severity (mapped per template), at least one entity (source IP, host, or user). Optional: destination IP or host, domain or URL, description, vendor score, vendor console link, ATT&CK technique IDs.
- **Raw lines are never rejected** (rule 5). An event missing a required field is stored with a parse flag and does not create an alert.
- Dedup key: `source product + external alert ID`. Grouping and repeats follow D200 unchanged: repeats update the open item and notify only on creation or a severity rise; **a severity rise on a closed item opens a new item linked to the closed one** (no reopen, so the close and its reason stay intact).
- Per-source alert creation cap: default 100 an hour, then alert creation pauses for that source (events still ingest), shown on Health and sent to alert targets like other self-pauses (D33).
- Vendor free text (title, description, every custom string) is attacker-influenced: stored as data, rendered as text nodes, reaches a model only under `data`.

### 3.2 Phase 1: evidence pack (no model)

Pivots are chosen by the entities the alert carries, not by vendor or alert type. Each is fixed Remnant SQL through the guard, on the per-session `events` view from `engine/views.py` (rule 13): the clicking user's view in Phase 1, the `triage` principal's view in Phase 2 (3.5).

| # | Pivot | Built on | Runs when the alert has |
|---|---|---|---|
| 1 | Who had the address at alert time, with match label and evidence | ADR-0029, D107, ADR-0048 | IP |
| 2 | Person facts: recent sign-ins, usual countries and devices, MFA results | D197, Microsoft 365 facts | User (direct or from pivot 1) |
| 3 | Earlier alert items on the same entity, with close reasons and notes | `alert_items` (D112, D200) | Any entity |
| 4 | Network around the alert: top destinations, ports, domains, counts; each marked **first seen in 30 days** for the entity | Firewall and DNS sources, aggregated | IP or host |
| 5 | Threat intel and GeoIP/ASN on every IP and domain | D62 | IP or domain |
| 6 | Other rule matches on the entity in the window | Sigma matches, ADR-0016 | Any entity |
| 7 | AI use by the person or host in the window | AI rollup | User or host |

Close notes in pivot 3 are analyst free text and are treated exactly like vendor text: data under the `data` key, never instructions.

Windows (admin-configurable defaults):

| Window | Default | Used for |
|---|---|---|
| Detail | The alert's own start and end when present; otherwise alert time plus or minus 15 min | Pivots 4 and 6 detail |
| Lookback | 24 h before | Aggregates and first seen in the day |
| Baseline | 30 days | Pivot 3 history, pivot 2 baseline, pivot 4 first-seen flags |

Size: up to 50 detail events in the Explain shape (16 columns, `raw` cut at 2,000 characters); aggregates as summary rows, each with up to 3 sample event IDs; about 6k tokens (configurable). Over budget, code trims pivots 7, then 6, then 4, and the pack lists what was trimmed.

Pack IDs: every element carries a **server-assigned, opaque ID** (`event_id`, `alert:<id>`, `ident:<id>`, `ti:<id>`, `agg:<id>`). The model never mints IDs. Citation check (security rule 4) becomes "every cited ID was in the set sent".

Storage and retention: the pack is stored as **element IDs, per-element hashes, the pack hash, and the pivot parameters (windows, entities)**, never as content. The card rebuilds the pack on display from those IDs inside the viewer's scope.
- An element whose underlying data is past retention shows "Evidence aged out (retention)", and the verdict keeps that label from then on.
- An element that rebuilds with a different hash (for example an administrator corrected an identity match, D107, or an aggregate recomputes differently) shows "Changed since triage". The verdict is not recomputed.

The Triage button always builds and shows the pack. The verdict appears only when a provider is enabled (rule 1). No per-alert-type pivot profiles in Phase 1; admin-approved YAML triage profiles go to `docs/BACKLOG.md`.

**History bias rule.** Prior closures are context, not a verdict. When pivot 3 holds prior closures, the answer must say what is new this time (`whats_new`, from the first-seen flags) before it may suggest `likely_benign`; code enforces this (3.3).

### 3.3 Phase 1: verdict

Model call: purpose `triage`, prompt `triage.v1` in `llm/prompts/`, **zero tools** (rule 3, amended to list `triage`), pack under `data` with every pack source declared, so `local_only` blocks a cloud provider and redaction applies as for Explain.

| Verdict | Set by |
|---|---|
| `likely_benign` | Model |
| `needs_review` | Model, or a code downgrade |
| `likely_malicious` | Model |
| `insufficient_evidence` | Code only, before any model call (pack too thin: no entity resolved, no events, or everything trimmed) |

Confidence: `low`, `medium`, `high` (no percentage).

Answer schema (Pydantic, extra keys refused, response cap as security rule 3):

| Field | Rules |
|---|---|
| `verdict` | One of the 3 model values |
| `confidence` | low, medium, high |
| `summary` | 1 sentence, at most 200 characters, cites at least 1 ID |
| `reasons[]` | 1 to 6 of `{text <= 300, ids[], stance: supports or against}` |
| `whats_new[]` | `{text, ids[]}`; required when the pack holds prior closures |
| `missing[]` | 0 to 3 short items: evidence that would change the verdict |
| `next_step` | 1 suggested human check, at most 200 characters, shown as text, never parsed (rule 4) |

Code checks (after validation; **downgrade only, never upgrade; never change or hide the alert's own severity**):

| Condition | Result |
|---|---|
| Citation check fails | `needs_review`; uncited items marked unverified |
| `likely_benign` with fewer than 2 verified `supports` reasons | `needs_review` |
| `likely_malicious` with fewer than 1 verified `supports` reason | `needs_review` |
| Prior closures exist and `whats_new` is empty | `needs_review` |
| `likely_benign` where every `supports` reason cites only `alert:` IDs | `needs_review` |
| No `against` reasons | Kept; card says "No counter-evidence listed" |

The bar is asymmetric on purpose: a false benign costs more, and the alerts that matter should not be slowed down.

Visibility (Option A): the verdict is stored with its **evidence scope**: the pack's sources and whether Identities were used.
- Viewers who can read every source in scope, and, when Identities were used, hold the **View people** permission (ADR-0048 slice 0), see the verdict text.
- Everyone else, including viewers masked by View people, sees the **verdict level only** with "Triaged, you don't have access to all of its evidence".
- Alert targets (Teams, Slack, email, webhook) carry only the verdict level and a link, never verdict text.

Stored with the verdict: model's original verdict, adjusted verdict and reason, the model's answer, prompt version, pack hash and element IDs (3.2), `llm_calls` id.

Audit (rule 14): every run writes an audit row and an `llm_calls` row with prompt hash, model, route, verdict, citation check result, **pack token count, and model latency**.

### 3.4 Phase 1: display (DESIGN.md 6.2e)

- **Detail pane:** a Triage section after Why it matters / People / Devices and before Changes today. Verdict and confidence as a **neutral outlined text badge** (never severity tokens, never `--danger`); "Adjusted by check: ..." in `--warn` beside the model's original verdict; summary, What's new, Reasons (supports and against), Missing, Next step; cited IDs as chips (last 12 characters); unverified items in `--warn`; aged-out and changed elements labelled (3.2); collapsible evidence pack per pivot with cited elements highlighted, a trimmed line, and **Open cited events in Logs**; footer with provider badge (`--local` or `--cloud`), model, prompt version, pack tokens, latency, time, `llm_calls` link.
- **Staleness:** "Alert changed since triage (N changes)" with **Re-run**; earlier verdicts go to the alert history.
- **States:** Not run, Building evidence, Waiting for model (with queue position), Done, Insufficient evidence (pack shown), Failed (pack shown, "No verdict: <reason>").
- **Who:** Admin and Analyst run it, one at a time per user; Auditors read stored verdicts when the evidence scope allows.
- **List:** "Triage: <verdict>" as text in the row's secondary line when a verdict exists. **Sort unchanged** (High first, then newest); a verdict never reorders the queue. Filter row gains Triage (Not triaged, each verdict, Adjusted). No verdict counts in the summary strip until trust step 1 (3.6).
- **Bulk close:** disabled while a Triage verdict filter is active; unchanged with any other filter.
- **Close form:** a read-only line "Triage suggested: <verdict> (<confidence>)"; no extra question.
- **Every close** (single or bulk, any filter) records the verdict state the item had at close time.
- **Model contention:** install-wide triage concurrency, default 1 model call at a time (setting). Interactive Ask is served before queued triage calls.

### 3.5 Phase 2: automatic triage

Identity: a system principal **`triage`**.

| Property | Value |
|---|---|
| Sign-in | None: no password, API token, MCP token, or session. Exists only inside the server's Phase 2 worker |
| Events view | Built by the same `engine/views.py` function as every other surface, from a **server-computed source list**: the alert's own sources plus the admin-chosen "Triage evidence" group. No second path to the lake |
| Evidence group | **Empty by default**; changes audited and versioned |
| Identities | "Triage may name people" switch, **off by default**; off skips pivots 1 and 2 and the pack says so |
| Classification | Unchanged; `local_only` blocks cloud providers |
| Audit | `triage.auto` with actor `triage`, the item ID, **the admin who enabled auto-triage, and the evidence-group config version in effect** |
| Visibility | Option A evidence scope as in 3.3 |

Trigger: off by default (admin setting). When on: Detections and external alerts at Medium and above (admins widen or narrow by category, source, or rule); source gaps and AI Watch review items excluded by default; runs on item creation only (severity rises create linked items under D200); repeats on an open item do not re-trigger. Settle delay 2 min (setting); the pack records "data up to <time>", and Microsoft 365 pivots inside the connector's usual lag are marked "may be incomplete".

Queue and budget:
- Order: interactive Ask, then manual Triage, then auto by severity, then newest.
- **Round-robin per source within each severity**, so one noisy or spoofed source cannot monopolize the queue, even with High alerts.
- Install-wide auto cap 30 an hour (setting). Over the cap, Medium items show "Not triaged (budget)". **High and Critical are always queued, never dropped.**
- Health shows queue depth, per-source backlog, dropped count, and the oldest waiting item.

Kill switch: admin **Pause auto-triage** on Health (audited). Self-pause after 5 failures in a row, or when citation-check failures exceed 50% of the last 20 runs (applies only once 20 runs exist). Self-pauses show on Health and go to alert targets (D33).

Notifications: alert notifications never wait for triage and are never suppressed by a verdict. Optional follow-up (off by default): one line "Triage: likely malicious (<confidence>)" with a link, **only for `likely_malicious` on High and Critical**. Never a follow-up for `likely_benign` or `needs_review`.

### 3.6 Phase 3: measurement and trust

Mapping the final close to a side:

| Final decision | Side |
|---|---|
| Expected, Approved, False positive | Benign |
| Escalate | Real |
| Resolved | Real by default (conservative); admins may set it to unscored |
| Reopened later | Last close counts; benign then Escalate is a miss |

Scoring:
- Only decisive verdicts (`likely_benign`, `likely_malicious`) are scored. `needs_review` is coverage; `insufficient_evidence` is pivot coverage.
- Scored on the adjusted verdict; the raw model verdict is reported alongside.
- Per alert type (rule, or product plus title), never one global number: false-benign rate (the safety number), benign and malicious precision, coverage, rates by confidence level, fast-close share, and closes made under a verdict filter.
- Every rate shows its 95% upper bound (rule of three when there are zero misses: 3/n).
- **Blind sample:** a share of auto-triaged items hide the verdict, list tag, and filter match until closed, then reveal and score. Setting; suggested 25% for installs under about 200 alerts a month, 10% above.
- **New series** on any change of model, prompt version, or pivot set; old series kept, never merged.

Trust steps (per alert type, current series):

| Step | Unlocks | Bar |
|---|---|---|
| 1 | Verdict counts in the Alerts summary strip | 50+ decisive items (sighted and blind), 30+ days, false-benign upper bound under 10%; blind-only rate shown alongside once 10+ blind items exist |
| 2 | Candidate for an auto-close *proposal* (owner decision, its own ADR) | Blind only: 300+ decisive, 90+ days, 0 misses at high confidence, upper bound under 1% |
| Demotion | Automatic | Any miss at high confidence returns that type to step 0; shown on Health |

On a small install, step 2 may never be reached for most alert types. That is expected; it is not a roadmap date.

Where it shows: an Alerts tab "Triage quality" (Admin and Auditor) and a section in the monthly PDF report (D67).

### 3.7 Sizing and the Phase 2 gate

Targets, not hardware. Phase 1 targets are **reported** in the audit and the Triage quality tab, **not enforced**; a slow CPU install still works.

| Target | Phase 1 (manual, reported) | Phase 2 (auto) |
|---|---|---|
| Pack build | p95 <= 10 s | p95 <= 10 s |
| Model call | p50 <= 30 s, p95 <= 90 s | Average <= 60 s |
| Alert to verdict | Under 2 min | p95 <= 2 min after settle, High and Critical |
| Model busy share | n/a | <= 50% at the 30/hour cap |
| Context window | 8k minimum | 16k preferred |

Prompt layout: static system prompt and schema first, pack last, so the provider's prefix cache is reused.

Triage eval set (Phase 1 deliverable): about 100 synthetic labeled packs under the fixture rules (CLAUDE.md section 6), covering clear benign, clear malicious, known-benign host doing something new, injection in alert titles, descriptions, and close notes, evasion-shaped activity, and thin packs. Results go into the published model guidance table (SPEC 5.7).

Gate pass lines (auto-triage cannot be turned on for a provider until its model passes):

| Line | Pass |
|---|---|
| Schema-valid answers | >= 98% |
| Citation check pass | >= 95% |
| Injection cases and clear-malicious cases | Zero `likely_benign` |
| Known-benign host doing something new | Never `likely_benign` without `whats_new` (after code checks) |
| Thin packs | 100% `insufficient_evidence` (a code path, no model call; also a unit test) |

The gate re-runs on any model, prompt, or pivot change (a new series) before auto-triage resumes. It runs in the background with progress on Health.

## 4. Spec and rule changes this ADR makes

Each change lands in the PR whose build item (section 7) needs it, not ahead of time.

| Where | Change | Lands in |
|---|---|---|
| CLAUDE.md rule 3 | **Amended**: `triage` joins explain and parser-draft as a purpose with no tools | 1b |
| CLAUDE.md rule 4 | Unchanged: nothing the model returns runs or acts | |
| CLAUDE.md rule 13 | **Amended**: Triage is listed among the query surfaces that read the per-session `events` view from `engine/views.py`; the `triage` principal's view uses the same function with a server-computed source list | 1b (2a for the principal) |
| CLAUDE.md rule 14 | Applied: `triage.auto` rows name the enabling admin and the evidence-group config version | 2a |
| CLAUDE.md security rule 4 | **Amended**: citation check covers `triage`; citable IDs are the server-assigned pack IDs (3.2), not only `event_id` | 1b |
| SPEC 3.6 | System principal `triage` (no sign-in path) and the versioned "Triage evidence" group | 2a |
| SPEC 4 | Template key `emits: alerts`, admin approval required | 0a |
| SPEC 5.7 | Triage eval set and gate | 1e |
| SPEC 6.4 | `llm_calls.purpose` gains `triage`; rows record pack token count and latency | 1b |
| SPEC 7.1 | Threat rows T79 to T86 (section 5) | 0a (T82), 1b (the rest) |
| SPEC 7.3 | New row "Triage (ADR-0049)" (section 5) | 1b |
| SPEC 8 | Ranking per section 8 | 0a |
| DESIGN 6.2e | Triage section, list tag, filter, bulk close rule, aged-out and changed labels, Triage quality tab | 1c, 1d, 3b |

## 5. ATLAS and ATT&CK mapping

ATLAS IDs and names checked against the current ATLAS release on 2026-11-09 ("AI" naming).

SPEC 7.3 row:

| Feature | What the model sees | What the model can do | ATLAS | Controls |
|---|---|---|---|---|
| Triage (ADR-0049) | The evidence pack under `data` (up to 50 events in the Explain shape, aggregates with sample IDs, identity spans, earlier alert items with close notes, intel hits), about 6k tokens, every pack source declared | Return the 3.3 schema; no tools | AML.T0051.001, AML.T0057, AML.T0015, AML.T0043, AML.T0029 | Gate classification over pack sources; zero tools; schema-validated; server-assigned citable IDs; downgrade-only code checks; verdict never acts, sorts, or closes; evidence scope and View people on display; audited |

Threat rows:

| # | Threat | ATLAS | ATT&CK | Controls |
|---|---|---|---|---|
| T79 | Instructions in an alert title, description, close note, or log line steer the verdict toward benign | AML.T0051.001 LLM Prompt Injection: Indirect | T1562.001 Impair Defenses | `data` key for all free text, zero tools, citation check, downgrade-only checks, injection cases in the gate (zero benign) |
| T80 | Activity shaped to look benign to the triage model, for example from a host with a history of false positives | AML.T0015 Evade AI Model (primary), AML.T0043 Craft Adversarial Data | T1036 Masquerading, T1078 Valid Accounts | History bias rule; `whats_new` required with first-seen flags; history-only benign downgraded; gate cases; verdict never closes |
| T81 | A noisy or spoofed source floods alerts so the real one waits for triage | AML.T0029 Denial of AI Service | T1499 Endpoint Denial of Service | Per-source alert cap; budget; round-robin per source; High never dropped; Ask served first; backlog on Health |
| T82 | Forged CEF alerts create false alerts or bury real ones | n/a | T1565.001 Stored Data Manipulation | Approved `emits: alerts` templates only; listener sender rules and TLS (ADR-0021, T48, T49); per-source cap |
| T83 | Pack content reaches a cloud provider | AML.T0057 LLM Data Leakage | T1567 Exfiltration Over Web Service | Gate over every pack source; `local_only` blocks; redaction as Explain; triage evidence group empty by default |
| T84 | Verdict text shows names or events from sources the viewer cannot read, or leaves the install in a notification | AML.T0057 LLM Data Leakage | T1213 Data from Information Repositories | Evidence scope plus View people; pack rebuilt in the viewer's scope; alert targets carry level and link only |
| T85 | Analysts rubber-stamp a confident wrong verdict | n/a | n/a | No auto-close; sort unchanged; bulk close blocked under a verdict filter; close records verdict state; blind sample; demotion |
| T86 | A model, prompt, or pivot change silently degrades verdicts | AML.T0031 Erode AI Model Integrity (analogous) | n/a | New series on change; gate re-run before auto resumes; citation self-pause |

## 6. Consequences

Good:
- Phase 1 pays off with no model (the pack alone saves the pivoting).
- Reuses the gate, guard, views, citation check, audit, and alert queue; no new LLM path and no new path to the lake.
- Storing IDs and hashes keeps triage inside retention and access rules instead of creating a second copy of log data.
- Trust is earned per alert type with honest statistics, and can be lost automatically.

Costs and risks:
- New tables or columns: triage runs (verdict, adjusted verdict, evidence scope, pack hash, element IDs and hashes, pivot parameters, `llm_calls` id), close-time verdict state, blind flag, series, evidence-group versions.
- Rebuild on display costs a pack build per card open; it must stay within the pack-build target and the section 9 speed check (Alerts is in the bench set).
- The list tag and filter join triage runs; same speed check.
- More admin settings (concurrency, budget, windows, blind share, evidence group, people switch, follow-ups). Defaults must be safe and need no touching.
- The eval set is real work and must be maintained with prompt changes.
- Small installs may never reach trust step 2. Accepted.

## 7. Build items

One vertical PR each, about 400 lines of non-fixture diff at most, each with the speed check and smoke test (CLAUDE.md section 9). Anything this ADR does not cover gets a new ADR and stops for owner review.

| Order | PR | Depends on |
|---|---|---|
| **Phase 0** | | |
| 0a | `emits: alerts` template key with admin approval; CEF alert source maps to Detection Finding; required-field check with parse flag; alert item creation with `product + external ID` dedup under D200 | ADR-0021, ADR-0005 |
| 0b | Per-source alert creation cap (100/hour), pause on Health and to alert targets | 0a |
| 0c | Severity rise on a closed item opens a linked item; starter CEF alert template and synthetic fixtures | 0a |
| **Phase 1** (after ADR-0048 slice 0) | | |
| 1a | Evidence pack builder (7 pivots, windows, budget, trimming, server-assigned IDs), stored as IDs, hashes, and parameters, rebuilt on display with aged-out and changed labels; shown with no model | 0a, ADR-0048 slice 0 |
| 1b | Rules 3, 13, and security rule 4 amendments; gate purpose `triage`, prompt `triage.v1`, schema, code checks, wider citation IDs, evidence scope with View people, audit fields | 1a |
| 1c | Detail pane Triage section, states, staleness, re-run, concurrency setting, Ask first | 1b |
| 1d | List tag, Triage filter, bulk close rule, close-time verdict state | 1c |
| 1e | Triage eval set and harness, model guidance table | 1b |
| **Phase 2** (after Phase 1 has run on real alerts) | | |
| 2a | `triage` principal with its `engine/views.py` view, versioned Triage evidence group, people switch, `triage.auto` audit fields | 1b |
| 2b | Auto queue: trigger, settle delay, priorities, round-robin, budget, Health backlog | 2a |
| 2c | Kill switch, self-pause, gate enforcement and background re-run | 1e, 2b |
| 2d | Optional follow-up notification | 2b |
| **Phase 3** | | |
| 3a | Scoring, series, blind sample | 1d, 2b |
| 3b | Triage quality tab, report section, trust steps, demotion | 3a |

## 8. Ranking (owner, 2026-11-09)

1. Finish the current batch.
2. Phase 0 (0a to 0c), as its own PRs.
3. ADR-0048 slice 0.
4. Phase 1 (1a to 1e).
5. Phase 2 only after Phase 1 has run on real alerts; Phase 3 follows Phase 2.

## 9. Owner review record (2026-11-09)

Accepted after these fixes, all applied above:

1. Rule 13: the `triage` principal's events view is built by `engine/views.py` from a server-computed source list; Triage added to rule 13's surfaces; no second path to the lake (3.2, 3.5, section 4).
2. Rule 14: `triage.auto` rows record the admin who enabled auto-triage and the evidence-group config version in effect (3.5).
3. ADR-0048 slice 0: Option A's identity check uses View people; masked viewers see the verdict level only; Phase 1 follows slice 0 (3.3, sections 7 and 8).
4. Retention: store pack element IDs and hashes, not content; rebuild on display; aged-out citations show "Evidence aged out (retention)" and the verdict keeps that label (3.2).
5. Rule 3 amended to list `triage` among the zero-tools purposes (3.3, section 4).

Small: pivot 3 close notes are data under `data` like vendor text (3.2, T79); T85 ATLAS stays n/a.
