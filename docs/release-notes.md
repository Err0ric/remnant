# Release notes

## Unreleased

### Fixed: Palo Alto event times on firewalls outside UTC

Palo Alto templates read Generated Time, which PAN-OS writes in the firewall's local time with no zone, as UTC unless the source's time zone was set. A Pacific firewall's events landed 7 hours early.

- `paloalto_system`, `paloalto_traffic`, `paloalto_threat`, `paloalto_userid`, and `paloalto_globalprotect` (version 1.1.0) now take the event time from the high-resolution timestamp, which carries its UTC offset (PAN-OS 10.x and later). Without it, Generated Time is read in the source's time zone.
- A source's time zone can now be changed on **Settings > Sources** (audited `source.timezone`).
- Sources and Health warn when a source's event times look a steady whole or half number of hours off: "Event times look 7 hours early; check this source's time zone."

**Stored events keep their old times.** Only lines read after the update are correct. Re-parsing stored events from `raw` is in the backlog. Until then, for queries over older Palo Alto events, shift by the firewall's offset (for example `time + INTERVAL 7 HOUR`), or let retention age them out.

### Fixed: invite and setup links behind a sign-in proxy

Behind forward-auth (Authelia, oauth2-proxy), the proxy's login redirect drops the part of the link after `#`, so people landed on the invite page with no code. The page now says "This link lost its code during sign-in. Open the invite link again now that you're signed in." The link was not used up and works on the second open. The Users page has **Copy message**, which sends the link with that note. See `docs/install/tls.md`.

### Added

- **Edit saved searches and schedules** (D86). Saved searches > Edit opens your search in Search. Schedules > Edit changes timing, range, flags, alerts, sharing, and what it runs; history is kept and the next run says what changed. Editing your own search updates your own schedules of it; other people's schedules of it still pause for review.
- **Search history** (D90): **New search** in the command bar; Back and Forward step through earlier searches, and the address can be bookmarked or shared; search text is kept after `#` so it never reaches the server or proxy logs (the reader's own source access still applies); **Recent searches** (last 10, this browser) at the top of Open; the page says "Unsaved search" or "Open: name".
- **Add to dashboard** (D89) on Search and Saved searches: hourly, last 24 hours, bars for label-and-count results, filled at once.
- **Endpoint agent** (D87): offline laptops keep their events on disk and send them on reconnect; a server name option for agents that connect by address; Sysmon DNS queries (event 22) count in AI usage. Download a new agent config to get these.
- **Can't reach the server** banner (D88), and Add source offers the Loki address other sources use.
- **Seven starter parsers** built from vendor docs (verify on real data): Authelia, TACACS+ (tac_plus), Vault audit and server, OpenVPN Access Server and server, PowerDNS, OpenLDAP slapd.
- **Example saved searches** in `examples/saved-searches/` (AI services from DNS, AI services by device, who had an address, parser mix, SSH logins, firewall maintenance), described in `docs/searching.md`.
- **`ask.v6`** Ask prompt (text on `raw`, not `message`); not the default until it is measured.

### Upgrade notes

- Migration 45 adds two columns (schedules and schedule runs); it runs on start.
- Templates changed: `windows_evtx` 1.1.0 (Sysmon 22). Sources pick it up on the next pass.
