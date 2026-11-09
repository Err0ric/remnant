### Roll back a systemd install with one command (2026-11-08)

- `sudo sh /opt/remnant/scripts/update-systemd.sh --rollback` puts a systemd install back on the version it ran before the last update: it stops the service, checks that commit out, rebuilds the web UI and Python packages, starts the service, and prints the startup lines. It goes back one update only, and refuses with nothing changed when no previous version is recorded or tracked files were edited by hand. The next ordinary update rolls forward.
- Every successful update now keeps the commit it replaced in `previous_commit` next to `installed_commit`, written by root under the same rules.
- An older version started on a database a newer version migrated logs `meta.schema_newer` and leaves the newer tables and columns alone. A source of a kind this version does not know is skipped with a warning instead of stopping ingest for every source, and keeps its retention.
- The install guides have Rolling back sections for systemd, Docker Compose, and single-user installs, with what happens to data and migrations.
- What you will notice: nothing visible.
- What changes for existing installs: the update after this one records the first rollback target, in `previous_commit` in the data folder (the update that installs this version runs the old script). AIDE checks treat that file and `rolled_back_from` like `installed_commit`.
