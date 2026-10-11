# ADR-0002: Microsoft 365 connector

Status: **Accepted** 2026-10-10 (SPEC D27, Slice 7)

## Context

Target users run Microsoft 365. Sign-ins, mailbox and SharePoint activity, admin changes, and security alerts live in Microsoft's APIs, not in syslog. Users want those events in the same lake, searchable in plain language next to firewall and server logs.

## Decision

A built-in connector, registered by the customer's admin as a single-tenant Entra ID application, read-only.

| Data | API | Application permission |
|---|---|---|
| Exchange, SharePoint/OneDrive, Teams, Entra audit, DLP | Office 365 Management Activity API (`Audit.Exchange`, `Audit.SharePoint`, `Audit.AzureActiveDirectory`, `Audit.General`, `DLP.All`) | `ActivityFeed.Read` (and `ActivityFeed.ReadDlp` for DLP) |
| Interactive and non-interactive sign-ins | Microsoft Graph `auditLogs/signIns` | `AuditLog.Read.All` (requires Entra ID P1 or P2) |
| Directory changes | Microsoft Graph `auditLogs/directoryAudits` | `AuditLog.Read.All` |
| Security alerts (optional) | Microsoft Graph security alerts | `SecurityAlert.Read.All` |

- **Auth:** client credentials with a certificate (preferred) or a client secret. The private key or secret is stored encrypted in the settings store and never logged.
- **Setup flow:** a guided page lists the exact permissions, shows the consent link for the tenant admin, and runs a test pull before saving.
- **Pull model:** Management Activity API subscriptions per content type, polled every 5 minutes for new content blobs; Graph endpoints polled with time-window checkpoints. De-duplicate on the provider event id. Honor throttling and `Retry-After`.
- **Landing:** each record is stored as its original JSON in `raw`. Templates map common records to OCSF (sign-ins to Authentication 3002, directory changes to Account Change 3001, mailbox and file events to API Activity 6003 or File Activity 1001). Everything else lands under `unmapped` until a template covers it.
- **Classification:** new connector sources default to `local_only`.

## Consequences

- Adds an ingest worker with a scheduler and an encrypted settings store (both reused by later connectors).
- Microsoft content can arrive with delays of minutes to hours; the Sources page shows last successful pull and lag.
- Some data requires specific licensing (Entra ID P1/P2 for Graph sign-ins); the setup page detects and explains missing access instead of failing silently.
- Threat T21 (SPEC 7): mitigated by read-only permissions, certificate auth, encryption at rest, and rotation guidance. Not AI-facing; no ATLAS impact beyond the existing classification gate for any LLM use of this data.
