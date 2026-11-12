### Vendor alerts: an hourly cap and optional messages (2026-11-09)

- A source that sends alerts from another security tool can create up to 100 new alerts an hour. Past that, High and Critical alerts still appear; lower ones are stored and searchable but do not appear as alerts until the hour is back under 100.
- Health and Sources show a source over its cap with how many alerts were held, by severity. Its chosen alert targets get one message when the pause ends, with those counts.
- New: "Vendor alert messages" on such a source. "Notify alert targets" is off by default; when on, new alerts at or above a minimum severity (High unless changed) go to the targets you pick.
- What you will notice: nothing unless a vendor alert source sends more than 100 new alerts in an hour, or an admin turns on its messages.
- What changes for existing installs: nothing to do; messages stay off until an admin turns them on. The update adds four tables to the settings database. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the new tables, raises every vendor alert with no cap, and sends no vendor alert messages; the settings come back if you update again.
