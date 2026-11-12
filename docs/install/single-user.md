# Single user on a laptop or workstation

For one person, on one machine, reading log files on that machine. Nothing is reachable from the network.

| | From source (no Docker) | Docker |
|---|---|---|
| Sign-in | One administrator account, created from a one-time link | One administrator account, created from a one-time link |
| Address | `http://127.0.0.1:8080` | `https://127.0.0.1:8080` (self-signed certificate) |
| Needs | Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 | Docker with Compose |
| Best for | Trying it quickly, development | Keeping it separate from the rest of the machine |

## From source

```bash
git clone https://github.com/Err0ric/remnant && cd remnant
cd frontend && corepack enable && pnpm install --frozen-lockfile && pnpm build && cd ..
cd backend && uv sync --frozen --no-dev
APP__SERVER__STATIC_DIR=../frontend/dist \
APP__PATHS__ALLOWED_ROOTS=/var/log \
uv run app-server
```

The first start prints a one-time link (valid 30 minutes) that creates your administrator account; open it in a browser on the same machine, then sign in at `http://127.0.0.1:8080`. For a new link, run `uv run app-admin setup-link` in `backend/` with the same environment. There is no mode without sign-in: a local address alone does not prove who is asking (a reverse proxy on the same machine looks the same).

`APP__PATHS__ALLOWED_ROOTS` lists the folders the app may read (comma-separated); sources can only point inside them. Data goes to `backend/data/` unless `APP__PATHS__DATA_DIR` says otherwise.

The server listens on `127.0.0.1` only. Setting `APP__SERVER__HOST=0.0.0.0` turns on HTTPS and the administrator setup link, as on a team VM ([team-vm.md](team-vm.md)).

## Docker

```bash
git clone https://github.com/Err0ric/remnant && cd remnant
cp .env.example .env          # set LOGS_DIR to the folder with your logs
docker compose up --build -d
docker compose logs app | grep -A1 "one-time link"
docker compose logs app | grep "SHA-256"
```

Open the link (it is single-use and expires in 30 minutes) and compare the certificate fingerprint in the browser warning with the log line before continuing. The folder in `LOGS_DIR` appears inside the app as `/logs`.

## Updating and rolling back

Before a major update, take a snapshot of the VM or container if your platform supports it; the rollback command only covers versions installed after this one.

From source: `git pull`, then the build commands above again. Docker: the update command in [team-vm.md, Docker Compose](team-vm.md#a-docker-compose). To roll back, check out the earlier commit (`git checkout --detach <commit>`; `git reflog` lists where the checkout has been) and build the same way; `git checkout main` before the next update rolls forward. Your data stays; see [What rolling back does to your data](team-vm.md#what-rolling-back-does-to-your-data).

## Backups

The server backs up its data folder every day at 02:15 and keeps 14: `backend/data/backups/` from source, `/srv/data/backups` in the Docker volume. **Settings > About and licenses > Backups** changes the time and count; **Health > Backups** shows the last run. To restore one, stop the app, run `uv run app-admin restore --replace data/backups/<file>` in `backend/` (Docker: `docker compose run --rm --no-deps app app-admin restore --replace /srv/data/backups/<file>`), and start it again. A backup holds events, settings, and the key for stored secrets, not the code; rolling back the code never touches it. On a laptop the backups share its disk, so copy the folder somewhere else as well. Details: [backup.md](backup.md).

## Next steps

- **Sources > Add source** for each log file or folder (the Automatic parser handles mixed syslog)
- **AI providers** to add a local model for Ask, such as Ollama (`docker compose --profile ollama up -d` starts one); for reasoning models set **Thinking** to **Off**
- [homelab-test.md](homelab-test.md) walks through every screen with made-up logs

The settings database uses a write-ahead log: a power loss or OS crash can drop the last second or two of changes, never damage the database. Details: [team-vm.md, Power loss and the settings database](team-vm.md#power-loss-and-the-settings-database).
