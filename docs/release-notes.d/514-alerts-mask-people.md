### AI watch alerts hide names without View people in AI usage (2026-11-11)

- On Alerts, a viewer without the **View people in AI usage** permission sees AI Watch alerts with "a person" in place of each name in the title, the details, and the changes, including alerts raised before this update. The People row says names are hidden, and "Person on device" gives the count without names. Rule, saved search, and source alerts are unchanged (ADR-0029 G2, D242).
- Muted AI Watch alerts are listed the same way, and closing an AI Watch alert as Approved still decides the agent, service, or MCP server it is about.
- Blocked-call and sensitive-data alerts about a machine where no person was seen now list the machine as a device, so it is shown as the machine, not hidden as a person; when a value may be a person, it is hidden. A mute keeps no device list, so a muted machine shows as "a person" there.
- Each Alerts list, alert view, and close, reopen, or mute answer that includes AI Watch alerts is audited `ai.view_people` when it showed names and `ai.view` when it did not (G3).
- What you will notice: without View people in AI usage, AI watch alerts show "a person" or the machine instead of names, including alerts raised before this update. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing already stored changes; names are hidden when an alert is read. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
