# Release notes

## Unreleased

### Claude Code hooks: offline queue (ADR-0026 amendment b)

- A record the plugin cannot send (at home without VPN, a server restart) now waits on the laptop instead of being dropped, and goes out after the next record that reaches the server, oldest first, in the background. Metadata only: content is never written to disk. At most 10,000 records and 7 days are kept.
- Every record carries a per-install sequence number. **Health > Endpoint agents** shows, per machine, records queued at its last check-in, delivered late, lost, and missing (with when), and marks a machine with missing records for attention. Session steps that arrived late say "delivered 3 h late".
- Plugin version 2.1.0: download and publish again to get it.

**What changes for existing installs:** "dropped" on Health now means lost from the queue (full or older than 7 days); records that could not be sent are no longer counted as dropped, they arrive late.

### Fixed: AI Watch wording, chart, and first seen

- The Not set up line keeps capitals inside the sentence ("new agents and MCP servers", "sensitive data to AI").
- The AI use chart covers only the days that have data until there are 30 ("AI use since Oct 22"); before, 8 days of data sat in the right third of a 30-day axis.
- Top services' **First seen** is the earliest event for the service, from the rollup's first-seen record when it is older than the window; it no longer moves forward to the start of the 7-day range.

### Claude Code hooks: a plugin per platform, the Claude account, and dropped records (ADR-0026 amendment)

- **Windows plugin**: Windows PowerShell 5.1, nothing to install; Git Bash is no longer needed. The **macOS and Linux** plugin keeps using `sh` and `curl`. Each stands aside on the other platform and in Cowork, so nothing is sent twice. Download each from the source's **Claude plugin** form.
- **Machine-wide config**: download a bundle with `hooks.conf` for your endpoint management tool. It wins over the plugin's own copy, which is then not read, so nothing in a user's folder can redirect records.
- Records now carry the **Claude account email** (from the managed config, `CLAUDE_CODE_USER_EMAIL`, or the signed-in account in `.claude.json`) apart from the OS user. ADR-0030 will use it to tell company from personal accounts.
- New events: **failed tool calls** and **session end**. **Stop** is now shown as a turn end; a session counts as ended at its session end.
- **Dropped records**: a record the plugin cannot send is counted on the machine and reported with its next record; Health > Endpoint agents shows "N dropped".
- **Certificates**: the download can bundle this server's self-signed certificate, and `CA_FILE` names another; there is no option to skip checking.
- Every script prints only `{}` and exits 0; the server's answer is never shown to Claude.
- Content, when the source keeps it: each piece is cut to its first and last 4 KB on the machine, and the server masks detected secrets before storing (also for Claude Code telemetry content).
- Pilot guide with the path for your proxy admin and pass/fail checks: `docs/install/claude-hooks.md`.

### Fixed: AI Watch failing on busy installs (F63)

- AI Watch no longer fails with "The query needs more memory" on an install with busy DNS. Closed days are read from the daily AI rollup and only today from events; a query with a time range now opens only that range's days of the lake. On 30 days of 300,000 DNS events a day, the summary takes about 1 second instead of 33 to 43.
- **New in 24 hours** now remembers what was seen before the last 30 days: the rollup keeps when each AI service, MCP server, and agent was first seen.
- When a query needs more memory than the server allows, the answer is now 503 (a server limit), not 400, and the server log has a warning with the request id and which query it was.
- A Dashboard section that fails to load (AI Watch, Needs you, Sources) and the Alerts list now say what failed, show the request id, and offer Retry, instead of leaving an empty frame or dropping the section.

### Who had an address: sessions with ends, DHCP, and sign-ins on a machine (ADR-0029, part 1)

- Addresses resolve from **spans**, not single moments: a GlobalProtect session ends at its logout, a User-ID mapping at its logout, a DHCP lease or logon at the next one on the address. When no end is seen, a span is assumed to last at most 24 hours (VPN, DHCP) or 12 hours (User-ID, logon), and it says so: "no logout seen, assumed until 9:02 PM". Before, the newest login named the address for 12 hours even after a logout.
- **DHCP leases** from the Palo Alto system log now name the machine on an address (with its MAC). DHCP never names a person.
- A machine gets its person through a **successful Microsoft 365 sign-in on that machine** in the 24 hours before, when only one person signed in on it ("several people" otherwise). Microsoft 365 sign-in addresses are never used: they are the office's public egress.
- In an event's detail, "At that time 10.20.1.5 was held by" now lists each match with what it was and when: "DHCP lease Oct 9, 8:55 AM: WS-0042 (MAC ...)", "Company sign-in Oct 9, 9:02 AM: alice@example.com on WS-0042". The address lookup API returns these spans.
- Next for ADR-0029: admin corrections, people shown with how they were matched everywhere, and the View people in AI usage permission.

