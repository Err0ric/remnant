# Homelab test plan

A step-by-step run-through on one VM, about 45 minutes. No log collector needed: the VM becomes one.

## Before you start

| Need | Notes |
|---|---|
| Linux VM | Ubuntu 24.04 or Debian 12, 2 vCPU, 4 GB RAM, 20 GB disk. A Proxmox LXC works too: unprivileged Debian 13 with `nesting` and `keyctl` on (tested 2026-10-10) |
| Docker | `curl -fsSL https://get.docker.com \| sh` then log out and back in |
| Network | The VM reachable from your PC; note its IP (`ip -br a`) |

Use made-up or homelab logs only, not production data.

## Part 1: install and first sign-in (10 min)

```bash
git clone https://github.com/Err0ric/remnant && cd remnant
cp .env.example .env
```

Edit `.env`:

```
APP_BIND=0.0.0.0
APP_PUBLIC_NAME=<VM IP or hostname>
LOGS_DIR=/var/log/remote
```

```bash
sudo mkdir -p /var/log/remote
docker compose up --build -d
docker compose logs app | grep -A1 "one-time link"
docker compose logs app | grep "SHA-256"
```

- [ ] Open the link from your PC. The browser warns about the certificate: compare the SHA-256 in the warning with the log, then continue
- [ ] Page says *You are creating the administrator account for this installation*
- [ ] Create the account; you land on Search signed in
- [ ] Open the same link again: it is refused
- [ ] Sign out, sign in with a wrong password 5 times: the 6th attempt is blocked for a few minutes

## Part 2: demo data (5 min)

```bash
docker compose --profile demo up -d
```

This writes 24 hours of made-up logs into `/var/log/remote/demo`, then a few new events per second.

- [ ] **Configuration > Sources > Discover**, scan `/logs/demo`: 6 candidates, with sudo and systemd each listing 3 hosts and matched at 100%. Discover only suggests; nothing is searchable until a source is added
- [ ] **Configuration > Sources > Add source**, three times (use these IDs; Part 3 refers to them):

| Source ID | Parser | File or folder | File pattern |
|---|---|---|---|
| `demo_syslog` | Automatic (the default) | `/logs/demo/syslog` | `**/*.log` |
| `demo_web` | Generic: JSON lines (one object per line) | `/logs/demo/apps` | `*.jsonl` |
| `demo_vpn` | Generic: CSV with a header row | `/logs/demo/vpn` | `*.csv` |

`demo_syslog` holds several programs (sshd, sudo, systemd, a firewall). Automatic sends each line to the template that fits it; the firewall lines have no template yet and keep time, host, and message until Part 3b. The other two are single-format files with no matching template, so they use the generic parsers; the Part 3 queries read their `message` and `unmapped`.

- [ ] All three show **Reading**; **Refresh counts** shows events climbing
- [ ] Under `demo_syslog`, **Parsed by** lists `linux_sshd`, `linux_sudo`, `linux_systemd`, and `generic_syslog`
- [ ] Simple search `user:root` returns sshd login attempts for root (the sshd template filled the user column)
- [ ] Try a path outside `/logs` (for example `/etc`): it is refused

## Part 3: search (10 min)

Paste each into Search and click **Run** (or press Ctrl+Enter). Run one statement at a time:

```sql
-- Brute force: failed SSH by source address
SELECT regexp_extract(message, 'from (\S+)', 1) AS src, count(*) AS failures
FROM events
WHERE source_id = 'demo_syslog' AND message LIKE 'Failed password%'
GROUP BY src ORDER BY failures DESC;

-- Firewall blocks by destination port
SELECT regexp_extract(message, 'dport=(\d+)', 1) AS port, count(*) AS blocks
FROM events
WHERE message LIKE 'action=block%'
GROUP BY port ORDER BY blocks DESC;

-- Failed VPN logins
SELECT time, json_extract_string(unmapped, '$.user') AS user,
       json_extract_string(unmapped, '$.reason') AS reason
FROM events WHERE source_id = 'demo_vpn'
  AND json_extract_string(unmapped, '$.result') = 'failure'
ORDER BY time DESC;
```

