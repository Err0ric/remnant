# Single user on a laptop or workstation

For one person, on one machine, reading log files on that machine. Nothing is reachable from the network.

| | From source (no Docker) | Docker |
|---|---|---|
| Sign-in | None: loopback only, so the app treats you as the local administrator | One administrator account, created from a one-time link |
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

Open `http://127.0.0.1:8080`. `APP__PATHS__ALLOWED_ROOTS` lists the folders the app may read (comma-separated); sources can only point inside them. Data goes to `backend/data/` unless `APP__PATHS__DATA_DIR` says otherwise.

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

## Next steps

- **Sources > Add source** for each log file or folder (the Automatic parser handles mixed syslog)
- **AI providers** to add a local model for Ask, such as Ollama (`docker compose --profile ollama up -d` starts one); for reasoning models set **Thinking** to **Off**
- [homelab-test.md](homelab-test.md) walks through every screen with made-up logs
