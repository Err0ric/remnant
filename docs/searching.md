# Writing searches that keep working

Saved and scheduled searches outlive the parsers that shaped their data. When a source's parser changes (a new template, a better match after an upgrade, a stream label that now fills in a missing header), the same log line can land in different columns. A search that matched yesterday can quietly return zero today.

## Match text on `raw`, not `message`

| Column | What it holds | Stable across parser changes? |
|---|---|---|
| `raw` | The original line, exactly as received | Yes. Never trimmed or changed (CLAUDE.md rule 5) |
| `message` | Whatever the current parser calls the message: the whole line for a generic parser, often only the free-text part for a specific one | No |
| Parsed columns (`actor_user_name`, `src_endpoint_ip`, `dst_endpoint_hostname`, ...) | Typed fields from the template | Yes, when a template maps them |

Example from a real install: DNS lines first parsed by the generic syslog parser held the whole query in `message`. After an upgrade matched them to the `dns_bind` template, `message` held only the part after the header, and a search with `message LIKE '%query: %example.com%'` dropped to zero.

```sql
-- Breaks when the parser changes
SELECT count(*) FROM events WHERE message LIKE '%Failed password%'

-- Keeps working: the original line
SELECT count(*) FROM events WHERE raw LIKE '%Failed password%'

-- Best when the template maps the field
SELECT count(*) FROM events WHERE dst_endpoint_hostname = 'example.com'
```

The Simple search tab already matches text against `raw` as well as `message`.

## When it happens anyway

When a scheduled search drops to zero right after a source it reads switched parser, its Dashboard panel says so, for example: "Parser changed for dns at 2026-10-21 03:00 UTC (generic_syslog to dns_bind)." Open the search, move text matches to `raw` or to the parsed column, and save it; the schedule asks for a review before it runs the changed search.

## When `message` is fine

`message` is only unstable across parsers. Once a query also pins the parser, `message` is whatever that template documents, and it stays that way:

| Filter | `message` holds |
|---|---|
| `class_uid = 4003` (any DNS template) | The queried name |
| `template_id = 'paloalto_system'` | The firewall's description text |
| `template_id = 'paloalto_globalprotect'` | The GlobalProtect event id |

## Microsoft 365 columns

Since the F66 parser update (directory audit 1.1.0, Management Activity 1.2.0, sign-ins 1.1.0), Microsoft 365 records fill these columns. Earlier events have them empty; Sources says from which day.

| You are looking for | Column | Filled from |
|---|---|---|
| Correlation id (the same operation in Graph and the Management API) | `metadata_correlation_uid` | Graph `correlationId`; Management API `InterSystemsId`; sign-ins `correlationId` |
| The app | `resource_name` (name), `resource_uid` (application id) | Graph target or `AppId` detail; Management API target and extended properties; sign-ins `appDisplayName`, `appId` |
| What kind of object | `resource_type` | `ServicePrincipal`, `Application` |
| Why it failed | `status_detail` | `resultReason`, `LogonError`, `status.failureReason` |
| Permissions asked for | `privileges` | The consent's scope list |
| Consent type, permission resource | `unmapped` (`$.consent_type`, `$.permission_resource`) | No OCSF column for these |

There is no `correlation_id` column. Count an operation once with `count(DISTINCT metadata_correlation_uid)`, as `m365_user_consent` does.

## Countries, networks, and internal addresses

Four functions answer from local data on the server, never the network (ADR-0039):

| Function | Returns |
|---|---|
| `ip_country(ip)` | Two-letter country code from the GeoIP file, or NULL (not an address, not public, or not in the file) |
| `ip_asn(ip)` | Autonomous system number from the ASN file, or NULL |
| `ip_org(ip)` | The network's organization from the ASN file, or NULL |
| `is_internal(ip)` | True when the address is in Settings > Enrichment > Internal networks |

```sql
SELECT src_endpoint_ip, ip_country(src_endpoint_ip) AS country, ip_org(src_endpoint_ip) AS network,
       count(*) AS failures
FROM events
WHERE class_uid = 3002 AND status_id = 2 AND NOT is_internal(src_endpoint_ip)
GROUP BY 1, 2, 3 ORDER BY failures DESC
```

