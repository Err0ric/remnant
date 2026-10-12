# remnant

Local-first, LLM-assisted SIEM front end. Bring your own logs, bring your own model.

> Status: early preview (Slices 1 to 5 built, Slice 6 polish nearly done). Expect rough edges. "Remnant" is a working codename.

Point it at log files you already have. Templates parse them into OCSF columns in a Parquet lake, DuckDB queries them, Sigma detects on them, and an LLM (local by default) helps write parsers and queries and explains results with citations back to real events.

![Overview: event volume per source, ingest health, flagged detections](docs/images/overview.png)

| | |
|---|---|
| ![Simple search for failed SSH passwords](docs/images/search.png) | ![Dashboard of scheduled searches with flags](docs/images/dashboard.png) |
| **Search.** Type `sshd "failed password"`, or SQL, or ask in plain English with a local model; the SQL is always shown before it runs | **Dashboard.** Scheduled searches and Sigma rules with thresholds, sparklines, and alerts to email, Teams, Slack, or a webhook |
| ![Command palette](docs/images/command-palette.png) | ![Light theme](docs/images/overview-light.png) |
| **Ctrl+K** goes to any page, saved search, or source | A complete light theme as well as dark |
| ![Sign-in with Microsoft](docs/images/sign-in-sso.png) | ![Terminal UI](docs/images/terminal.png) |
| Optional sign-in with Microsoft Entra ID or any OIDC provider | `remnant tui`: query, results, and a live tail in the terminal |

Screenshots use made-up logs from `scripts/loggen.py`.

## What it does

- **Bring your own logs.** Files and folders (rsyslog, syslog-ng, Vector), JSON lines, CSV, Windows EVTX and forwarded events, or a Grafana Loki you already run. 24 starter parsers (Linux auth, Palo Alto, Fortinet, UniFi, Cisco ASA and IOS, CEF, LEEF, Windows, DNS) and an Automatic parser for mixed streams.
- **Search three ways** over one engine: Simple search, SQL (read-only, guarded), or Ask in plain English.
- **Detect** with imported SigmaHQ rules and scheduled searches; alert to email, Teams, Slack, or a signed webhook.
- **Bring your own model.** Ollama, LM Studio, llama.cpp, vLLM, or any OpenAI-compatible API, plus Anthropic. Fresh installs allow local models only. Each source is Local only or Cloud allowed, and Local only data is blocked from cloud models in code.
- **Treats log content as hostile.** The model never reads the whole dataset, never runs anything on its own, and every claim it makes cites event ids that are checked.
- **Team ready.** Accounts, roles, per-source access, an append-only audit log, HTTPS by default, optional single sign-on, online backups.

## Docs

| Doc | What it covers |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | Architecture, schemas, threat model, roadmap, decisions |
| [docs/DESIGN.md](docs/DESIGN.md) | UI tokens, typography, component patterns |
| [CLAUDE.md](CLAUDE.md) | Build rules, conventions, tests, definition of done |
| [docs/install/single-user.md](docs/install/single-user.md) | One person on a laptop or workstation, from source or Docker |
| [docs/install/team-vm.md](docs/install/team-vm.md) | A shared server with accounts and roles, with Docker Compose or as a systemd service |
| [docs/install/homelab-test.md](docs/install/homelab-test.md) | First run on one VM with made-up logs |
| [docs/install/team-trial-loki.md](docs/install/team-trial-loki.md) | A team trial on a shared VM reading from Grafana Loki, with no data leaving the network |
| [docs/install/sso-entra.md](docs/install/sso-entra.md) | Optional sign-in with Microsoft Entra ID (or another OIDC provider): invite first, group check, passwords kept for administrators |
| [docs/install/backup.md](docs/install/backup.md) | Back up and restore the data folder while the server runs, nightly cron, moving to a new server |
| [docs/ingest/](docs/ingest/) | Pointing rsyslog, syslog-ng, Vector, or Loki at the app |

## Development

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm.

```bash
make dev-backend    # API on http://127.0.0.1:8080
make dev-frontend   # UI on http://127.0.0.1:5173 (proxies /api)
make ci             # architecture checks, lint, types, tests, build
```

Runs single-user on a laptop or VM, or as a shared team VM with individual accounts, roles, and per-source access. Anything reachable from the network requires login; there is no insecure mode. On first network-facing start, the server prints a one-time link to create the administrator account ([ADR-0001](docs/adr/ADR-0001-container-bind.md)).

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
uv sync --extra tui && uv run remnant tui --source linux_auth   # full-screen: query box, results, live tail
```

`app-admin ingest` does a one-off load; for continuous tailing add a source on the **Sources** page. The CLI only talks to the server API, with the same SQL guard as the web UI. Output formats: `table`, `json` (one object per line), `csv`, `raw`.

### Docker

```bash
cp .env.example .env    # optional: LOGS_DIR, APP_PUBLIC_NAME
docker compose up --build
docker compose logs app | grep -A1 "one-time link"   # open it to create the admin account
docker compose --profile ollama up    # with a local Ollama
```

The app serves HTTPS (self-signed on first start, fingerprint printed in the log) and is published on `127.0.0.1:8080` by default. The first start prints a single-use link, valid for 30 minutes, that creates the administrator account. Lost the admin password? `docker compose exec app app-admin reset-password <username>`. See [docs/install/tls.md](docs/install/tls.md) for your own certificate.

## Tested scale

Measured with `scripts/bench.py` (synthetic syslog through the real ingest path with the Automatic parser, then searches through the real query API), on a 2 vCPU Intel Xeon 2.1 GHz cloud VM with 8 GB RAM:

| Measure | Result |
|---|---|
| Ingest | about 9,600 events/s for one source (854,316 events in 89 s) |
| Storage | 117.7 MB of raw syslog became a 54.1 MB lake (2.2x smaller), raw lines kept |
| Count, group by host, failed logins by IP | 40 to 45 ms |
| Text search in `message` (`ILIKE`) | 270 ms |
| Latest 100 events, all columns | 340 ms |

On a 4 vCPU Proxmox container (AMD Ryzen 9 5950X host, 8 GB RAM), the same run gave about 14,700 events/s; 16 to 19 ms for count, group by host, and failed logins by IP; 96 ms for the text search; and 110 ms for the latest 100 events.

Run it on your own hardware with `cd backend && uv run python ../scripts/bench.py --events 1000000`. A Loki source reads at most 20,000 lines per 30 s poll (about 650 lines/s), well inside the ingest rate.

## Software bill of materials

Every CI run publishes `sbom.cdx.json` (CycloneDX 1.5) as a build artifact: the Python packages and web UI packages that ship in the image, with hashes, plus the container base images. Development tools are left out. To make one locally:

```
cd backend && uv run python ../scripts/sbom.py --out ../sbom.cdx.json
```

It is built from `uv.lock`, `pnpm-lock.yaml`, and the `Dockerfile`, so the same commit always gives the same file.

## Security

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## License

Apache 2.0