- [ ] Click a row: fields on the left, the raw line on the right, unchanged
- [ ] **Export CSV** downloads the results
- [ ] `DROP TABLE events` is refused with a clear reason

## Part 3b: write a parser without AI (10 min)

No AI provider is needed for this part. The demo firewall has no matching template (Discover said so), so give it one.

- [ ] **Configuration > Templates > New draft**: Template ID `demo_firewall`, sample from a file: File or folder `/logs/demo/syslog`, File pattern `*/filterlog.log`
- [ ] The draft opens as a skeleton that keeps each line as `message`, with 3 tests built from the sample
- [ ] In the YAML, replace the `payload` block and the `fields` under `mapping` with:

```yaml
payload:
  format: kv
  kv:
    pair_sep: ' '
    kv_sep: '='
```

```yaml
  fields:
    src_endpoint_ip:
      from: src
    dst_endpoint_ip:
      from: dst
    dst_endpoint_port:
      from: dport
```

- [ ] **Save**, then **Preview**: 200 sample lines parse ok, the 3 tests pass, and each row shows the source IP, destination IP, and port. "Ready to approve" appears
- [ ] **Approve**; `demo_firewall` is now listed as approved and appears under **Templates** in the Add source **Parser** list
- [ ] The draft's `match` block already named `filterlog` (the sample's syslog tag), so `demo_syslog` uses the new template for firewall lines from its next read: within a minute **Parsed by** shows `demo_firewall`, and Simple search `dst_port:22` finds blocks. Lines stored before the approval keep the generic parse
- [ ] Start another draft with the ID `linux_sshd`: it is refused, because starter templates cannot be shadowed

## Part 4: real syslog from your homelab (15 min)

Follow [docs/ingest/rsyslog.md](../ingest/rsyslog.md) on the same VM, then point at it:

- Proxmox host: add `/etc/rsyslog.d/90-forward.conf` from the guide
- Router or firewall: remote syslog to the VM IP, port 514

- [ ] Folders appear under `/var/log/remote/<sender IP>/`
- [ ] Add source `homelab_syslog`, Syslog, path `/logs`, pattern `*.*.*.*/*.log` (sender folders only, skips `demo/`)
- [ ] `ssh` into the Proxmox host; the login shows up in Search within seconds
- [ ] Optional: repeat with [Vector](../ingest/vector.md) on a spare VM and note the version in that guide; it is the one collector guide not yet run

## Part 5: CLI from your PC (5 min)

```bash
cd remnant/backend && uv sync
uv run remnant login --server https://<VM>:8080
# confirm the fingerprint matches the server log, then sign in
uv run remnant tail demo_syslog -n 20
uv run remnant tail demo_syslog -f --where "message LIKE 'Failed%'"
uv run remnant query "SELECT source_id, count(*) FROM events GROUP BY 1" -o table
uv run remnant logout
```

- [ ] Token went to your OS keychain (the login message says where)
- [ ] After `logout`, `tail` asks you to log in again

## Part 6: team access, Ask, and the accuracy suite (30 min)

Team access:

- [ ] Users and access: invite a second user as Analyst, open the link in a private window, set a password
- [ ] Create a group with only `demo_vpn`, add the analyst; as the analyst, Search shows only `demo_vpn`
- [ ] Remove the analyst from the group; their next search shows nothing

Ask with a local model (needs about 8 GB of RAM free for an 8B model):

```bash
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama pull llama3.1:8b
```

- [ ] AI providers: edit "Local Ollama", **Test** lists `llama3.1:8b`, pick it, save, **Enable**; the badge says Local
- [ ] Ask: "Which source IPs had the most failed SSH logins?" shows SQL, an explanation, and a self-check line; nothing runs until **Run query**
- [ ] Refine with "only the last hour"; the earlier question is listed and the SQL changes
- [ ] **Save** it; it appears in Saved searches with your question as its origin
- [ ] As the analyst, Ask never mentions sources outside their group
- [ ] CLI: `uv run remnant ask "events per source"` prints SQL and waits at `Run? [y/N]`

Accuracy suite (from a checkout on the VM or your PC, pointing at the same Ollama):

