# Backup and restore

Everything the server knows lives in one data folder: the event lake, settings, users, source groups, saved searches, rules, the audit log, your own parser templates, the generated TLS certificate, and `.key`, which encrypts stored secrets (AI provider keys, alert target secrets, Loki passwords).

`app-admin backup` copies all of it into one `.tar.gz` while the server keeps running.

| Part | How it is copied |
|---|---|
| Database (`meta.sqlite`) | SQLite's online backup, so it is consistent even mid-write |
| Event lake | File by file while compaction and retention are paused; events arriving during the copy may or may not be included |
| `.key` | Included by default. `--no-key` leaves it out, for copies kept somewhere less trusted; restoring one of those means re-entering stored secrets |
| Check | A manifest with a SHA-256 for every file. `verify-backup` and `restore` check them all before trusting the file |

A backup with the key can decrypt every stored secret. Keep it as safe as the server itself: owner-only permissions, encrypted storage, and not on the same disk as the server.

## Docker Compose

Back up (the server can keep running):

```bash
cd /opt/remnant
mkdir -p /var/backups/siem && chmod 700 /var/backups/siem
umask 077
docker compose exec -T app app-admin backup -o - > /var/backups/siem/backup-$(date +%F).tar.gz
```

Check a backup without restoring it:

```bash
docker compose run --rm -T --no-deps app app-admin verify-backup - < /var/backups/siem/backup-2026-10-12.tar.gz
```

Restore (stop the server first):

```bash
docker compose stop app
docker compose run --rm -T --no-deps app app-admin restore --replace - < /var/backups/siem/backup-2026-10-12.tar.gz
docker compose start app
```

`--replace` does not delete what was there: the previous contents move to `.before-restore-<time>/` inside the data volume. Remove that folder once the restored server looks right:

```bash
docker compose exec app sh -c 'rm -rf /srv/data/.before-restore-*'
```

## systemd install

```bash
sudo install -d -m 0700 -o remnant -g remnant /var/backups/remnant
sudo -u remnant sh -c 'set -a; . /etc/remnant/remnant.env; set +a; exec /opt/remnant/backend/.venv/bin/app-admin "$@"' app-admin \
  backup -o /var/backups/remnant/backup-$(date +%F).tar.gz
```

The settings file is read by the `remnant` user, which may read it (mode 0640, group `remnant`). Reading it before `sudo` (for example `env $(grep ... remnant.env)`) runs as you, fails on the permissions, and the command then starts with no settings, silently.

Restore: `systemctl stop remnant`, run the same command with `restore --replace <file>` instead of `backup -o <file>`, then `systemctl start remnant`.

## Scheduled backups

The server makes a backup every day by itself, on new and existing installs. Nothing to set up.

| | Default | Where to change it |
|---|---|---|
| On or off | On | **Settings > About and licenses > Backups** (administrators; every change is in the audit log with who made it) |
| Time of day | 02:15, in the install's time zone (`APP__SCHEDULES__TIMEZONE`) | Same |
| How many are kept | 14 | Same, 1 to 90 |
| Folder | `backups/` in the data folder: `/var/lib/remnant/backups` (systemd), `/srv/data/backups` in the `app-data` volume (Docker), `backend/data/backups` (from source) | `APP__BACKUP__DIR` in the settings file, for example a mounted NAS share the service user can write |

- Files are named `scheduled-<UTC time>.tar.gz`, mode 0600, the same format as `app-admin backup` (with the key). A file appears only once it is complete.
- The oldest scheduled files beyond the count are deleted only after a new backup succeeds. A failed or skipped run deletes nothing. Files with other names (backups you made by hand) are never deleted.
- Before each run the free space is checked. If the backup (about the size of the last one) would leave less than 5% of the disk or 1 GiB free, the run is skipped and Health says so. Free some space or keep fewer.
- If the server was stopped at the backup time, it runs when the server is back that day. After an update or a change in Settings, the first backup is at the next backup time, never at once.
- **Health > Backups** shows the last run (local time, UTC on hover), its result and size, how many are on disk, and the next run. A failed run shows as Unhealthy with the reason.
- With no successful backup for 48 hours, one alert opens on **Alerts** ("No successful backup in 48 hours"). It stays the only one until a backup succeeds, which closes it as Resolved.
- Backups never include the backup folder, and a restore leaves it where it is.