Put the cheap filters (`class_uid`, `status_id`, `template_id`) first so the lookups see few rows. The answers follow the files and the list as they are now: after a GeoIP update or a change to Internal networks, the same search can return different rows.

## Query library

The query library ships tested questions for common sources, grouped in packs: Microsoft 365, Linux sign-ins and privilege, Palo Alto firewalls, DNS and AI services, and ingest health. On **Search**, **Library** (next to Open) lists the queries whose sources you have: a query is offered only when a source you can read produced events from one of its templates in the last 30 days. Each shows why it is worth running and what normal looks like.

- Clicking a query loads its SQL into the SQL tab, unsaved. Run it as any search: it goes through the query guard and reads only your sources.
- **Save as my own** makes a private saved search from it. That copy is yours; a new version of the pack never changes it. When the pack's SQL changes, the Library shows **Updated in this version** with the difference and **Replace my copy**.
- Every query runs in CI on the template fixtures for its sources, so a template change that would break one fails the build.
- The packs live in `library/<pack>/pack.yaml` and are read at start. Nothing is downloaded.

| Pack | Query | What it answers | Reads |
|---|---|---|---|
| DNS and AI services | `ai_services_dns` | Which AI services the network looks up, and from how many clients. | `dns_bind`, `dns_unbound`, `dns_windows`, `dns_powerdns` |
| DNS and AI services | `ai_services_by_device` | AI service lookups named by the device that held the address, from Palo Alto DHCP leases. | `dns_bind`, `dns_unbound`, `dns_windows`, `dns_powerdns` |
| DNS and AI services | `dns_top_domains` | What the network looks up most, and from how many clients. | `dns_bind`, `dns_unbound`, `dns_windows`, `dns_powerdns` |
| DNS and AI services | `dns_random_looking_names` | Long labels of letters and digits with few vowels are typical of generated domains and DNS tunnels (T1568.002, T1071.004). | `dns_bind`, `dns_unbound`, `dns_windows`, `dns_powerdns` |
| Ingest health | `parser_mix` | Which parser read each source and how well; a shift in the mix means a parser or a log format changed. | any source |
| Linux sign-ins and privilege | `ssh_logins` | Every SSH sign-in per user, address, and result: the baseline everything else is compared to. | `linux_sshd` |
| Linux sign-ins and privilege | `ssh_failures_by_source` | One address failing against many accounts or hosts is guessing (T1110). | `linux_sshd` |
| Linux sign-ins and privilege | `ssh_invalid_users` | Names like admin, oracle, and ubuntu tried on a host that has no such account show a dictionary list in use. | `linux_sshd` |
| Linux sign-ins and privilege | `sudo_denied` | A user not in sudoers trying sudo, or wrong passwords at the sudo prompt, is someone reaching for root. | `linux_sudo` |
| Linux sign-ins and privilege | `sudo_commands` | What people ran as root, per user and host. | `linux_sudo` |
| Linux sign-ins and privilege | `su_failures` | Wrong passwords for su and console logins, and accounts locked by faillock. | `linux_pam` |
| Microsoft 365 | `m365_failed_signins_by_user` | Who is failing to sign in, from how many addresses: the first look for guessing and lockouts. | `m365_signin`, `m365_management_activity` |
| Microsoft 365 | `m365_password_spray` | One address failing for five or more people is spraying, not a person who forgot a password (T1110.003). | `m365_signin`, `m365_management_activity` |
| Microsoft 365 | `m365_failures_then_success` | Three or more failures followed by a success from the same address is a guessed password until shown otherwise (T1078.004). | `m365_signin`, `m365_management_activity` |
| Microsoft 365 | `m365_signins_by_app` | Which apps people sign in to, and how often each fails. | `m365_signin` |
| Microsoft 365 | `m365_inbox_rules` | A new inbox rule or forwarding address is how a taken-over mailbox hides replies and copies mail out (T1564.008, T1114.003). | `m365_management_activity` |
| Microsoft 365 | `m365_app_consent` | Apps people granted access to their data, per app: the start of most consent-phishing cases (T1528). | `m365_directory_audit`, `m365_management_activity` |
| Microsoft 365 | `m365_user_consent` | Each consent, with the permissions asked for: read the scopes before deciding a consent was harmless. | `m365_directory_audit`, `m365_management_activity` |
| Microsoft 365 | `m365_new_service_principals` | Apps added to the tenant that Microsoft did not provision: where app risk starts. | `m365_directory_audit`, `m365_management_activity` |
| Microsoft 365 | `m365_admin_changes` | Role grants, Conditional Access edits, password resets by admins, and new app credentials change who can do what (T1098). | `m365_directory_audit`, `m365_management_activity` |
| Microsoft 365 | `m365_copilot_activity` | Who uses Microsoft 365 Copilot and how much: AI use the network logs cannot see (AML.T0057 monitoring). | `m365_management_activity` |
| Microsoft 365 | `m365_external_sharing` | Anyone links and invitations to outside people are how files leave the tenant on purpose or by mistake (T1567). | `m365_management_activity` |
| Microsoft 365 | `m365_dlp_matches` | Data loss prevention matches show sensitive data moving in mail, files, and Teams. | `m365_management_activity` |
| Palo Alto firewalls | `firewall_maintenance` | HA changes, commits, restarts, and installs: what changed on the firewall and when. | `paloalto_system` |
| Palo Alto firewalls | `pa_admin_signins` | Who signs in to the firewall, from where, and failed attempts: admin access is the keys to the network. | `paloalto_system` |
| Palo Alto firewalls | `pa_denied_by_source` | Internal hosts hitting many denied destinations or ports are misconfigured or scanning. | `paloalto_traffic` |
| Palo Alto firewalls | `pa_threats_by_signature` | Which threat signatures fired, on how many hosts, and whether the firewall blocked them. | `paloalto_threat` |
| Palo Alto firewalls | `gp_logins_by_user` | VPN sign-ins and failures per person and public address: remote access is a favourite way in. | `paloalto_globalprotect` |
| Palo Alto firewalls | `who_had_ip` | Which device or person had an internal address at a time: DHCP leases and VPN tunnels. | `paloalto_system`, `paloalto_globalprotect` |

