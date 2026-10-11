# ADR-0007: Alert routing (email, Microsoft Teams, Slack, webhook)

Status: **Accepted** 2026-10-11 (reviewed by the project owner: every recommendation accepted).

## Context

D26 moved alert routing into Slice 4, and the Slice 4 DoD asks for email (SMTP), Microsoft Teams, Slack, and a generic webhook, with per-rule and per-schedule targets, a test-send button, and retried, visible failures. Schedules (rules and saved searches) and their flags exist now (SPEC 5.5), so this is the last Slice 4 item.

Alerting is the first feature that sends data out of the server to a destination someone typed in. That raises questions the spec does not answer:

- **Data leaving the box.** Slack and Teams are cloud services. SPEC 6.2 refuses to send `local_only` data to cloud models; nothing yet says what may go into an alert.
- **Server-side request forgery.** A webhook URL makes the server send a request to an address someone chose: cloud metadata endpoints, admin panels on the LAN, or the app itself.
- **Secrets.** Webhook URLs carry their token in the URL; SMTP needs a password. Both must be stored like provider keys (encrypted with `data/.key`, never shown back, never logged).
- **Trust in what an alert says.** An alert should never be the only place a finding lives, and it should not be able to carry instructions from log content into a chat channel without being clearly quoted.

Also, SPEC section 2 still lists "alert routing" under non-goals for v1, which D26 overrode; that line gets fixed with this ADR.

## Decision

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. Who manages destinations | Admins create alert targets (type, name, URL or SMTP settings, secrets). Analysts choose from existing targets for their own schedules. Every create, change, delete, and test send is audited | A target is an outbound channel with credentials; same rule as AI providers | Analysts create their own targets |
| 2. What an alert contains | **Summary only**: what fired (schedule or rule name, rule author and title for Sigma), when, the count, the flag reason, the time range, and a link back to the run in the app. No event content, no sample rows, no field values | Keeps log content (and anything an attacker wrote into it) out of chat channels and mailboxes, and sidesteps the classification question entirely. The analyst clicks through to see the data with their own permissions | Include up to N sample rows, only when every source the run read is `cloud_allowed` (reusing the classification gate), off by default |
| 3. When alerts fire | A saved-search schedule run that is flagged (threshold); a rule schedule run with at least one match, or flagged if a threshold is set; and, to the owner's chosen target, a schedule that pauses itself (with the reason). On-demand runs never alert | Matches what people expect from "alert me"; a silent pause is a silent detection gap | Alert on every run |
| 4. Outbound safety | Slack and Teams: `https` only, host must be the vendor's webhook host (Slack `hooks.slack.com`; Teams Workflows hosts under `*.logic.azure.com` and `*.powerplatform.com`, checked again at build time). Generic webhook: `https` for public hosts, `http` allowed for private or loopback addresses (a homelab relay such as ntfy or n8n is a fair use); link-local and cloud metadata addresses (`169.254.0.0/16`, `fe80::/10`, `fd00:ec2::254`) always refused; the address is resolved once and pinned (as the LLM adapter does), no redirects, 10 s timeout, response body read at most 64 KB and never shown. SMTP: STARTTLS or implicit TLS with certificate checks, except to a loopback relay | Covers SSRF to metadata and stops a URL change from silently moving traffic | Refuse all private addresses (blocks legitimate homelab relays) |
| 5. Integrity of webhooks | Generic webhooks carry an `X-Signature-256` HMAC-SHA256 of the body with a per-target secret, and a timestamp | Lets the receiver reject forged or replayed alerts | No signing |
| 6. Delivery and failures | Each alert is a delivery row (target, run, attempts, last error, status). Up to 3 attempts with backoff (1, 5, 15 minutes). Failures show on the Schedules page and the target's page; a target failing 10 times in a row is marked failing (still tried) | The DoD asks for retried, visible failures | Fire and forget |
| 7. Formats | Email: plain text plus a simple HTML part, subject `[<product name>] <what fired>: <count>`. Slack: Block Kit message. Teams: a Workflows (Power Automate) webhook, which accepts Adaptive Cards and the older MessageCard format; Office 365 connector webhooks in Teams were retired in May 2026 (Microsoft 365 message MC1181996). The Workflows webhook host names are confirmed when building, before the row 4 host check is fixed. Webhook: JSON with a documented, versioned schema | Native look in each tool; one internal alert object rendered four ways | |

## Questions for the owner

1. **Alert content (row 2):** summary only with a link back (recommended), or allow sample rows for runs that read only `cloud_allowed` sources?
2. **Who creates targets (row 1):** admins only (recommended), or analysts too?
3. **Private addresses for generic webhooks (row 4):** allow private and loopback over `http` for homelab relays (recommended), or require `https` and public hosts only?
4. **Pause notices (row 3):** send a message when a schedule pauses itself (recommended), or only show it on the dashboard?

## Consequences

- Meta tables (additive): alert targets (secrets encrypted), schedule-to-target links, deliveries.
- A delivery worker in the server next to the schedule loop.
- UI: Configuration > Alert targets (admin), a target picker on the schedule form, delivery status on the Schedules page.
- SPEC section 2 non-goals line updated; SPEC 5.5 gains an alerting paragraph.

## ATT&CK

| Threat | ATT&CK | Control |
|---|---|---|
| Alerts used to move log data out of the network | T1567 Exfiltration Over Web Service | Summary only (row 2); admin-only targets; every send audited |
| Webhook URL aimed at internal services or cloud metadata | No direct ATT&CK technique; CWE-918 Server-Side Request Forgery | Row 4 address rules, pinned resolution, no redirects |
| Forged alerts to a webhook receiver | T1565.002 Transmitted Data Manipulation | HMAC signature and timestamp (row 5) |
| Alerts silenced by breaking a target | T1562.001 Impair Defenses | Failures visible, failing state, audit of target changes |

Not AI-facing, so no ATLAS mapping.

## Review outcome

| Question | Answer |
|---|---|
| 1. Alert content | Summary only, with a link back to the run; no event content |
| 2. Who creates targets | Admins only; analysts pick targets for their own schedules |
| 3. Private addresses for generic webhooks | Allowed over `http` for private and loopback addresses; public hosts need `https`; link-local and metadata addresses always refused |
| 4. Pause notices | Sent to the schedule's targets when it pauses itself |
