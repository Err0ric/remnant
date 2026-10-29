# ADR-0030: Approved for company accounts, and possible personal-account use

Status: **Accepted** 2026-10-23 by the owner, with the conditions in "Owner conditions" below; where a row above differs, the conditions win. Recorded as SPEC D108. Built after ADR-0029.

## Context

The install trial raised a common policy: a service such as ChatGPT or Claude is approved, but only through the company's own workspace (the "tenant"), signed in with company single sign-on. Using the same service with a personal account is not approved. The domain is the same for both, so network logs alone cannot tell them apart.

Today a service has one review state (Approved, Unreviewed, Not approved, ADR-0015) and an allowed data level (ADR-0020 row 4). Marking ChatGPT Approved hides personal use; marking it Not approved flags every company user.

The lake often already holds evidence of tenant use:

| Evidence | Where it comes from today | Says |
|---|---|---|
| SSO sign-in to the app | Microsoft 365 connector, Graph sign-ins (`appDisplayName`, app id, user) | This person signed in to the company app at this time |
| Vendor usage or compliance reports | Anthropic usage, Claude Code, and compliance activity connectors | This person used the company workspace at this time |
| Claude Code telemetry | OTLP receiver | This person used the company's Claude Code setup |

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | New review state | Add **Approved, company tenant only** next to Approved, Unreviewed, Not approved. Shown on the AI usage review list; changes audited `ai.service_change` like the others | One more state where review already happens | A separate policy page (another place to keep in sync) |
| 2 | Tenant evidence per service | An admin lists, per service, what counts as evidence: one or more SSO app ids or display names (from the Microsoft 365 sign-ins), and optionally a vendor connector source. Shipped hints for well-known services (for example the Enterprise app names of ChatGPT Enterprise and Claude for Work), never applied without the admin saving them | The app ids are tenant-specific; only the admin knows them | Guessing from domain names (cannot separate the accounts) |
| 3 | The check | For network use of a tenant-only service by a resolved person (ADR-0029), look for tenant evidence for the same person within a window around the use (default 8 hours before to 1 hour after, configurable 1 to 24 hours). None found: the row is **Possible personal account** | SSO sessions last hours; a window avoids flagging every request | Per-request matching (SSO is not per request) |
| 4 | Unresolved rows | Use by an address or machine with no person is **Not checked**, never flagged | Cannot compare a person who is not known | Flagging unknowns (noise) |
| 5 | Identity matching | Person names are compared through the identity map (ADR-0018), so `alice`, `EXAMPLE\alice`, and `alice@example.com` are one person | Sign-ins use UPNs; network logs use short names | Exact string match (misses most) |
| 6 | Where it shows | AI usage Services tab: a count of possible personal-account people per tenant-only service, with the rows. AI watch: optional alert on the first possible personal use per person and service, same once-per-sighting rule as today. Investigations: a Suspicious preset | Where people already look for shadow AI | A new page |
| 7 | Wording | "Possible personal account: no company sign-in seen for this person in the window." Never "personal account" without "possible" | The evidence can be missing for other reasons (sign-in log delay, source not readable by this user) | Stating it as fact |
| 7a | What was missing (owner review) | Each flag states the evidence it looked for and did not find, in plain words: "No company SSO sign-in to Claude within 8 hours before or 1 hour after." The evidence sources configured for the service are listed under it, with their freshness from Health | The reviewer sees why, and whether a source was simply behind | A bare "Possible personal account" |
| 7b | Review, not action (owner review) | The flag is a prompt for a reviewer. Nothing acts on it automatically: no blocking, no ticket, no message to the person or their manager. The AI watch alert (row 6) goes only to the targets the admin chose for AI watch and, under ADR-0029 G5, names a person only to targets marked for people with the permission | A missing log is not misconduct; people decide | Automatic notifications (wrong on every gap in logging) |
| 8 | Scope | Evidence comes from the caller's own events view; a user who cannot read the sign-in source sees **Not checked**, not a flag | Rule 13; no flag built on data the viewer cannot see | Server-wide evidence (would leak) |

## Since this was written (2026-10-22)

