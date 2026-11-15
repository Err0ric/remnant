### Quiet is normal for sources that send only while people work (2026-11-14)

- An OpenTelemetry or syslog listener source can be set to "Quiet is normal for up to" 1, 3, 7, 14, or 30 days, under its status on Settings > Sources (administrators).
- Inside those days a silent source counts as healthy. Health and Sources say "Idle" with how long it has been, and the Dashboard does not list it under Needs you.
- Errors, a listener that is down, refused records, and quiet or gap alerts still count. A source silent for longer than its days, or one that never sent, reads as quiet as before.
- A quiet alert still fires inside those days. Collector OpenTelemetry sources and syslog listener sources get a 1-hour quiet alert when they are added, so marking one of them changes nothing after an hour of silence until you turn that alert off or lengthen it; the setting says so when the source has a quiet alert on.
- New Claude Code sources start at 7 days.
- What you will notice: Claude Code sources nobody used for a day read "Idle" and no longer lower Sources healthy, once marked.
- What changes for existing installs: nothing until an administrator marks a source; you may want to set your existing Claude Code sources to 7 days on Settings > Sources. Going back to the previous version leaves the new setting unused (`docs/install/`, `update-systemd.sh --rollback`).