```bash
cd remnant/backend
uv run python -m evals.nl_queries.run --base-url http://<VM>:11434/v1 --model llama3.1:8b --out llama31-8b.json
```

Ollama listens on `127.0.0.1` in the compose file, so run this on the VM or tunnel the port. Paste the JSON summary into the results table in `backend/evals/nl_queries/README.md`.

- [ ] Executable rate, exact rate, and median seconds recorded for at least one model

## Part 7: Sigma rules (10 min)

Rule sets live in their own folder, `rules/` next to `docker-compose.yml`, mounted read only at `/rules`. It is not a log folder, so nothing in it is ever ingested.

```
mkdir -p /opt/remnant/rules
git clone --depth 1 --branch r2026-07-01 https://github.com/SigmaHQ/sigma /opt/remnant/rules/sigma
docker compose up -d   # picks up the /rules mount after a pull
```

As the administrator, import `/rules/sigma/rules` (about a minute). Expect about 3,128 accepted and 14 refused, each refusal with its reason. Imported rules start disabled. Check:

- [ ] The import summary shows accepted, new, and refused counts
- [ ] Every rule shows its title and author
- [ ] Importing again reports everything unchanged
- [ ] An analyst can list rules but cannot import or enable them

Then run something:

1. Tick **With data only** to see the rules some source of yours can satisfy (the Sources column).
2. Enable a few (tick them, then **Enable selected**), for example "Failed Logon From Public IP" if Windows Security events come in.
3. Pick **Run over: Last 7 days** and **Run** one. The run panel shows the count, the sources read, the matches, and the rule's author.
4. **Open in Search** shows the matched events.

- [ ] A rule with no matching source says "No matching sources" instead of scanning everything
- [ ] Process creation rules that use only Image, ParentImage, or CommandLine also match Security 4688 if you collect it

## Part 8: schedules and the Dashboard (10 min)

1. Save a search (Search, then **Save**), for example failed SSH logins by source address with `time BETWEEN {{start}} AND {{end}}`.
2. **Detect > Schedules > New schedule**: the saved search, **Hourly**, **Last 24 hours**, flag when **Above** 5.
3. Add a second schedule for an enabled rule.
4. **Run now** on each, then open **General > Dashboard**.

- [ ] Each panel shows the count, a small bar trend, the flag when above the threshold, and the top rows
- [ ] **Open in Search** on the saved-search panel runs the same query for the same range
- [ ] Editing the saved search pauses its schedule with a reason; **Resume** brings it back
- [ ] An analyst outside a source's group sees "Restricted" on a shared panel that read that source

## Part 9: Explain (10 min, needs an enabled AI provider)

1. In Search, open an event and click **Select for Explain** on two or three events, then **Explain N selected** in the results header.
2. Pick your local model and click **Explain**.

- [ ] Each claim lists the events it cites; a claim that cites nothing, or an event that was not sent, says "unverified"
- [ ] **Download report (Markdown)** saves a file with every claim and its event ids
- [ ] On a rule run, **Explain matches** works the same way
- [ ] An auditor sees no Explain buttons

## Part 10: alerts (10 min)

1. **Configuration > Alert targets > Add target**: a Slack or Teams Workflows webhook, an SMTP server, or a webhook on your network (for example ntfy: `http://<ntfy host>/<topic>` works over http because the address is private).
2. **Send test**. The result shows next to the target.
3. On **Schedules**, create a schedule and tick the target under **Send alerts to**; **Run now** a rule schedule that has matches.

- [ ] The message is a summary (what fired, count, why, link) with no log lines in it
- [ ] The **Alerts** column on Schedules shows the delivery as Sent
- [ ] A wrong URL is refused when saving (for example a Slack URL on another host)
- [ ] An analyst can pick targets on their schedules but cannot see Configuration > Alert targets

## Report back

For anything that felt wrong, note the page, what you did, and what you expected. Screenshots help. Layout and wording changes are cheap now.

## Clean up

```bash
docker compose --profile demo down      # stop the generator
docker compose --profile ollama down    # stop the model server
docker compose down -v                  # remove everything, including the admin account
```
