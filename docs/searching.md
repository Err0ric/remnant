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

## Example saved searches

Eight examples ship in `examples/saved-searches/`. Import one on **Saved searches > Import**, then adapt it. Each reads parsed columns and carries the time range, so it works on the Dashboard as a schedule.

| File | What it answers | Reads |
|---|---|---|
| `ai_services_dns` | Which AI services were queried, by how many clients | DNS events (`class_uid = 4003`); a short domain list, with vendor ad tags left out |
| `ai_services_by_device` | Which device used which AI service | DNS events, named by the Palo Alto DHCP lease that held the address at the time of each query (an ASOF join, up to 7 days back) |
| `who_had_ip` | Who held an address: DHCP device and MAC, GlobalProtect person and laptop | `paloalto_system` DHCP leases and `paloalto_globalprotect` tunnel addresses; parameter `ip` |
| `parser_mix` | Which parser read each source, and how well | `source_id`, `template_id`, `parse_status` |
| `ssh_logins` | SSH sign-ins per user, client, and result | `linux_sshd` columns |
| `firewall_maintenance` | HA changes, commits, restarts, installs, and medium or higher system events per firewall | `paloalto_system` subtype, event id, severity |
| `m365_new_service_principals` | Enterprise apps added to the tenant, without the ones Microsoft provisions itself (actor Azure Resource Manager, or an app owned by Microsoft's tenants `f8cdef31-...` and `72f988bf-...`) | M365 directory audit and Management Activity rows; the owner is matched on `raw` |
| `m365_user_consent` | People consenting to applications (the start of OAuth consent phishing) | Same two templates, `Consent to application` |

Notes:

- The AI usage page uses the full, reviewable AI catalog and names people from logon, User-ID, and VPN events. The AI examples are a smaller, editable starting point.
- The DHCP examples read the Palo Alto system log's DHCP lease lines. For another DHCP server (Windows DHCP, ISC dhcpd, UniFi), change the `leases` part to read that source.
- A summary with a label and a count (`ai_services_dns`, `parser_mix`) can be shown as bars on the Dashboard.

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