Microsoft 365 sign-ins now carry the device name (`device_hostname`) as well as the user and app. Row 3's check can require the evidence and the network use to match on the person **and**, when both are known, the device: a company sign-in from WS-0042 does not clear use from a different machine. When the device is unknown on either side, the check falls back to person only, as written.

## Owner conditions (2026-10-23)

| # | Condition | What it changes above |
|---|---|---|
| C1 | The state is **Approved for company accounts** (Claude, and any service with a company tenant) | Row 1's name |
| C2 | Use counts as approved only with company sign-in evidence: an Entra / Microsoft 365 sign-in to that app by the same person, on the same device when both sides know it | Row 2: only M365 sign-ins clear use. Vendor reports (Anthropic compliance, Claude Code telemetry) show on the row as context, never as clearing |
| C3 | The window is per service and defaults to the app's session lifetime (configurable; for example 30 days for Claude). The evidence is **the most recent company sign-in to this app by this person (or device) within the window before the use** | Replaces row 3's 8 h before to 1 h after: an SSO app signs in when its session starts, and the session lasts days or weeks, so a short window would flag most company users |
| C4 | Use with no matching company sign-in is **Possible personal account**: one alert item per person, or per device not matched to a person, per service per day, under the one rule (D116) and its close rules | Replaces row 4 (devices are checked too, against sign-ins from that device) and row 6 (always an item, not an optional once-per-sighting alert) |
| C5 | **Report-only first.** Possible personal account is computed and shown on AI usage, but no alert items are raised until an admin turns on **Raise alerts for possible personal accounts** (off by default; audited `ai.watch_change`) | New switch on AI usage > Review and alerts |
| C6 | Where the evidence cannot exist (no Microsoft 365 sign-in source, or the app is not signed into through Entra SSO), the service shows **Can't verify company accounts** with what is missing; it is never treated as approved | Row 8 stays for a viewer who cannot read the sign-in source; C6 is the service-level state |
| C7 | Possible personal account and Can't verify count as unapproved on the AI Watch cards, with their own context line ("2 possible personal accounts on Claude") | AI Watch cards (D114) |
| C8 | Each row shows the evidence that matched ("company sign-in 9:02 AM, device RC0238") or what was looked for and not found (row 7a) | Every decision is checkable |
| C9 | Device match only where the sign-in has a device id (Entra-joined or registered devices). Without one, match on the person only and say so on the row ("person only: the sign-in had no device") | The "since this was written" device rule, made explicit |
| C10 | A setup note on each such service: "Requires sign-in through Entra SSO", with how to confirm the app appears in the Entra sign-in logs | Shown on the service's review |
| C11 | Review decisions never change on upgrade. A one-time notice on AI usage offers to move an Approved service with company sign-in evidence configured to Approved for company accounts: one click, audited `ai.service_change` | The owner's Claude review |

### Non-interactive sign-ins (checked 2026-10-23)

- Graph `v1.0/auditLogs/signIns`, which the Microsoft 365 connector reads today, returns interactive sign-ins only.
- Non-interactive user sign-ins (token refreshes by a client already signed in) are available only from the **beta** endpoint, with an explicit filter: `beta/auditLogs/signIns?$filter=signInEventTypes/any(t: t eq 'nonInteractiveUser')`. Without the filter, beta also returns interactive only.
- Where an app refreshes tokens through Entra (OAuth / OIDC apps), non-interactive sign-ins show ongoing use and are better evidence than the session's first sign-in. A SAML-only app signs in through Entra only when its session starts, so it has interactive sign-ins only; C3's session-length window covers it.
- Decision: an optional Microsoft 365 feed **Non-interactive sign-ins** (beta), filtered to the apps configured as evidence (they are high volume across a tenant), off by default. Evidence from it is labelled "token refresh 9:40 AM". Whether Claude's Entra app shows non-interactive sign-ins is checked on the owner's tenant (Entra admin center > Sign-in logs > User sign-ins (non-interactive), filter Application) before relying on it; until then the interactive window (C3) is the rule.
- `deviceDetail.deviceId` is filled only for Entra-joined or registered devices (C9).

## Consequences

