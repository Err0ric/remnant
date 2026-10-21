# ADR-0023: Enrichment feeds: GeoIP/ASN and threat intel from local files, kept current on request

Status: **Accepted** 2026-10-17 (project owner: option C, "least work for the user and the most current without having to call out all the time"; threat intel "has to be set up clean in the interface"). Recorded as SPEC D62; threats T53 and T54 added.

## Context

Slice 8 asks for GeoIP/ASN and threat intel enrichment at query time, with feed freshness shown. Both work from data files that go stale: free GeoIP databases publish a new edition monthly, threat intel lists change hourly. Until now the server never made an outbound connection that no user started (D60 keeps lookups local: no address from the logs is ever sent to a lookup service). The owner wants the least effort and current data, without frequent calls out, and an interface that stays quiet.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Which data | **GeoIP/ASN**: DB-IP Lite country and ASN databases (MMDB, CC BY 4.0, no account). **Threat intel**: abuse.ch Feodo Tracker botnet C2 addresses (no key), abuse.ch ThreatFox (addresses, domains, URLs, hashes; needs a free Auth-Key), and lists an admin uploads (one indicator per line, or CSV) | Free, widely used, and enough to start; uploads cover anything else | MaxMind GeoLite2 (account and license key; can be uploaded as a file instead), MISP and OTX (later, if asked) |
| 2 | Lookups | Always against local files. No online lookup API, ever | Addresses in logs are sensitive (D60) | Online lookups (more current, but every address leaves the server) |
| 3 | Getting files | **Upload always works. Automatic updates are off on a fresh install** and turned on with one switch (Settings > Enrichment), which the setup checklist recommends. When on: GeoIP is checked once a day and downloaded only when a new monthly edition exists; threat intel lists are checked every 4 hours (configurable, at least 1 hour) with conditional requests (`If-None-Match`, `If-Modified-Since`), so an unchanged list costs one small request | One click for current data; a fresh install still never calls out on its own; locked-down networks keep working by upload | On by default (breaks the local-first promise); upload only (stale data in practice) |
| 4 | Where it may connect | A fixed list: `download.db-ip.com`, `feodotracker.abuse.ch`, `threatfox-api.abuse.ch`. HTTPS only, through the configured proxy and CA bundle (D46). Requests carry no event data; the ThreatFox key sits in the URL path as abuse.ch requires and is stored encrypted, never logged | Nothing configurable can turn this into a way out for data | Admin-entered feed URLs (later, behind its own review) |
| 5 | Accepting a file | Size caps (100 MB per download after decompression), a format check (the MMDB opens and is the right kind of database; a list parses with at least 95% valid lines), and an atomic swap that keeps the previous file. A failed or rejected update leaves the current file in place and shows the reason | A bad download never breaks enrichment | Replace in place |
| 6 | Where GeoIP shows | The query API adds an `enrichment` map for the distinct public addresses in a result (at most 1,000 per response): country code, ASN, and organization. The table shows them as muted text after the address; private and reserved addresses get nothing. Each user can hide them. The DB-IP attribution link appears in the details card and on the settings page | Quiet by default, no new columns, no change to stored events | A SQL function (heavier; later if wanted) |
| 7 | Where threat intel shows | A read-only `threat_intel` table available in SQL (indicator, type, feed, threat, first_seen, last_seen), so searches, presets, and schedules can join it. In results, a matched value gets one small marker; details on hover or click. One "Threat intel" group in the facet sidebar and two Suspicious presets. No new pages, no row colors, no banners | Matches stand out because nothing else changes; schedules can alert on matches with what already exists | Tagging events at ingest (stale the moment a list changes) |
| 8 | Freshness | Each feed shows its age, last check, last change, and entry count on Settings > Enrichment and on the Health page. GeoIP turns to attention after 45 days and unhealthy after 75; threat intel after 2 and 7 days. Health alerts can fire on unhealthy | A stale list is visible before it misleads | |
| 9 | Who | Admins manage feeds, keys, and the update switch; every signed-in user sees enrichment on rows they can already read. Changes and every download are audited (`enrichment.*`) | Matches other admin settings | |

## Consequences

- New dependency: `maxminddb` (Apache 2.0, pure Python reader).
- Files live under `data/enrichment/`, outside the lake; backups include them.
- New table `enrichment_feeds` (state, settings, encrypted key) in a migration; `threat_intel` is a view over a Parquet file the updater writes, added to the guard's allowed tables.
- Threat intel text (a feed's threat name or tags) is untrusted like log content: rendered as text, never sent to a model in this ADR.
- ATT&CK: improves detection of T1071 (application layer C2) and T1105 (ingress tool transfer) against listed infrastructure. Not AI-facing; no ATLAS mapping.
- Threats: T53 (a poisoned or broken feed floods or hides matches: fixed HTTPS hosts, format checks, entry count shown, previous file kept); T54 (the update path used to send data out: fixed hosts, no event data in requests, off by default, audited).
- Build order: GeoIP with the feed framework first, then threat intel.
