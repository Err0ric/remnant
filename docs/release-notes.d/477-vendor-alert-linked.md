### Vendor alerts: a rise after a close opens a new alert, and a starter CEF alert parser (2026-11-10)

- When another security tool resends an alert at a higher severity after you closed it, a new alert opens. It says how the earlier one was closed and links to it; the closed alert and its reason stay as you left them.
- New starter parser "CEF security alerts" for sources that receive only alerts from another security tool in CEF. It is never picked automatically: choose it for the source.
- What you will notice: a closed vendor alert that comes back more severe now shows as a new alert with a "Follows" link, where before nothing appeared.
- What changes for existing installs: nothing to do. The update adds one column to the settings database. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the new column, does not open new alerts for a rise after a close, and does not list the new parser, so pick another parser for a source that used it before rolling back.
