### Quiet alerts off on existing Claude Code sources (2026-11-02)

- On the first start after this update, the server turns off the 1-hour quiet alert on existing OpenTelemetry sources that still have it exactly as it was set when the source was added (no alert targets, never edited). Quiet alerts you changed are kept. Each change is in the audit log as `source.quiet_alert_change`, with the reason.
- What changes for existing installs: nothing to do. If an OpenTelemetry source receives from collectors that send all the time and you want its quiet alert back, turn it on again on **Sources**.
