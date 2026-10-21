# Enrichment: GeoIP and threat intel

Search results can show the country and network (ASN) of public addresses, and mark values that appear on threat intel lists. Both are looked up in files kept on this server (ADR-0023). No address or value from your logs is sent anywhere. Private and reserved addresses get no location.

```
src_endpoint_ip   203.0.113.9  NL · AS64500
```

## Turn it on

Settings > **Enrichment** (admins), or the **Keep enrichment data current** step on the setup checklist.

| Way | What to do | Good for |
|---|---|---|
| Automatic (recommended) | Tick **Keep these lists and files current automatically** | Servers that can reach the internet, directly or through the proxy |
| By hand | Download the monthly `dbip-country-lite-YYYY-MM.mmdb.gz` and `dbip-asn-lite-YYYY-MM.mmdb.gz` from [db-ip.com/db/lite.php](https://db-ip.com/db/lite.php) on another machine, then **Upload file** on each row | Servers without internet |

MaxMind GeoLite2 Country and ASN files (`.mmdb`) can be uploaded instead; the file is checked to be the right kind before it replaces anything.

## What automatic updates do

| | |
|---|---|
| When | GeoIP: a check once a day, with a request only when this month's edition is not installed yet (about 12 downloads a year per file). Threat intel: every 4 hours (`APP__MAINTENANCE__INTEL_CHECK_S`, at least 1 hour), with a conditional request, so an unchanged list costs one small request |
| Where | `download.db-ip.com`, `feodotracker.abuse.ch`, and `threatfox-api.abuse.ch` only, through `network.https_proxy` if set, with your CA bundle if set. Redirects are not followed |
| What is sent | A plain file request (ThreatFox: a request for the last day's additions, with your key). Nothing from your logs |
| If it fails | The current file stays in use; the reason shows on the Enrichment page and on Health |
| Size | Up to 100 MB per file once decompressed; the previous file is kept as `previous.mmdb` |
| Record | Every download and upload is in the audit log (`enrichment.update`, `enrichment.upload`) |

Files live in `data/enrichment/` and are included in backups.

## Freshness

The Enrichment page and Health (Connectors tab, once a feed is set up) show each file's edition and age:

| Status | Meaning |
|---|---|
| Current | This or last month's edition |
| Getting old | About two editions behind |
| Out of date | Three or more behind: check the network or proxy, or upload a newer file |

## In results

- A muted label after each public address in the results table. **Location** in the results toolbar hides or shows it for you (remembered in this browser).
- The expanded event shows the country name, ASN, and network name under each public address.

## Threat intel

| List | Source | Setup |
|---|---|---|
| Botnet C2 addresses | [abuse.ch Feodo Tracker](https://feodotracker.abuse.ch/) | None: downloads with automatic updates |
| Indicators of compromise (addresses, domains, URLs, hashes) | [abuse.ch ThreatFox](https://threatfox.abuse.ch/) | A free Auth-Key from the abuse.ch authentication portal: **Add key** on its row. Stored encrypted, never shown again. Keeps a rolling 90 days |
| Your list | You | **Upload list**: one address, domain, URL, or hash per line, optionally `value,note`. Lines starting with `#` are comments. CIDR ranges are not matched. An upload replaces the list; at least 95% of lines must be valid |

Each list can be switched off with the box on its row.

**In results**

- A value on a list gets one small red dot before it. Hover for the list and the threat; the expanded event spells it out under the value.
- `intel:listed` in Simple search finds every event whose source or destination address or host name is on an enabled list. `intel:qakbot` narrows to listings that mention the word; `intel:threatfox` to one list.
- With `intel:` in the search, the field sidebar gets a **Threat intel** group with counts per threat; click one to filter.
- Search > Suspicious has **Threat intel matches** and **Botnet command and control**.
- In SQL, `threat_intel` is a read-only table: `indicator, type, feed, threat, first_seen, last_seen`. For example:

```sql
SELECT e.time, e.src_endpoint_ip, t.threat
FROM events e JOIN threat_intel t ON t.type = 'ip' AND t.indicator = e.dst_endpoint_ip
```

Saved searches and schedules can use it too, so a schedule on `intel:listed` alerts on new matches.

Ask mode previews and the MCP server cannot read `threat_intel`: list text is never sent to a model.

Data: [IP Geolocation by DB-IP](https://db-ip.com), CC BY 4.0. Threat intel from [abuse.ch](https://abuse.ch); check each project's terms for your use.
