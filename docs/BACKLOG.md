# Backlog

Items noted during a slice that belong to a later slice. Move into the slice plan when it starts.

| Item | Target slice | Noted |
|---|---|---|
| On or after 2026-11-02: bump `certifi` to 2026.10.19 (PYSEC-2026-4320), then drop its row in `docs/security/dependencies.md` and its CI ignore | Maintenance | CI, 2026-10-20 |
| AI catalog freshness, part one: a Possible AI list on AI usage > Services. Destination domains in DNS, firewall, and proxy logs that are not in the catalog but look like AI (a `.ai` domain; `gpt`, `llm`, `chat`, `copilot`, `agent`, `inference` in the name; known model hosting sites), with Add to catalog or Dismiss, both audited. Local logs only. Write an ADR first | 9 | Owner, 2026-10-21 |
| AI catalog freshness, part two: optional catalog updates. The service catalog published as a signed file in the public repo; the server checks for a newer version on a schedule like the ADR-0023 intel feeds (off until turned on, pull only, nothing sent, every change shown and audited). Release checklist adds a review of new AI services | 9 | Owner, 2026-10-21 |
| Renew the generated self-signed certificate on its own before it expires (825 days), with a Health warning 30 days ahead | 9 | Install feedback, 2026-10-21 |
| Cancel during an in-flight model answer (ADR-0028 follow-up): Cancel frees a request's place while it waits, but once the request is sent, the call runs synchronously in a worker thread with a 180 s read timeout, so the connection stays open and Ollama keeps generating until it finishes, holding the only slot. Fix: stream responses (`stream: true`) and stop reading and close the connection when the cancel flag is set, which makes Ollama stop; or close the client from the watcher thread. Needs streaming in both adapters | 9 | Owner review, 2026-10-21 |
| Pin Docker base images by digest | 6 | Slice 1 skeleton |
| Self-hosted Lucide subset or tree-shake audit | 6 | Slice 1 skeleton |
| Read-only MCP server (SPEC 3.8, ADR-0003) | 7 | Roadmap, 2026-10-10 |
| Octet-counted framing for file sources (watcher reads newline-framed files; octet counting is a TCP framing, covered in the framer for the Slice 7 listener) | 7 | Slice 1 review |
| Per-partition classification summary written at ingest, so the gate's event-label check does not scan the `classification` column on every cloud call | 5 | Gate review, 2026-10-10 |
| Cache Ask sample values per scope for a few minutes instead of 10 GROUP BY scans per question | 6 | Ask review, 2026-10-10 |
| DNS query name and type columns (`query_hostname`, `query_type`, additive schema change); DNS templates use `message` and `unmapped` until then | 3 | Starter batch 2 |
| Vendor CEF and LEEF templates with `class_by` on signature or event id | 3 | Starter batch 1 |
| Target user column (OCSF `user.name`, additive schema change) so account, group, and lockout events can show the account acted on; until then it stays in `unmapped` (`TargetUserName`) | 3 | Windows batch |
| OCSF classes for Windows events the map labels only: 1102 audit log cleared, 4697 and 7045 service installed, 4698 scheduled task created (class_uid 0 today) | 4 | Windows batch |
| Windows DNS debug log: day-first 12-hour locales (en-AU, en-NZ, en-IN) parse with day and month swapped unless the template is copied and changed; add a per-source date order setting | 3 | Windows batch, review |
| JSON templates keep the whole nested object in `unmapped` even when nested leaves are mapped, so Winlogbeat and EVTX rows store the record twice (raw and unmapped); drop mapped leaves or skip unmapped for raw-equal JSON | 6 | EVTX PR |
| Sysmon in the Windows map: map Image, ParentImage, User, SourceIp, DestinationIp, and ports, with `Initiated` deciding direction, then add event ids 1, 3, 5 | 3 | EVTX review |
| Confirm `%%14592` = Inbound and `%%14593` = Outbound for 5156/5157 Direction on a real Windows host (Event Viewer friendly view vs XML); templates rely on it | 3 | EVTX review |
| Ingest loop handles sources one after another; a large backlog in one source delays the rest. Per-source time budget or a worker per source | 6 | EVTX review |
| Header news ticker (rotating security headlines) in the empty top bar. Needs an ADR first: it is the first outbound call not made by a user action. Off by default, admin-set feed URL, fetched server side (CSP stays `self`), headlines rendered as text nodes with links opened in a new tab, cached, no log data or user info sent | 6 | Homelab test, 2026-10-10 |
| Phone width (about 400px): top bar wraps and the side nav stacks above the page; collapse the nav behind a menu button and shorten the top bar | 6 | Browser walkthrough, 2026-10-10 |
| Templates: regex timeouts apply per call, so a template with many regex transforms can cost seconds on one hostile line; add an aggregate time budget per line | 6 | Security review, 2026-10-10 |
| OCSF-native Sigma pipeline (`detect/pipelines/ocsf.py` is a stub): rules written against OCSF column names | 8 | Slice 4 Sigma backend, D13 |
| Sigma 4688 mapping, part two: `User` (Sysmon `DOMAIN\user` vs 4688 `SubjectDomainName` and `SubjectUserName`) and process ids (4688 records them in hex), so more process creation rules can also run on Security 4688. Part one (Image, ParentImage, CommandLine, LogonId) shipped in Slice 4 | 4 | Slice 4 Sigma backend |
| Agent API for outside agents: the ADR-0003 MCP server plus a documented REST surface (OpenAPI) for per-user tokens, so an agent can query, read flagged runs and rule matches, and pull results marked unverified for review on a schedule | 7 | Review feedback, 2026-10-11 |
| Verification endpoint: an agent submits a claim with `event_ids` (and optionally its query); the server checks each id exists in the caller's view and returns the events, so agent reports are checked against the lake (the SPEC 7 citation check, offered to outside agents) | 7 | Review feedback, 2026-10-11 |
| Outsider install test: someone other than the author installs from the GitHub README on a fresh host with no help, and every gap found is fixed in the install guide | 6 | Review feedback, 2026-10-11 |
| Re-parse a source's stored events with its current parser (from `raw`) into new partitions, replacing the old rows; admin only, audited, with a dry-run count first (ADR-0012 row 8) | 6 | ADR-0012, 2026-10-11 |
| CLI device-code sign-in for SSO users (OAuth device authorization grant), so `remnant login` works without creating a token in the web UI (ADR-0013 row 9) | 7 | ADR-0013, 2026-10-11 |
| SAML 2.0 sign-in, only if an identity provider without OIDC is asked for (ADR-0013 row 1) | Later | ADR-0013, 2026-10-11 |
| Built-in quiet-source check: per-source "expect events every N minutes" on the Sources page, one alert per source to chosen targets, cleared when events resume; proposed in ADR-0014 (waiting for review). Until then, a schedule flagged below 1 does it (docs/install/quiet-sources.md) | 7 | Overnight work, 2026-10-12 |
| Documentation site: one place for install, every integration (M365, Claude Code, agents, Loki, syslog relays, SSO), configuration, and operations, in the style of a vendor docs portal (left nav, breadcrumbs, search). Built from `docs/` with MkDocs Material and published on GitHub Pages (no domain needed); until then the guides live in `docs/install/` | Later | Owner request, 2026-10-14 |
| PowerShell MCP inventory script: first run on a Windows machine (the Python version is tested; no PowerShell in CI) | 7 | AI usage PR, 2026-10-14 |
| M365 and Anthropic connectors: first run against a live tenant and a live Admin API key; record any response shapes the fakes missed | 7 | Connector PR, 2026-10-14 |
| Microsoft 365 consent link on the add-source form (`https://login.microsoftonline.com/{tenant}/adminconsent?client_id=...`) | 7 | Connector PR, 2026-10-14 |
| Active checks for watched devices (ping, TCP port): **not planned**. Uptime is an uptime monitor's job; ingest its alerts as a source instead (ADR-0019 row 6) | n/a | Health page, 2026-10-15 |
| Salesforce connector (event log files, login history, setup audit trail; Einstein and Agentforce AI audit needs Data Cloud). Later, when asked for | Later | Owner question, 2026-10-15 |
| README screenshots still to add: Ask follow-ups (needs a model), Identities, Sources with Microsoft 365 (needs a tenant). The rest were refreshed 2026-10-17 with the new shell | 6 | README review, 2026-10-15 |
| Okta, Google Workspace, and AWS CloudTrail connectors (Slice 7 list). Each needs a sign-in choice first (Okta API token or OAuth service app; Google service account with domain-wide delegation; CloudTrail from the S3 bucket or the LookupEvents API) | Later | Owner, 2026-10-17: not needed now |
| Object-storage tier for older partitions, queried in place (Slice 8). Deferred by the owner 2026-10-17: querying S3 in place needs DuckDB external access, which rule 7 turns off on every query connection. Needs an ADR for a separate, non-user connection first; a NAS mount used as the lake path covers small installs meanwhile | Later | Slice 8 planning, 2026-10-17 |
| Merged Home page: Overview health cards and Dashboard panels on one page (ADR-0031 option b). Option (a) shipped: Dashboard first when it has panels, with a health strip | Later | Owner, 2026-10-21 |
| Ask prompt: prefer `raw` over `message` for text matching (D84). Needs a new prompt version and an accuracy-suite run before it becomes the default | Later | Trial F36, 2026-10-21 |
| Re-parse stored events from `raw` for a source and time range (for example after a time zone or template fix, D85): writes new rows, keeps the old ones out of queries, and records it in the integrity ledger | Later | Trial, 2026-10-21 |
| Azure subscription Activity Log connector (resource provider registration, resource changes, role assignments on subscriptions): not in any Microsoft 365 feed. Read through the Azure Monitor REST API or an Event Hub export; needs the sign-in choice and an ADR (ADR-0002 follow-up) | 7 | Install F45, 2026-10-22 |
| Daily rollup for AI usage (service, device, person, day, count), built by the compaction job, so 30 and 90 day views read it instead of events. Not needed at the sizes measured after D94 (30 days of 300k DNS events a day); revisit if a larger install is slow | Later | Install F46, 2026-10-22 |
| No sideways scroll at 1100px: AI providers and AI usage > Services scroll a little; fix them, then add 1100 to the CI width check (`scripts/check-layout.py`, owner 2026-10-22, after live mode) | F54 follow-up |

## Morning answer: admin grants and app consents in "New in 24 hours"

ADR-0037 row 6 lists new admin or role grants and app consents in the New column. The column shows AI services, MCP servers, and agents (AI Watch items) today; grants and consents need a small server query over Microsoft 365 directory and management audit events (the AI Watch consent card already counts consents per period).

## From ADR-0038 parts 3 and 4 (2026-10-30)

- **Microsoft 365 rollup** (ADR-0038 section 5, "Speed"): closed days from a daily rollup, today from events, as the AI rollup does, so the 30-day Overview stays fast on a large tenant. The area reads events directly until then.
- **Agents Overview and Tools tabs** (ADR-0038 section 6): KPIs (sessions, people, tool calls, failed calls, not-approved MCP servers in use, devices late or missing) and a typed Tools table.
- **Accounts corroboration** (ADR-0030 T3): raise Company, reported and Company, not confirmed when the Anthropic usage or compliance connector names the same email in the window.
