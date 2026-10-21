# ADR-0024: Hand selected events to another system through an alert target

Status: **Accepted** 2026-10-17 (project owner: "send selected events to a webhook" instead of a DFIR-IRIS or TheHive integration; "merge go"). Recorded as SPEC D63; threat T55 added.

## Context

Slice 8 lists case handoff to TheHive, DFIR-IRIS, or a webhook. A one-person team rarely runs a case tool; they track work in a ticket system, a chat channel, or a mailbox. Alert targets already reach all of those (ADR-0007), but alerts are summaries by design: no event content. Handing events to a person or a system is a deliberate act by an analyst and needs the events themselves.

## Decision

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Where events go | Any existing alert target. One click: select events in Search, **Send N**, pick a target, add a note | Reuses targets the admin already approved; no new outbound destinations |
| 2 | What is sent | Webhooks: each event as JSON (time, source, classification, severity, class, message, user, host, addresses, ports, and `raw` capped at 4 KB), signed like other webhook alerts. Teams, Slack, email: a short list (up to 20 lines with event ids) and the note, escaped like every alert | Machines get the data; people get something readable |
| 3 | How many | 1 to 100 events per send | Enough for a case; small enough to stay a deliberate act |
| 4 | Scope | Events are read again on the server from the caller's own `events` view; ids the caller cannot read are not found | Rule 13 |
| 5 | Classification | Events from `local_only` sources go only to targets whose every address is private (a webhook or mail server on the internal network). For any other target they are withheld and counted, and the analyst is told | `local_only` means the data stays inside; chat services are outside |
| 6 | Who | Admins and analysts. Every send, including a refused one, is audited (`handoff.send`) with the event ids, target, and withheld count | Rule 14 |
| 7 | TheHive and DFIR-IRIS | Not built. Both accept webhooks or can be fed by one; native integrations wait until someone asks | Thin slice |

## Consequences

- `Alert` gains an optional `events` field used only by `handoff`; the webhook body carries `events` only for that kind. ADR-0007's "no event content" still holds for every automatic alert.
- Queued deliveries hold the events in `alert_deliveries` until sent (and in the last 50 kept), inside `meta.sqlite`.
- The private-address check happens when the analyst sends; the send step checks the destination again as for every alert.
- ATT&CK: none new. Not AI-facing: no model sees the note or the events; no ATLAS mapping.
- Threats: T55 (an analyst sends events they can read to a destination outside the network: only admin-approved targets, local_only withheld from non-private targets, every send audited).
