# Development

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm.

```bash
make dev-backend    # API on http://127.0.0.1:8080
make dev-frontend   # UI on http://127.0.0.1:5173 (proxies /api)
make ci             # architecture checks, lint, types, tests, build
make demo           # synthetic demo install on http://127.0.0.1:8090 (build the frontend first)
```

## Demo and screenshots

`make demo` (`scripts/demo/run.sh`) replaces `data/demo/` with two weeks of synthetic logs from `scripts/demo/generate.py`, starts a server on loopback with no accounts, and loads it with `scripts/demo/load.py`: one file source per log type, an OTLP source with Claude Code hook and telemetry records, a synthetic GeoIP file, and some AI services and MCP servers reviewed. `DEMO_DETACH=1` leaves the server running and returns; `DEMO_PORT` changes the port.

The demo turns on `enrichment.place_documentation_ranges` so its GeoIP file can place documentation addresses (D157). Never set it on a real install.

`scripts/screenshots/capture.py` takes the README screenshots from a running demo (Python Playwright with Chromium) and `scripts/screenshots/social.py` builds `docs/images/social-preview.png` (upload it under the repository's Settings > Social preview). Ask and Explain are answered by `scripts/screenshots/stand_in_model.py`, a scripted stand-in that is not an LLM, added as a provider named "Scripted demo model (not an LLM)".

## Command line

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

Scripts and other tools can call the same JSON API with a personal token: see [docs/api.md](docs/api.md).

`app-admin ingest` does a one-off load; for continuous tailing add a source on the **Sources** page. The CLI only talks to the server API, with the same SQL guard as the web UI. Output formats: `table`, `json` (one object per line), `csv`, `raw`.


## Software bill of materials

Every CI run publishes `sbom.cdx.json` (CycloneDX 1.5) as a build artifact: the Python packages and web UI packages that ship in the image, with hashes, plus the container base images. Development tools are left out. To make one locally:

```
cd backend && uv run python ../scripts/sbom.py --out ../sbom.cdx.json
```

It is built from `uv.lock`, `pnpm-lock.yaml`, and the `Dockerfile`, so the same commit always gives the same file.


## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for how to add a parser template, run the tests, and open a pull request.