### Dashboard: AI Watch first, and nothing empty on a quiet day (F62)

- The header is one row: name, dashboard picker, New dashboard, Edit layout, and when it was updated.
- **Needs you** appears only when something does: open alerts and sources with errors or that stopped, one line each with the severity first and a link to the alert or the source's Health row. On a quiet morning it is not there at all.
- **AI Watch** comes next, then your panels. A card whose source is not set up no longer takes a card; one muted line says what is not set up and what it needs, with Add a source. **New in 24 hours** moved into AI Watch, under the cards. With less than 7 days of AI data the chart covers the days that exist ("AI use since Oct 21").
- Copy: Needs you lines no longer repeat the status after an AI Watch title; the Not set up line keeps "MCP servers" and "AI" capitalized; a panel counts "rows" unless each row is one kind of thing (one address, one person, one device), so a row keyed by host, user, and address is no longer called a device.
- Sources are one line at the bottom ("4 of 4 flowing, longest wait 3 min (m365), no gaps") linking to Health.

### Fixed: AI Watch review items and "New in 24 hours"

- One rule for everything AI Watch tracks: an AI service or MCP server in use that is not approved, an AI agent in use (its decision is Close), and each person's day with sensitive data sent to AI always has an item on Alerts until someone decides. Agent items read "AI agent not reviewed: ..."; sensitive-data items are per the day the signals were received.
- An AI service in use that is not approved now always has an item on Alerts until someone decides. Before, a service used only before the watch's last check never got one, so AI Watch could count unapproved services while Alerts and the morning answer said nothing needed you. The watch now checks every hour over the last 7 days. Items read "AI service not reviewed: Copilot" (or "not approved"), since the service may not be new; the hourly check also brings open items' wording and people up to date. A closed item stays as it was decided.
- **New in 24 hours** now lists AI services, MCP servers, and agents whose use first appears in the data in the last day (not seen in the 30 days before), with the time first seen. Before, it listed items raised in the last day, so approving a service seen days earlier could make it look new.

### People and devices are counted apart

- AI Watch's card is **People using unapproved AI** again, counting only people the events name. Devices or addresses with no person matched show as their own line under it ("3 more devices not matched to a person"), linked to AI usage > Services. Before, both were added into one number.
- AI Watch review items say "2 people: ..." and "3 devices not matched to a person: ..." separately, and Alerts shows the people count ("no person matched" when there is none).
- In Investigations' AI flow, the first lane groups People, Addresses, and Devices not matched to a person; machine names no longer appear as people.
- Fixed: an address's summary sometimes showed a Windows line that did not name the address as its example; it now prefers a line that names it.

### AI Watch on the Dashboard

- Under the morning answer, **AI Watch** answers "is anyone using AI we have not approved?" for the last 7 or 30 days: unapproved AI services, users of unapproved AI, new agents and MCP servers, app consent grants (Microsoft 365), and sensitive data sent to AI (Claude Code), each with the change against the period before.
- **AI use, last 30 days** stacks each day's use by review status (not approved, unreviewed, approved), and **Top services** lists the ten most used with their status, people, devices, and last seen. It reads the daily AI rollup, so 30 days loads quickly.
- Every number is counted on your own sources. A card whose source you do not have says which source it needs; one you cannot read says Restricted.
- The morning answer gains a third column, **New in 24 hours**: AI services, MCP servers, and agents first seen in the last day, each linking to its alert. Admin and role grants and app consents are not in it yet.

### AI Watch review items on Alerts

- AI use that needs a decision now lands on Alerts: a new AI service or MCP server that is not approved or not reviewed yet (with how many people used it), sensitive data sent to AI (per person and day), and a new or changed AI agent. Each has a severity: High when a service that is not approved is used by more than one person, or for sensitive data.
- These items are raised whether or not AI watch messages are turned on in AI usage > Review and alerts; that switch now only decides whether messages go to alert targets.
- Admins can **Approve** or mark **Not approved** right from the item. That updates the service or MCP rule, as on AI usage, and closes the item with the decision. Everyone else uses Close with a reason.
- An item is restricted for anyone who cannot read the sources it came from.

### Every source link lands on its row, and Settings agrees with Health

