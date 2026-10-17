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
| `diskcache` 5.6.3 (through `pysigma`) | PYSEC-2026-2447, GHSA-w8v5-vhqr-4h9v: pickle in the cache lets someone who can write the cache folder run code | pySigma only opens this cache in its rule validators (MITRE ATT&CK and D3FEND tag checks), which the server never runs. The cache folder would be under the service user's home, which is read-only in the container and outside `ReadWritePaths` under systemd. No fixed release exists | When pySigma or diskcache ship a fix |
| `braces` (dev only, through Tailwind's file watcher `chokidar`) | GHSA-rj75-hqrm-r3gf: deep nesting in a glob pattern exhausts the stack | Only the watcher in `pnpm dev` uses it, on the repository's own patterns. Not in the build output. No fixed release exists | When Tailwind 4 migration happens, or a fix ships |

Last full review: 2026-10-17 (`pip-audit` 2.9.0, `pnpm audit` with pnpm 10).
