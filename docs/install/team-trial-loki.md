# Team trial on a shared VM, reading from Loki

A fresh install on a VM inside a team's network, reading logs the team already keeps in Grafana Loki. About an hour, most of it waiting for data. Written for a first trial: nothing is sent outside the network, and nothing in Loki changes.

Run [homelab-test.md](homelab-test.md) once on made-up data first if you can; it covers the same screens with made-up logs.

## 1. Before the day (with whoever runs Loki)

| Ask for | Why | Example |
|---|---|---|
| Loki root URL, reachable from the VM | The app polls it every 30 s | `http://loki.internal:3100` |
| Sign-in, if any | Loki behind a gateway | token, or username and password |
| Tenant, if multi-tenant | Sent as `X-Scope-OrgID` | `ops` |
| One or two label selectors to start with | Keep the first source small | `{job="syslog", host=~"fw.*"}` |
| Rough volume of those streams | One source reads at most about 650 lines a second when catching up | "about 50 lines/s" |
| OK to copy those logs onto the VM | The VM becomes a second store of them | written approval, if your policy needs one |

Check from the VM before installing (no app needed):

```bash
curl -s "$LOKI/loki/api/v1/labels"                 # label names
curl -s "$LOKI/loki/api/v1/label/job/values"       # values of one label
```

Add `-H "Authorization: Bearer <token>"` and `-H "X-Scope-OrgID: <tenant>"` when needed.

## 2. VM

| Item | Minimum | Notes |
|---|---|---|
| OS | Ubuntu 24.04 or Debian 12/13 | A Proxmox LXC works: unprivileged, `nesting` and `keyctl` on |
| CPU / RAM | 2 vCPU, 4 GB | 4 GB more if you run a local model on the same VM |
| Disk | 20 GB plus room for the copied logs | Retention is per source, 30 days by default; watch disk use on day one and adjust |
| Address | Static, or reserved in DHCP | Check it is free before assigning it (`ping`, `arp -a`) |
| Access | Analysts' PCs to port 8080 only | Restrict at the firewall; SSH for admins only |

## 3. Install

```bash
curl -fsSL https://get.docker.com | sh      # then log out and back in
git clone https://github.com/Err0ric/remnant && cd remnant
cp .env.example .env
```

Edit `.env`:

```
APP_BIND=0.0.0.0
APP_PUBLIC_NAME=<VM hostname or IP analysts will type>
```

No `LOGS_DIR` is needed when everything comes from Loki. For Sigma rules, clone a rule set and point at it (the app only reads it, and imports rules when an admin asks):

```bash
git clone --depth 1 https://github.com/SigmaHQ/sigma /opt/sigma
echo "RULES_DIR=/opt/sigma/rules" >> .env
```

```bash
docker compose up --build -d
docker compose logs app | grep -A1 "one-time link"
docker compose logs app | grep "SHA-256"
```

- [ ] Open the link from your PC. Compare the SHA-256 in the browser's certificate warning with the log line before continuing
- [ ] Create the administrator account (single-use link, valid 30 minutes)
- [ ] Optional: replace the self-signed certificate with one from your CA ([tls.md](tls.md))

## 4. AI settings for a trial on real data

Fresh installs have no AI provider, and every source starts **local only**. For a trial on real data, keep it that way:

- [ ] Do not add a cloud provider (OpenAI, Anthropic, or any hosted API) under **AI providers**
- [ ] Leave every source **Local only**
- [ ] Optional: a model on your own network (Ollama, LM Studio, vLLM) for Ask. Check it shows the **Local** badge after **Test**. For reasoning models such as Qwen 3.5, set **Thinking** to **Off**, or Ask can run out of output before it answers
- [ ] Simple search, SQL, Sigma rules, and the Overview all work with no provider at all

## 5. Add the Loki source

Follow [../ingest/loki.md](../ingest/loki.md). In short:

- [ ] **Sources > Add source**, **Reads from: Grafana Loki**, the URL, sign-in, and the first selector
- [ ] **Test connection**: lines in the last hour, and the label sets that matched. Fix the selector until the label sets are the ones you expect
- [ ] Leave **Parser** on **Automatic** and back-fill at 24 hours
- [ ] Add it. Status shows **Reading** and, after the first poll, how far behind Loki it is

Start with one source. Add more selectors as separate sources once the first one looks right; separate sources also let you share some logs with some people only (**Users and access > Source groups**).

## 6. First hour checks

| When | Check | Good looks like |
|---|---|---|
| 2 min | Sources: status and **Behind** | Reading, behind under a few minutes once the back-fill is done |
| 5 min | Sources: **Parsed by** under the source | Your products' templates (`linux_sshd`, `paloalto_traffic`, ...) plus some `generic_syslog` |
| 5 min | Search, Simple tab: `host:<a known host>` | Events from that host, newest first |
| 10 min | Search: `user:<your account>` and `src_ip:<your PC>` | Your own sign-ins, if those products send them |
| 10 min | A row's detail: raw line | Exactly the line Loki holds |
| 15 min | Overview | Volume by hour, ingest health, no paused or failing items |
| 30 min | **Detection rules**: import `/rules/linux` (or `/rules/windows`), enable a few rules, run over 24 hours | Matches listed with event ids; no rule reads rows from the generic parser |
| 60 min | **Audit log** | Your sign-in, the source creation, the Loki connection test, every query |

If most lines show `generic_syslog`, no template fits those products yet. Note the program names (the `app_name` in a row's envelope); a template for each is the fix (**Templates > New draft**, from a sample of those lines).

## 7. What to write down for the project

| Item | Where to find it |
|---|---|
| Install problems, with the step | Your notes |
| Products in the stream and which parser each got | Sources: **Parsed by**; Search: group by `template_id` |
| Lines that stayed generic: program names and one sample each, with addresses and names replaced | Simple search: `template_id:generic_syslog` |
| Ingest lag and lines per second | Sources page, Overview |
| Searches people tried that did not work | Search history in your notes |
| Anything that looked wrong or confusing | Screenshots with real values blurred |

Do not paste real log lines into public issues; replace hostnames, users, and addresses with made-up ones first.

## 8. Ending the trial

```bash
docker compose down        # stop, keep the data
docker compose down -v     # stop and delete every stored event, user, and setting
```

Loki is untouched either way. If the logs were copied under an approval, record when the copy was deleted.
