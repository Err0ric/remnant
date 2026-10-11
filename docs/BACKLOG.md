# Backlog

Items noted during a slice that belong to a later slice. Move into the slice plan when it starts.

| Item | Target slice | Noted |
|---|---|---|
| Pin Docker base images by digest | 6 | Slice 1 skeleton |
| Self-hosted Lucide subset or tree-shake audit | 6 | Slice 1 skeleton |
| Command palette (Ctrl+K) wired up; header shows a hint only | 6 | Slice 1 skeleton |
| Investigate action on expanded rows wired to Investigation pages | 4 | Search UI PR |
| Read-only MCP server (SPEC 3.8, ADR-0003) | 7 | Roadmap, 2026-10-10 |
| Octet-counted framing for file sources (watcher reads newline-framed files; octet counting is a TCP framing, covered in the framer for the Slice 7 listener) | 7 | Slice 1 review |
| Per-partition classification summary written at ingest, so the gate's event-label check does not scan the `classification` column on every cloud call | 5 | Gate review, 2026-10-10 |
| Hash chain over `llm_calls` and `audit_log` rows (tamper evidence beyond triggers) | 8 | Gate review, 2026-10-10 |
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
