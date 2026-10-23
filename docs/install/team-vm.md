# Team VM

One server that several analysts use from their browsers, each with their own account, role, and source access. Two ways to run it; pick one.

| | Docker Compose (recommended) | systemd service |
|---|---|---|
| Runs as | A container, user `app` (uid 10001) | A system user `remnant` |
| Updates | `git pull` and rebuild the image | `git pull`, rebuild the UI, sync Python packages, restart |
| Data | Docker volume `app-data` | `/var/lib/remnant` |
| Best for | Most installs | Hosts where Docker is not allowed |

## Before you start

| Need | Notes |
|---|---|
| VM | Ubuntu 24.04 or Debian 12/13, 2 vCPU, 4 GB RAM to start. A Proxmox LXC works (unprivileged, `nesting` and `keyctl` on) |
| Disk | 20 GB plus room for the logs you keep. Retention is per source (30 days by default) |
| A fixed address | Static IP or a DHCP reservation, and a DNS name analysts will type |
| Firewall | Analysts to TCP 8080 only (or only the reverse proxy nodes, when there is one); SSH for administrators. Examples below |
| A reverse proxy in front? | Read [tls.md, Behind a reverse proxy](tls.md#behind-a-reverse-proxy) first, and set the public URL **before the first start** so the setup link goes through the proxy |
| Logs on the VM | A collector writing files under one folder (see [../ingest/](../ingest/)), or a Grafana Loki to read from ([../ingest/loki.md](../ingest/loki.md)) |

Anything reachable from the network requires sign-in and HTTPS; there is no switch to turn that off. Until the first administrator exists, the server only serves the setup page.

## A. Docker Compose

```bash
curl -fsSL https://get.docker.com | sh            # then log out and back in
git clone https://github.com/Err0ric/remnant /opt/remnant && cd /opt/remnant
cp .env.example .env
```

No internet access on the VM, or a proxy that breaks the build? Use [offline.md](offline.md) instead of the clone and build here.

Edit `.env`:

```
APP_BIND=0.0.0.0
APP_PUBLIC_NAME=siem.example.internal
LOGS_DIR=/var/log/remote
LOGS_GID=4
# RULES_DIR=/opt/sigma/rules
```

| Setting | Meaning |
|---|---|
| `APP_BIND` | Address to publish on; `0.0.0.0` for all interfaces |
| `APP_PUBLIC_NAME` | The name analysts type. Used in the setup link, alert links, and the certificate |
| `LOGS_DIR` | Host folder with log files, mounted read-only at `/logs` |
| `LOGS_GID` | Group that can read those files (4 is `adm` on Debian and Ubuntu, which rsyslog uses) |
| `RULES_DIR` | Optional Sigma rule folder, mounted read-only at `/rules` |

```bash
docker compose up --build -d
docker compose logs app | grep -A1 "one-time link"
docker compose logs app | grep "SHA-256"
```

Open the link from your PC, compare the certificate fingerprint in the browser warning with the log line, and create the administrator. To use your own certificate instead of the generated one, see [tls.md](tls.md).

Updating:

```bash
cd /opt/remnant && git pull && GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build --force-recreate app
```

Database changes are applied automatically at start and only ever add to what is there.

Lost the administrator password: `docker compose exec app app-admin reset-password <username>`.

## B. systemd service

Needs Python 3.12 (uv installs it; `backend/.python-version` pins it even when the system Python is newer) to run, and Node 22 to build the web UI once per update. Run the commands as root, or prefix each with `sudo`. Tested unchanged, hardening included, in an unprivileged Proxmox LXC on Debian 13: it survived a reboot and used about 105 MB at idle.

```bash
# 1. Tools (as root)
apt-get install -y git curl ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs

# 2. User and folders
useradd --system --home /var/lib/remnant --shell /usr/sbin/nologin remnant
install -d -o remnant -g remnant -m 0750 /var/lib/remnant
install -d -m 0755 /etc/remnant
install -d -m 0755 /var/log/remote   # or the folder your collector already writes to

# 3. Code, UI, and Python packages (umask 022: the service user must read every file)
umask 022
git clone https://github.com/Err0ric/remnant /opt/remnant
cd /opt/remnant/frontend && corepack enable \
  && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm install --frozen-lockfile && pnpm build
cd /opt/remnant/backend && UV_PYTHON_INSTALL_DIR=/opt/remnant/.python uv sync --frozen --no-dev
```

`/etc/remnant/remnant.env` (owned by root, mode 0640, group `remnant`):

```
APP__SERVER__HOST=0.0.0.0
APP__SERVER__PORT=8080
APP__SERVER__PUBLIC_NAMES=siem.example.internal
# Behind a reverse proxy: the address people open (no :8080), set before the first start.
# APP__SERVER__PUBLIC_URL=https://siem.example.internal
# Behind a reverse proxy: its node addresses, so the audit log and the login lockout see
# each person's address (docs/install/tls.md, Trusted proxies).
# APP__SERVER__TRUSTED_PROXIES=192.0.2.10,192.0.2.11
APP__SERVER__STATIC_DIR=/opt/remnant/frontend/dist
APP__PATHS__DATA_DIR=/var/lib/remnant
APP__PATHS__ALLOWED_ROOTS=/var/log/remote
APP__PATHS__STARTER_TEMPLATES=/opt/remnant/templates/starter
# APP__PATHS__RULE_ROOTS=/opt/sigma/rules
# Memory budget that query memory is sized from. Auto: 75% of the smallest of
# /proc/meminfo, the cgroup limit, and physical RAM. Set it only if the startup line
# "Memory budget" shows a size larger than this machine. The process limit itself is
# MemoryHigh=/MemoryMax= in the unit below.
# APP__SERVER__MEMORY_LIMIT_MB=4096
# Query threads. Auto: threads per query from the usable CPUs (at most 4), 4 queries at once.
# On a small container with a low process limit, lower them; the startup line "Queries"
# shows the peak thread count to compare with the limit.
# APP__SERVER__QUERY_THREADS=2
# APP__SERVER__MAX_CONCURRENT_QUERIES=2
PYTHONUNBUFFERED=1
```

```bash
chown root:remnant /etc/remnant/remnant.env && chmod 0640 /etc/remnant/remnant.env
```

`/etc/systemd/system/remnant.service`:

```ini
[Unit]
Description=Remnant log search
After=network-online.target
Wants=network-online.target

[Service]
User=remnant
Group=remnant
# Read rsyslog's 0640 root:adm files without running as root
SupplementaryGroups=adm
EnvironmentFile=/etc/remnant/remnant.env
WorkingDirectory=/var/lib/remnant
ExecStart=/opt/remnant/backend/.venv/bin/app-server
Restart=on-failure
RestartSec=5
# Memory limit for the whole service (D80). Past MemoryHigh the kernel reclaims and slows
# the service; past MemoryMax it ends it and systemd restarts it. Percentages are of the
# machine's (or container's) memory; fixed sizes such as 3G work too.
MemoryHigh=80%
MemoryMax=90%

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ReadWritePaths=/var/lib/remnant
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LockPersonality=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
ProtectProc=invisible
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged
UMask=0027

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now remnant
journalctl -u remnant | grep -A1 "one-time link"
journalctl -u remnant | grep "SHA-256"
```

Open the link and create the administrator, as above.

### Updating

Run the update script as root. It stops the service, pulls, rebuilds the web UI, syncs the Python packages, makes `/opt/remnant` readable by the service user, starts the service, and prints the startup lines. Database migrations run on start.

```bash
sudo sh /opt/remnant/scripts/update-systemd.sh
# With AIDE installed, also re-baseline it afterwards:
sudo sh /opt/remnant/scripts/update-systemd.sh --aide
```

The same steps by hand:

```bash
umask 022                                  # whatever your shell had (an openssl step may leave 077)
systemctl stop remnant
cd /opt/remnant && git pull --ff-only
cd frontend && pnpm install --frozen-lockfile && pnpm build
cd ../backend && UV_PYTHON_INSTALL_DIR=/opt/remnant/.python uv sync --frozen --no-dev
chmod -R a+rX /opt/remnant
systemctl start remnant
journalctl -u remnant -n 20 -o cat          # look for "listening on"
```

| What you see | Cause | Fix |
|---|---|---|
| `error: user remnant cannot read /opt/remnant/...` in the journal | The update ran with umask 077, so new files are readable by root only | `chmod -R a+rX /opt/remnant`, then `systemctl start remnant`; the script does this every time |
| `status=203/EXEC` and `Permission denied` on `.venv/bin/app-server` | Same, on the program itself, so systemd cannot start it at all | Same fix |

After an update, re-baseline any file integrity monitor that watches `/opt/remnant` (see below), or every updated file shows as changed.

Lost the administrator password:

```bash
sudo -u remnant sh -c 'set -a; . /etc/remnant/remnant.env; set +a; exec /opt/remnant/backend/.venv/bin/app-admin "$@"' app-admin reset-password <username>
```

### Firewall examples

Allow port 8080 only from the people or the proxy nodes that need it (addresses are examples):

```bash
# firewalld
firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=192.0.2.10/32 port port=8080 protocol=tcp accept'
firewall-cmd --reload
# ufw
ufw allow from 192.0.2.10 to any port 8080 proto tcp
```

Docker installs: Docker publishes ports through its own rules, which can bypass firewalld and ufw. Check from a host that should be refused that the port does not answer, or publish on one address only (`APP_BIND`).

### File integrity monitoring

AIDE, Wazuh syscheck, and similar tools: exclude the data folder (`/var/lib/remnant`, or the `app-data` volume), which changes constantly. Keep watching `/opt/remnant` and `/etc/remnant`, and re-baseline after each update (`update-systemd.sh --aide` does it for AIDE). The data folder has the app's own integrity checks ([integrity.md](integrity.md)).

## After install

| Step | Where |
|---|---|
| Invite analysts and auditors (each gets a single-use invite link) | **Users and access** |
| Add sources: files under the allowed folder, or Loki | **Sources** |
| Group sources and grant groups to people; ungrouped sources are visible to administrators only | **Users and access > Source groups** |
| Optional: a local model for Ask | **AI providers** (keep sources **Local only** unless you choose otherwise per source) |
| Optional: Sigma rules | **Detection rules > Import rules** from the rules folder |
| Optional: alert targets for schedules and rules | **Alert targets** |
| Optional: sign-in with Microsoft Entra ID or another OIDC provider | [sso-entra.md](sso-entra.md) |
| Recommended: an alert when a source stops sending | [quiet-sources.md](quiet-sources.md) |

Back up the data folder with `app-admin backup`, which works while the server runs: see [backup.md](backup.md). It holds the event lake, settings, users, the audit log, and `.key`, which encrypts stored passwords and tokens: without it those secrets cannot be read back.
