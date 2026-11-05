### AIDE: the spool folder is skipped, and hashes are no longer read as paths (2026-11-03)

- The AIDE rules the update script writes now skip the data folder's `spool/`, where incoming syslog and OpenTelemetry messages wait to be ingested.
- `update-systemd.sh --aide` no longer mistakes a hash in AIDE's detailed report for a changed file outside the install, which could stop an update for no reason.
- What changes for existing installs: the next update rewrites `/etc/aide/aide.conf.d/90_aide_remnant` with the new rule and says so; re-baseline as usual.
