### An external alert lists every vendor alert it groups (2026-11-09)

- An alert from another security tool shows how many vendor alerts it groups and the first 50 of their IDs; Show all loads the rest 200 at a time.
- Show alert events lists those alerts' own lines, newest first, read only from the alert's sources and time range.
- A resend or a higher severity on any grouped vendor alert updates the same alert.
- What you will notice: external alerts have a Vendor alerts list and a Show alert events button in their Evidence section.
- What changes for existing installs: nothing to do. The update adds one index to the settings database; to go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the index, and external alerts show their Evidence as before.
