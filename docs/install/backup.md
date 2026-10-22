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

## Nightly backups

A root cron entry for the Compose install that keeps 14 days:

```
# /etc/cron.d/siem-backup
15 2 * * * root cd /opt/remnant && umask 077 && docker compose exec -T app app-admin backup -o - > /var/backups/siem/backup-$(date +\%F).tar.gz && find /var/backups/siem -name 'backup-*.tar.gz' -mtime +14 -delete
```

Copy the files off the host with whatever you already use for that (a NAS share, restic, borg, your backup agent). Run `verify-backup` on a copy now and then; a backup nobody has ever restored is a hope, not a backup.

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
