# Release notes

## Unreleased

### Schedule many detection rules at once

- **Detection rules > Schedule selected**: pick how often, the range each run looks at, and the alert targets once, and get one schedule per selected enabled rule (F58). Rules that are off or that you already schedule are skipped and named. Each schedule is created and audited as if made alone.
- By default these schedules do not each add a dashboard panel; their matches show on Health and go to the alert targets. A checkbox adds the panels if you want them.

### Changed: Overview is now part of Health

Overview missed a real problem: a firewall sent nothing for five hours while other sources flowed, shown only as dark heatmap cells (F55). Health now answers "am I blind?" on one page:

- Four tiles at the top: events in 24 hours against a usual day, sources healthy (with gaps and the longest wait), panels that need attention, and alert delivery. Each opens its detail.
- One line for detections, paused schedules, and alert delivery when all is clear, and a short list when not.
- **Health > Sources**: one row per source, problems first, with events per hour as a line in your local time, the 24-hour total, events per minute now, and when the last event arrived. A source that normally sends every hour and stops for two hours or more gets a sentence under its row: "No events 2:00 to 7:00 AM (5 h). Other sources kept flowing." This needs no history.
- The Overview item is gone from the menu; `/overview` and old bookmarks open Health > Sources. The Dashboard's health strip counts sources with gaps and links to Health.

### Fixed: pages scrolling sideways; About shows the exact build

- Overview's heatmap and the Sources table no longer scroll sideways or widen the page at desktop widths (F54). Sources now shows each source's event count with "latest 8 min ago" under it (UTC time on hover), and Data and retention in one column. CI checks every page at 1280px.
- **Investigations** picks the entity type from what you type (an address, `alice@example.com` or `DOMAIN\\user`, or a host name); the list still overrides it. It starts on IP address, shows an example for the chosen type, and remembers the last type in this browser (F56).
- **About and licenses** shows the version with the commit it was built from, such as `0.3.0+01f3cd7`. Container builds show it when built with `GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build`. "License" is spelled the US way everywhere.

### Updating a systemd install

- New `scripts/update-systemd.sh`: stops the service, pulls, rebuilds the web UI, syncs Python packages, makes `/opt/remnant` readable by the service user, starts the service, and shows the startup lines. `--aide` also re-baselines AIDE. See **Updating** in `docs/install/team-vm.md`.
- If the service cannot read its own files (an update run with umask 077), it now logs one line naming the file and the fix (`chmod -R a+rX /opt/remnant`) instead of a Python traceback (F50).
- Re-baseline any file integrity monitor that watches `/opt/remnant` after each update.

### Fixed: false "Parser changed" note on dashboard panels

A panel could say "Parser changed for <source>" when no one changed a parser: under Automatic, a new template appearing in a source's routing mix counted as a change, and the note showed on panels whose query never read that source.

- The note now needs an administrator's parser change (the audited `source.parser_change`) on a source the panel's query returned rows from, after a run that had rows, followed by a run with none (D102).
- Notes already stored on past runs stay until the panel's next run.

### Dashboard layout editing

- **Edit layout** now lets you drag a panel to a new place in its section or into another section. Each panel also has a **Section** list and **Earlier** / **Later** buttons, so everything works from the keyboard.
- Sections can be added, renamed, moved up or down, and deleted. A new section can be empty until you move panels into it; deleting one moves its panels to No section.
- The owner or an administrator changes a dashboard's layout. Every change is in the audit log (`dashboard.layout` with before and after, `dashboard.section_rename`).

### Changed: DB-IP credit

- The "IP Geolocation by DB-IP" credit no longer appears inside every expanded event. It shows once, muted, below the results table when locations are shown.
- New **About and licenses** page (Settings > Records) lists the version, license, and each outside data source (DB-IP Lite, abuse.ch feeds, SigmaHQ rules) with its license and attribution.

### Fixed: Palo Alto event times on firewalls outside UTC

Palo Alto templates read Generated Time, which PAN-OS writes in the firewall's local time with no zone, as UTC unless the source's time zone was set. A Pacific firewall's events landed 7 hours early.

- `paloalto_system`, `paloalto_traffic`, `paloalto_threat`, `paloalto_userid`, and `paloalto_globalprotect` (version 1.1.0) now take the event time from the high-resolution timestamp, which carries its UTC offset (PAN-OS 10.x and later). Without it, Generated Time is read in the source's time zone.
- A source's time zone can now be changed on **Settings > Sources** (audited `source.timezone`).
- Sources and Health warn when a source's event times look a steady whole or half number of hours off: "Event times look 7 hours early; check this source's time zone."

