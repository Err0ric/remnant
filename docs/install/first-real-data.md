# First week with real data: a checklist

For a team trying the product on its own logs for the first time: firewall syslog already landing on a collector, Microsoft 365, and AI tools to account for. Work top to bottom; each step says what "working" looks like, so you know when to move on.

Keep it **local only**: every source starts `local_only`, so nothing is ever sent to a cloud AI provider. Leave it that way for a trial, and use a local model (Ollama) or none at all. Everything except Ask in plain English and Explain works with no model.

## 1. Stand it up

- [ ] VM per [team-vm.md](team-vm.md): 4 vCPU, 8 GB RAM, and disk for 30 days of logs. The lake is about half the size of the raw syslog (README, Tested scale), so check how many GB a day your collector writes and plan for half that per day kept.
- [ ] `docker compose up -d`, open the setup link from the server log, create the administrator.
- [ ] Browser shows the sign-in page over HTTPS. Replace the self-signed certificate when convenient ([tls.md](tls.md)).
- [ ] Optional: Entra sign-in for the team ([sso-entra.md](sso-entra.md)).

**Working:** you can sign in from your workstation, and **Overview** loads.

## 2. Firewall logs (already on the syslog server)

No firewall change is needed: the product reads the files your collector already writes.

- [ ] Make the collector's log folder readable on the VM (a bind mount or an NFS read-only share), under `allowed_roots`.
- [ ] **Settings > Sources and connectors > Discover**, point it at the folder. It groups files by host and pattern and suggests a template per group (Palo Alto traffic, threat, system, GlobalProtect, User-ID).
- [ ] Accept the suggestions. Parser: **Automatic** for mixed files.
- [ ] On the Sources page, each source shows **Reading** and an event count that grows.
- [ ] Open a source's parser mix (under its name): most lines should go to a vendor template, not "Generic". A large Generic share means the log format differs from the shipped template; draft a template from a sample (**Settings > Templates > New draft**).

**Working:** in **Search**, `source:paloalto_traffic deny` returns rows with source and destination IPs filled in.

For the AI usage view, the firewall must forward **URL filtering** or **DNS** logs, not only traffic logs, so destination host names are there. **User-ID** logs turn IP addresses into people.

## 3. Microsoft 365

- [ ] Follow [m365.md](m365.md): app registration, read-only permissions, admin consent, certificate.
- [ ] Check that the server can reach `login.microsoftonline.com`, `manage.office.com`, and `graph.microsoft.com` on 443, directly or through your proxy ([proxy.md](proxy.md)).
- [ ] **Test connection** shows **Works** for every feed you ticked. Save.
- [ ] Wait: audit content arrives 30 minutes to a few hours after the activity.

**Working:** `message = 'CopilotInteraction'` and `class_uid = 3002` (sign-ins) return rows.

## 4. Detection rules

- [ ] Put Sigma rules in a folder under `rule_roots` (the SigmaHQ repository's `rules/windows` and `rules/linux` are a start), then **Detect > Detection rules > Import rules**.
- [ ] Enable a handful you care about. Run them over the last 7 days.
- [ ] Schedule the ones worth watching (**Detect > Schedules**, kind Rule) with an alert target (Teams, email).

**Working:** **Investigations** ranks users, IPs, and hosts. Clicking one shows its lanes.

## 5. AI usage

- [ ] **AI > AI usage > Services**: AI services seen in DNS and URL logs. Set each to Approved or Not approved.
- [ ] Optional: Claude Code telemetry ([claude-code-telemetry.md](claude-code-telemetry.md)), the MCP inventory script ([mcp-inventory.md](mcp-inventory.md)), and the Anthropic reports ([anthropic-admin-api.md](anthropic-admin-api.md)) if your plan has an Admin key.
- [ ] **Review and alerts > AI watch**: alert on first sightings of anything not approved.

**Working:** **Investigations > AI flow** shows people, AI clients, MCP servers, and services.

## What to check every day of the trial

| Look at | Healthy | If not |
|---|---|---|
| Sources page | Every source **Reading**; no warnings | The status says why: a folder permission, a missing license, an expired secret |
| Overview | Events per hour look like your network | A gap means a collector or a source stopped; set a quiet-source alert ([quiet-sources.md](quiet-sources.md)) |
| Parser mix | Few Generic lines | Draft a template from a sample |
| Search speed | Seconds for a day of firewall logs | Note the query and the row count |

## Sending feedback

Report problems with **screenshots and counts, never log lines**: the page, what you did, what you expected, and numbers such as parse rates or query times. Real log content stays on your server.
