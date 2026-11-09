### Daily backups by the server (2026-11-08)

- The server now backs up its data folder every day at 02:15 (install time zone) and keeps the last 14, with no cron entry or script. Administrators change the time, the count, or turn it off under Settings, About and licenses, Backups; every change is in the audit log.
- Health has a Backups tab: the last run in your local time (UTC on hover), its result and size, how many are on disk, and the next run. A failed run shows as Unhealthy with the reason.
- With no successful backup for 48 hours, one alert opens on Alerts; the next successful backup closes it.
- Old backups are deleted only after a new one succeeds. A run that would leave the disk nearly full is skipped and shown on Health instead. A restore now leaves the `backups/` folder in place.
- The install guides (backup.md, team-vm.md, single-user.md) say where backups are, how to restore one, what a backup holds, and how a restore and a rollback differ.
- What you will notice: a Backups tab on Health and a Backups section in Settings, About and licenses; backup files appear in the data folder's `backups/` after the first 02:15.
- What changes for existing installs: backups turn on automatically; the first one runs at the next 02:15 after the update, never at once. They use disk space in the data folder (about 14 times one backup); set `APP__BACKUP__DIR` to put them elsewhere, or turn them off in Settings. Your hand-made backups are never deleted. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the new settings and leaves the backup files in place for you to keep or delete.