Notes:

- The AI usage page uses the full, reviewable AI catalog and names people from logon, User-ID, and VPN events. The AI queries are a smaller, editable starting point.
- The DHCP queries (`ai_services_by_device`, `who_had_ip`) read the Palo Alto system log's DHCP lease lines. For another DHCP server, change the `leases` part to read that source. `who_had_ip` loads with the address `10.20.1.5` written in; change it in the editor.
- A summary with a label and a count can be shown as bars on the Dashboard.
- The `m365` failure queries treat MFA interruptions as interruptions, not failures. Events stored before `m365_management_activity` 1.1.0 recorded failed logons as successes, so older failures are missing.

## Search addresses, history, and where search text goes

Each run on Search records the search in the address after `#`, for example `/search#tab=sql&q=...&range=24h` or `/search#saved=failed_by_ip&p.top=5&range=24h`. Back and Forward step through earlier searches, and the address can be bookmarked or shared. A shared address only shows what the reader's own source access allows; the server scopes every run.

The search is in the fragment (after `#`), not the query string (after `?`), on purpose:

| Where | Sees search text? | Why |
|---|---|---|
| Reverse proxy and SSO access logs (nginx, Caddy, Authelia) | No | Browsers never send the fragment to the server |
| The server's own request log | No | Same; the query runs as a POST body to `/api/query` |
| Referer header to other sites | No | The server sends `Referrer-Policy: no-referrer`, and fragments are never in a Referer anyway |
| The audit log | Yes, by design | Every query is audited with the user id (SPEC rule 14) |
| This browser's history and bookmarks | Yes | The full address, fragment included, is kept by the browser |
| Recent searches (top of Open) | Yes | The last 10 runs, in this browser's storage only; Clear recent removes them |

What is left is on the analyst's own machine: browser history, bookmarks, synced browser profiles, and anywhere an address is pasted (a ticket, a chat). Treat a copied search address like the query itself. Queries over 4,000 characters are not put in the address at all.

Addresses from before this change (`/search?tab=...`) still open; the page moves the state into the fragment at once, so it is not sent again on reload.