- A source name on the Dashboard, in an alert, or in a quiet-source message opens Health > Sources at that source's row, marked, with its gap shaded and written out (`/health#source=...`). The name there opens that source's settings, at the same row (F61).
- Settings > Sources now shows the same gap sentence Health does for the last 24 hours, with **Show on Health**, so the two pages no longer disagree.
- **Alert if quiet** is on for every new source: 60 minutes, or 3 hours for Microsoft 365 and the Anthropic admin API, which deliver late and in batches. It starts with no alert targets, so a gap becomes an alert on Alerts and the Dashboard; add targets to get messages too. Change or turn it off on Settings > Sources as before. Existing sources keep their setting.

### The Dashboard opens on the morning answer

- The top of the Dashboard is now one sentence and two columns: "2 things need you: Failed SSH by address (2 runs) and demo_dns has sent nothing for 14 h." **Needs you** lists open alerts, newest first, each linking to its alert and closable in place; **Sources** says how many are flowing, names any with errors or that stopped sending, and links each to Health. Panels sit below as before (ADR-0037 rows 5 to 8).
- This replaces the Health strip and the Needs attention list with Acknowledge: closing an alert is the one way to clear it, with a reason, on the Dashboard or on Alerts. Health's tile is now **Open alerts** and opens Alerts.

### Alerts: one queue, and a nav in the morning's order

- **Alerts** is a new page, second in the left nav with its open count. Open, Closed, and Muted tabs; each alert opens to what fired, its range and sources, its history, **Close**, and the rows the run kept (every address, person, and machine a link). A gap links to its Health row. Auditors read; Admins and Analysts close and reopen.
- The nav now reads as a morning does: Dashboard, Alerts, Investigate (Search, Investigations, Saved searches), AI usage, Health, Detect (Detection rules, Schedules), then Settings. Single items no longer sit under a heading of their own.
- Health's last tab is now **Alert delivery and schedules**, so "Alerts" means one thing.

- Every flagged schedule run, scheduled rule run with matches, and gap on a source with Alert if quiet on is now an alert item: open until someone closes it with a reason (True positive, Benign or expected, False positive, Needs follow-up; a note is required for the last two). Items can be reopened, and every close, reopen, and mute is audited (ADR-0037).
- Alert messages for flagged runs, rule matches, and quiet sources now link to that alert (`/alerts#item=...`) instead of the Dashboard or the Sources page.
- Admins can mute alerts like one item for 1 to 30 days; new ones close themselves with reason Muted and stay on record. A mute expires on its own.
- On upgrade, each schedule's latest flagged run becomes an item: closed if a dashboard had acknowledged it, open otherwise.

### Faster AI usage over long ranges

- A daily AI rollup is built for each closed day after compaction, so AI usage > Services over 7 or 30 days reads a few rows per hour instead of every DNS event. Today and any day not yet built are still read from events, with the same totals.
- The rollup follows source access and the Local only label exactly as events do, is rebuilt when late events arrive or the AI service catalog's domains change, and is removed with the events it came from. It is derived data: not in the integrity ledger, and not queryable from Search.

### Investigations leads with the answer

- An address, person, or machine opens on one sentence that says what it did ("2,619 failed sign-ins against ftp-01 over the last 7 days, 0 succeeded. From Netherlands, AS64500."), then cards with sign-in attempts, successes, users tried, hosts targeted, first and last seen, and country and network.
- **What it did** groups activity by outcome (succeeded, failed, other), with a real line from each group instead of a pattern with numbers masked, and View in Search for each. Hosts and users it touched are listed and linked. The lane graph sits below and folds away.

### Every address, person, machine, and AI service is a link

- Search results, expanded events, dashboard panels, AI usage (service names, the Who column, Claude usage people), session machines, and Health's endpoint agents now link each IP address, user, host name, and AI service to its page in Investigations. Middle-click opens it in a new tab; Back returns.
- The address of an Investigations page names the entity (`/investigations#ip=203.0.113.9`), so it can be bookmarked or shared. An AI service opens the AI flow for that service.
- Field buttons (+, -, Top) in an expanded event are always visible, dimmed until you point at them.
- A capped result now reads "the newest rows; narrow the range or filters to see all" instead of "limit reached".

### Fixed: Health > Sources was empty on installs that only pull

- Sources from Loki, Microsoft 365, and the Anthropic admin API were on a Connectors tab, so an install with only pulled sources saw "No log sources yet" and none of the per-source lines or gap sentences (F59). **Sources** now lists every source that brings events. Enrichment feeds have their own **Enrichment feeds** tab, each judged by its own update interval ("updated daily").
- The Events tile no longer compares a partial first day: it says "Not enough history yet (2 of 7 days)" until 7 full days exist, then compares only sources with that history and says when newer ones are left out (F60).

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
