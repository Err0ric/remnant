# Dependency vulnerability checks

CI checks the packages that ship for known vulnerabilities on every pull request:

| Side | Check | Fails the build when |
|---|---|---|
| Backend | `pip-audit` over the locked runtime packages (`uv export --no-dev`), PyPI advisory data | Any runtime package has a known vulnerability not listed below |
| Frontend | `pnpm audit --prod` | Any package in the web bundle has a known vulnerability |

Development and build tools (test runners, Tailwind, Vite) are not shipped. Their advisories are reviewed by hand and fixed with `overrides` in `frontend/pnpm-workspace.yaml` once a fixed release is at least 14 days old (security rule 11).

## Accepted findings

| Package | Advisory | Why it is accepted | Review again |
|---|---|---|---|
| `certifi` 2026.7.22 | PYSEC-2026-4320, GHSA-6q48-6c7w-9gw2: the bundle still trusts `emSign ECC Root CA - G3`, whose revoked intermediates had compromised keys, so an on-path attacker holding one could pass as any host on outbound HTTPS (feeds, connectors, alert targets, AI providers) | The fixed release, 2026.10.19, is younger than the 14-day rule (security rule 11). Exploiting this needs both a stolen key and a position on the network path. Accepted for those 14 days only, while no install is in production; the lockfile moves to 2026.10.19 once it is 14 days old | 2026-11-02: bump `certifi` to 2026.10.19 and remove this row and the CI ignore |
| `diskcache` 5.6.3 (through `pysigma`) | PYSEC-2026-2447, GHSA-w8v5-vhqr-4h9v: pickle in the cache lets someone who can write the cache folder run code | pySigma only opens this cache in its rule validators (MITRE ATT&CK and D3FEND tag checks), which the server never runs. The cache folder would be under the service user's home, which is read-only in the container and outside `ReadWritePaths` under systemd. No fixed release exists | When pySigma or diskcache ship a fix |
| `braces` (dev only, through Tailwind's file watcher `chokidar`) | GHSA-rj75-hqrm-r3gf: deep nesting in a glob pattern exhausts the stack | Only the watcher in `pnpm dev` uses it, on the repository's own patterns. Not in the build output. No fixed release exists | When Tailwind 4 migration happens, or a fix ships |

Last full review: 2026-10-17 (`pip-audit` 2.9.0, `pnpm audit` with pnpm 10).
