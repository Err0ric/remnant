# remnant

Local-first, LLM-assisted SIEM front end. Bring your own logs, bring your own model.

> Status: Slice 1 in progress. Not ready for use. "Remnant" is a working codename.

Point it at log files you already have. Templates parse them into OCSF columns in a Parquet lake, DuckDB queries them, Sigma detects on them, and an LLM (local by default) helps write parsers and queries and explains results with citations back to real events.

## Docs

| Doc | What it covers |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | Architecture, schemas, threat model, roadmap, decisions |
| [docs/DESIGN.md](docs/DESIGN.md) | UI tokens, typography, component patterns |
| [CLAUDE.md](CLAUDE.md) | Build rules, conventions, tests, definition of done |
| [docs/install/homelab-test.md](docs/install/homelab-test.md) | First run on one VM with made-up logs |
| [docs/install/team-trial-loki.md](docs/install/team-trial-loki.md) | A team trial on a shared VM reading from Grafana Loki, with no data leaving the network |
| [docs/ingest/](docs/ingest/) | Pointing rsyslog, syslog-ng, Vector, or Loki at the app |

## Development

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm.

```bash
make dev-backend    # API on http://127.0.0.1:8080
make dev-frontend   # UI on http://127.0.0.1:5173 (proxies /api)
make ci             # architecture checks, lint, types, tests, build
```

Runs single-user on a laptop or VM, or as a shared team VM with individual accounts, roles, and per-source access. Anything reachable from the network requires login; there is no insecure mode. On first network-facing start, the server prints a one-time link to create the administrator account (being built in Slice 1, see [ADR-0001](docs/adr/ADR-0001-container-bind.md)).

### Try it with your own logs (early preview)

```bash
cd backend
uv run app-admin ingest /var/log/auth.log --source linux_auth          # syslog is the default
uv run app-admin ingest events.jsonl --source winlogbeat --format json
uv run app-server                                                       # API on 127.0.0.1:8080

# in another terminal
uv run remnant login --server https://siem.corp.example:8080   # once; token goes to the OS keychain
uv run remnant tail linux_auth -n 20
uv run remnant tail linux_auth -f --where "message LIKE 'Failed%'"
uv run remnant query "SELECT device_hostname, count(*) FROM events GROUP BY 1" -o csv
```

`app-admin ingest` does a one-off load; for continuous tailing add a source with `POST /api/sources` (UI page coming). The CLI only talks to the server API, with the same SQL guard as the web UI. Output formats: `table`, `json` (one object per line), `csv`, `raw`.

### Docker

```bash
cp .env.example .env    # optional: LOGS_DIR, APP_PUBLIC_NAME
docker compose up --build
docker compose logs app | grep -A1 "one-time link"   # open it to create the admin account
docker compose --profile ollama up    # with a local Ollama
```

The app serves HTTPS (self-signed on first start, fingerprint printed in the log) and is published on `127.0.0.1:8080` by default. The first start prints a single-use link, valid for 30 minutes, that creates the administrator account. Lost the admin password? `docker compose exec app app-admin reset-password <username>`. See [docs/install/tls.md](docs/install/tls.md) for your own certificate.

## License

Apache 2.0