**Stored events keep their old times.** Only lines read after the update are correct. Re-parsing stored events from `raw` is in the backlog. Until then, for queries over older Palo Alto events, shift by the firewall's offset (for example `time + INTERVAL 7 HOUR`), or let retention age them out.

### Fixed: AI usage over 7 days ran out of memory on busy DNS

AI usage > Services held a row per DNS event while it looked up who had each address, so a week of a busy DNS source could exceed the per-query memory share (D94).

- The query now reduces events to one row per service, person, machine, address, and hour before the address lookup. A 30-day scale test of busy DNS fits a 256 MB share without spilling.
- Queries that do need more memory spill to `<data>/tmp/duckdb`. Before, DuckDB tried `.tmp` in the working directory, which a read-only container (the default Compose setup) cannot write, so the query failed instead.
- If a range is still too big, AI usage says so and shows the last 24 hours instead.

### Fixed: failed Microsoft 365 logons counted as successes

`m365_management_activity` read the status of `UserLoginFailed` from ResultStatus, which Microsoft sets to "Success" on these records (the audit write succeeded). Every failed M365 logon in the audit logs had `status_id = 1`, so searches, schedules, and Sigma rules filtering `status_id = 2` missed them.

- Template 1.1.0 takes the status of logons from the operation: `UserLoginFailed` is 2, `UserLoggedIn` is 1. Graph sign-ins (`m365_signin`) were already right (0 is success, any other error code is failure).
- **Stored events keep the old status.** For older rows, filter on `message = 'UserLoginFailed'` instead of `status_id`. Re-parsing from `raw` is in the backlog.

### Fixed: invite and setup links behind a sign-in proxy

Behind forward-auth (Authelia, oauth2-proxy), the proxy's login redirect drops the part of the link after `#`, so people landed on the invite page with no code. The page now says "This link lost its code during sign-in. Open the invite link again now that you're signed in." The link was not used up and works on the second open. The Users page has **Copy message**, which sends the link with that note. See `docs/install/tls.md`.

### Added

- **Claude hooks plugin** (ADR-0026, D99): observe-only hooks for Claude Code and Cowork that send one metadata record per session start, prompt, tool call, tool result, and stop. Download it per OTLP source (server address, a new token, and a pilot list written in), publish it from the Claude admin console. **AI usage > Agents** now includes these sessions, and **Sessions** shows each one in order. Content is sent only when the source keeps content. See `docs/install/claude-hooks.md`.
- **Dashboards at scale** (ADR-0034, D96): more than one dashboard, personal or shared, picked at the top of the page. **Edit layout** sets each panel's size (a new **Tile** for a number and its flag, 1/3, 1/2, Full), section, and order, and adds or removes panels. Each schedule can show a headline other than its row count (sum or count distinct of a column, or the first row's value) with a label such as "devices". **Needs attention** collects flagged panels at the top until someone acknowledges them (audited). Panels say what they count ("3 addresses over threshold (0)"), tiles are compact one-line cards, and the header shows the range and when the panels last updated. Your existing panels are on "My dashboard"; shared schedules are also on "Shared panels".
- **Left nav in order of daily use** (D95): Dashboard and Overview, Investigate, Detect, AI, then System > Health; Settings at the foot. Health's collector tab is now **Endpoint agents**, so **Agents** means AI agents only.
- **Change retention and connector settings** (D93): **Change** next to Retention on every source, and **Edit settings** for Microsoft 365, Anthropic, and Loki sources (feeds, first-run history, the Loki query). The stored credential is kept. Both are audited.
- **Microsoft 365 Test connection explains itself** (D92): a new app shows "Works. No subscription yet"; audit API errors show Microsoft's AF code and a hint. Test never starts a subscription. Connector events are in the service log with the source id (`connector_notice`, `connector_pulled`, `connector_feed_failed`, `connector_failed`). New M365 sources read 7 days on first run.
- **Two Microsoft 365 example searches**: `m365_new_service_principals` (apps added, without Microsoft's own provisioning) and `m365_user_consent`.

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
- Migration 46 adds dashboards and moves every existing panel onto them; it runs on start.
- Templates changed: `windows_evtx` 1.1.0 (Sysmon 22), `m365_management_activity` 1.1.0 (failed logons). Sources pick it up on the next pass.