Scheduled backups include `.key`, so a share that `APP__BACKUP__DIR` points at must be readable by admins and the service user only, never a general file share (D227). The backups sit on the same disk as the data unless `APP__BACKUP__DIR` points elsewhere. They protect against a bad change or a damaged database, not a lost disk: copy the folder off the host with whatever you already use (a NAS share, restic, borg, your backup agent), and run `verify-backup` on a copy now and then. A backup nobody has ever restored is a hope, not a backup.

## Restoring a scheduled backup

List them, newest last:

```bash
sudo ls -l /var/lib/remnant/backups                      # systemd
docker compose exec app ls -l /srv/data/backups          # Docker
```

Restore one (stop the server first; the current contents move to `.before-restore-<time>/`, not deleted):

```bash
# systemd
systemctl stop remnant
sudo -u remnant sh -c 'set -a; . /etc/remnant/remnant.env; set +a; exec /opt/remnant/backend/.venv/bin/app-admin "$@"' app-admin \
  restore --replace /var/lib/remnant/backups/scheduled-20261108T101500Z.tar.gz
systemctl start remnant

# Docker
docker compose stop app
docker compose run --rm --no-deps app app-admin restore --replace /srv/data/backups/scheduled-20261108T101500Z.tar.gz
docker compose start app
```

Restore checks every file first and changes nothing if any check fails (table below).

## What is and is not in a backup

| In it | Not in it |
|---|---|
| The event lake, the settings database (users, groups, sources, saved searches, rules, alerts, the audit log), your own parser templates, the generated TLS certificate, enrichment files, `.key` | The settings file (`/etc/remnant/remnant.env` or `.env`) and the unit file: keep your own copy |
| | The code: restore runs on whatever version is installed |
| | Page rollups and the query spill folder: rebuilt by the server |
| | Other backups, `quarantine/`, and `.before-restore-*` folders |

## Backups and rolling back

`update-systemd.sh --rollback` (D226) changes the code only; it never restores a backup, and a restore never changes the code. The two are separate:

- **Bad update, data fine:** roll back. The data folder and the backups stay.
- **Data damaged or a bad change, code fine:** restore a backup made before it.
- **Both:** roll back first, then restore a backup made by that older version or earlier. A backup made after the update is refused by the older version ("This backup is from a newer version"); restore it after rolling forward instead.

Scheduled backups go on after a rollback only if the older version has them. Versions before this one leave the backup folder alone: the files stay, but nothing new is made or deleted until you roll forward.

## What restore refuses

| Situation | What happens |
|---|---|
| Any file's checksum does not match, an entry is missing, or an entry has an unsafe path | Nothing is written; the message names the file |
| The data folder has data and `--replace` was not given | Nothing is written |
| The backup came from a newer version (its database schema is ahead of this code) | Nothing is written; update the code first |
| The backup came from an older version | Restored; database changes are applied at the next start, as with any update |

## Moving to a new server

1. On the old server, take a backup.
2. Install on the new server (team-vm.md), but do not open the setup link.
3. Stop the new server, restore the backup with `--replace`, start it again.
4. If the new server has a different name, set `APP_PUBLIC_NAME` (and update the redirect URI in Entra if you use [single sign-on](sso-entra.md)). Delete `tls/` in the data folder before starting if you want a new self-signed certificate for the new name.

## Damaged files after a crash

Events are flushed to disk before a file is published, so a power cut leaves either a complete file or none. A file found empty or unreadable anyway (written by a version before this, or a disk fault) is moved to `data/quarantine/<source>/<day>/`, outside what searches read, and the Health page shows how many under **Sources > Data folder**. Nothing there is deleted automatically. Empty files hold nothing and can be removed; for anything else, check the disk, and restore the day from a backup if it matters.
