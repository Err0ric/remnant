# Self-hosted CI runner

The `ci` workflow can run its jobs on a self-hosted runner instead of GitHub's hosted runners, to save the private repository's limited minutes (D217). Nothing changes until the repository variable `CI_RUNNER` is set: with it unset, every job stays on `ubuntu-latest`.

## How a job picks its runner

| Event | Runner |
|---|---|
| Pull request or push, `CI_RUNNER` unset or anything but `self-hosted` | `ubuntu-latest` |
| Pull request or push, `CI_RUNNER` = `self-hosted` | labels `self-hosted`, `remnant-ci` |
| Run workflow by hand (workflow_dispatch), input `runner` | what the input says; the default is `ubuntu-latest` |
| Pull request from a fork, or any run in a public repository | always `ubuntu-latest` |

Every job in `.github/workflows/ci.yml` uses the same `runs-on` expression, so the four jobs move together. The other workflows (`release-checks`, `scale`, `hooks-windows`) stay on hosted runners: they build images, install services, or need Windows.

## What each job does on the self-hosted runner

- Checks out with `clean: true` (an existing checkout is reset and every untracked file removed) and `persist-credentials: false` (no token left in `.git/config`).
- `scripts/ci/self-hosted.sh prep` points the uv cache, uv's Python installs, uv tools, the pnpm store, Playwright browsers, and the XDG folders at the job's temp folder (`RUNNER_TEMP`), which the runner empties at every job start. Nothing is written to the runner user's home.
- Installs its own toolchain every time: uv at the version pinned in `ci.yml`, Python 3.12 through uv (`UV_PYTHON_PREFERENCE=only-managed`, so a Python on the host is never used), Node at the exact `engines.node` in `frontend/package.json`, and pnpm at `packageManager`. All actions stay pinned by commit (`scripts/check-architecture.sh`).
- Writes its own temp files (JUnit report, requirements export, the layout check's lab folder) under `RUNNER_TEMP`, not `/tmp`.
- `scripts/ci/self-hosted.sh clean` runs last, also after a failure or a cancel: it stops servers started from the checkout's virtual environment and runs `git reset --hard` and `git clean -ffdx`, so venvs, `node_modules`, build output, and any `data/` folder are gone before the next job.
- Has a `timeout-minutes` (5 to 45) so a hung job frees the runner.
- Gets only `GITHUB_TOKEN` with `contents: read`. No other secret is used by `ci.yml`.

The workflow's concurrency group already cancels an older run of the same pull request or branch. One runner process runs one job at a time in its own work folder, so register **one runner per host or container**: the layout check binds `127.0.0.1:8080`, and two runners on one host would share it. A per-job concurrency group was left out on purpose: GitHub keeps only one pending job per group, so it would cancel other pull requests' queued jobs.

## Setting up the host

A Debian 13 or Ubuntu 24.04 VM or unprivileged LXC, 4 vCPU and 8 GB RAM or more (the backend suite is the long job), for example `ci01.example.internal`.

1. Create a dedicated user with no sudo and no other access:
   ```bash
   sudo adduser --disabled-password --gecos "" ci-runner
   ```
2. Install the system packages the jobs need, once, as root: `git`, `curl`, `ca-certificates`, `tar`, and the Chromium libraries the layout check needs (`cd backend && uv run playwright install-deps chromium` from any checkout, or the equivalent packages). Do not install Docker, Python, Node, or Chrome system-wide: the jobs bring their own, and a system Chrome would be picked up by the layout check.
3. As `ci-runner`, download the runner from the repository's **Settings > Actions > Runners > New self-hosted runner** page (Linux x64), check the SHA-256 shown there, and register it with the extra label:
   ```bash
   ./config.sh --url https://github.com/OWNER/REPO --token REGISTRATION_TOKEN \
     --name ci01 --labels remnant-ci --work _work --unattended
   ```
   The `self-hosted`, `Linux`, and `X64` labels are added automatically.
4. Install it as a service that runs as `ci-runner`: `sudo ./svc.sh install ci-runner && sudo ./svc.sh start`.

### Hardening

| Control | How |
|---|---|
| Non-root, single purpose | The `ci-runner` user owns only the runner folder; no sudo, no SSH keys to other hosts, nothing else runs on the host. |
| Fresh state per job | Preferred: register with `--ephemeral` so the runner takes one job and unregisters, and rebuild it from a snapshot or a script that fetches a new registration token. That needs a token with administration access to the repository stored on the host, so the simpler start is a persistent runner relying on the clean steps above, with the container rebuilt from a snapshot now and then. |
| No Docker socket | `ci.yml` builds no images. Do not add `ci-runner` to the `docker` group: socket access is root on the host. |
| Egress | Allow outbound HTTPS only to GitHub (github.com, its API, and the githubusercontent.com and Actions service hosts the runner reports on first start), the Python and npm package registries, and the Playwright browser download host. Deny everything else, including the internal network. No inbound ports are needed: the runner polls GitHub. |
| Forks | Self-hosted runs are refused for pull requests from forks by the `runs-on` expression, and the private repository has none. Never point a public repository at this runner. |
| Updates | Let the runner self-update (the default); patch the host OS on a schedule. |

## Turning it on and off

- On: **Settings > Secrets and variables > Actions > Variables > New repository variable**, name `CI_RUNNER`, value `self-hosted`. Or `gh variable set CI_RUNNER --body self-hosted`.
- Off (the runner is down, or a run is stuck waiting for it): delete the variable (`gh variable delete CI_RUNNER`) or set it to `ubuntu-latest`. A job already queued for the self-hosted labels keeps waiting; cancel it and push again, or run the workflow by hand.
- By hand: **Actions > ci > Run workflow**, input `runner`. `ubuntu-latest` (the default) is the fallback that always works.
