# Sending events to someone else

Search can hand selected events to a ticket system, a chat channel, or a mailbox through an existing alert target (ADR-0024).

1. Run a search, click a row, and **Select** each event you want (up to 100).
2. Click **Send N** in the results bar.
3. Pick the target, write a note for whoever picks it up, and **Send**.

| Target | What arrives |
|---|---|
| Webhook | JSON signed like other webhook alerts (`X-Signature-256`), with `kind: "handoff"`, the note in `detail`, and `events`: time, source, classification, severity, class, message, user, host, addresses, ports, and the raw line (first 4 KB) |
| Teams, Slack, email | The note and up to 20 lines (time, source, message, event id), escaped |

Events from **local-only** sources go only to targets whose every address is on your own network (an internal webhook or mail server). For Teams, Slack, or an outside mail server they stay here, and the result says how many were held back. To send them anyway, mark the source **Cloud allowed** on its settings, knowing that this also lets cloud AI providers read it.

Admins and analysts can send. Every send, refused or not, is in the audit log as `handoff.send` with the event ids and the target.

**Feeding TheHive or DFIR-IRIS:** point a webhook target at a small relay or automation that creates an alert or case from the JSON; both products accept alerts over their APIs.