- A common policy ("company workspace only") becomes visible without proxy decryption.
- Depends on ADR-0029 for people behind addresses; until then only rows with a person are checked.
- False positives when sign-in logs lag or the connector is down: the Health page already shows connector freshness, and the window is configurable.
- New config per service (evidence list) stored with the catalog review state; additive migration.

## Threat model (SPEC section 7)

- MITRE ATLAS AML.T0057 (LLM Data Leakage): company data sent to a model through a personal account, outside the tenant's retention, training, and audit settings. This ADR is a detection for it. ATT&CK T1567 (Exfiltration Over Web Service) for the same path.
- Person-level flags follow ADR-0029 governance (G1 to G6): only users with **View people in AI usage** see names; every named view and export is audited.
- New risk: an analyst treats "possible" as proof and acts against a person. Mitigation: wording (row 7), evidence shown with each flag, and Not checked when evidence cannot be seen.
- No model input; deterministic SQL only.

## Tests

- Person with a matching sign-in in the window: not flagged; outside the window: flagged, with the missing-evidence text naming the service and the window; no person: Not checked.
- Flagging changes nothing else: no alert target, ticket, or message is created unless AI watch is on and the target is configured.
- Identity map joins `alice` and `alice@example.com`.
- A user without the sign-in source sees Not checked.
- Review state change audited; watch alerts once per person and service.

## Out of scope

- Reading account identifiers from TLS or proxy logs (needs decryption or vendor tenant headers; a later option where a proxy already adds them).

## Amendment 2026-10-29 (owner: Claude account email from the hooks plugin, with tiers)

The hooks plugin now reports the signed-in Claude account email for Claude Code and Cowork sessions (ADR-0026 amendment 2026-10-29 row 4). That names the account in use directly, which a sign-in window can only infer; but it is reported by the device (the file it comes from can be edited), so it is a tier of its own below an Entra sign-in. This amends condition C2 for Claude Code and Cowork use only; browser use still needs an Entra sign-in.

| Tier | When | Row label | Counts as |
|---|---|---|---|
| Company, confirmed | Company-domain account email, and an Entra sign-in to the app by the same person within the window (C3) | "Company account: reported by device, sign-in 9:02 AM" | Approved |
| Company, reported | Company-domain account email; no Microsoft 365 sign-in source is configured | "Claude account (reported by device)" | Approved |
| Company, not confirmed | Company-domain account email; a sign-in source is configured but has no sign-in to the app by that person within the window | "Reported company account, not confirmed by sign-in" | Approved, flagged for review. Report-only: no alert item unless an admin turns on **Raise alerts for unconfirmed company accounts** (off by default; audited `ai.watch_change`) |
| Personal | Account email outside the company domains | "Personal Claude account" (a fact the device reported, not "possible") | Unapproved. An alert item per person and day once **Raise alerts for possible personal accounts** (C5) is on |
| Not checked | No account email (API key sessions, or no plugin) | "Not checked: no Claude account reported" | Never company: not cleared, counted with Can't verify (C7) |

| # | Rule |
|---|---|
| T1 | **Company domains** are the ADR-0018 organization email domains setting (one list for identity and this check). Compared case-insensitively on the exact domain. With the list empty, every row with an email is Not checked, and the service says so |
| T2 | **What the email clears**: the hook records themselves, and network use of the Claude API host (`api.anthropic.com`) from the same device within the window. Network use of `claude.ai`, which a browser and the desktop chat share, still needs an Entra sign-in (C2) |
| T3 | **Corroboration**: when the Anthropic compliance or usage connector is configured and names the same account email in the window, the row adds "seen in the Anthropic usage report". It raises Company, reported and Company, not confirmed to the same standing as confirmed (the report comes from Anthropic, not the device) |
| T4 | **Shown evidence (C8)**: every row names the tier, the email's source (`managed`, `env`, `claude_json`), the device, and the sign-in or report that matched, or what was looked for and not found |
| T5 | Nothing acts on a tier (row 7b): no blocking, ticket, or message; items go only to targets the admin chose, and name people only under ADR-0029 G5 |

Threat: a device reports a forged company email to hide personal use (T63): mitigated by the "not confirmed" tier against Entra sign-ins, corroboration from Anthropic's own report, and labelling every tier with its source.
