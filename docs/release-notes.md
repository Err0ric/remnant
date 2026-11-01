# Release notes

## Unreleased

### Left rail: click to open (2026-11-01)

- Group headers (System, Connected apps) and folded pages open and close in place when you click them, and stay as you left them. Hovering them no longer pops up a separate menu.
- The narrow icon rail (768 to 1100 px wide) still shows a page's sub-pages beside it on hover, since it has no room to open them in place.
- What changes for existing installs: nothing to do.

### Update script: "up to date" means installed (2026-11-01)

- The update script now compares `origin/main` with the build the service last ran, kept in `/var/lib/remnant/installed_commit` after a successful restart, not with the checkout. A checkout moved by hand, or an update that failed partway, is built and restarted on the next run even when there is nothing new to fetch.
- `--aide` re-baselines AIDE even when the install is already up to date.
- The record is root-owned (0644). One the service user could have written, or a link, is ignored and the update builds, so a compromised service cannot hold back updates.
- Sessions survive a restart (they are kept in the database). A browser signed in more than 12 hours earlier (`auth.session_hours`) is signed out at that time, restart or not.
- What changes for existing installs: nothing to do. The first run after this update builds once, since no installed commit is recorded yet. Don't fetch or merge by hand before running it.

### Microsoft 365 > Admin shows the changes that matter (2026-11-01)

- **Provisioning apart**: directory sync and provisioning cycles group into one row per service per day ("Example Directory Sync: 144 cycles, all succeeded"), expandable; a failed cycle gets its own row. Admin changes lists people and apps only.
- **Apps by name**: a change written as `ServicePrincipal_<id>` shows the app's name, with an App badge, when the directory audits in the window name it. The id is in the expanded row.
- **Readable columns**: Success or Failure, an event count that opens Search, and the properties changed. Times are in your time zone.
- **Real changes first**: role, policy, credential, and user create, delete, or disable changes rank above routine updates, which are hidden until you untick Hide routine.
- The rail's flyouts open beside the rail instead of over it, and the narrow icon rail's sub-page menus are no longer cut off.
- What changes for existing installs: nothing to do.

### Clock changes (2026-11-01)

- **Repeated hour**: when clocks fall back, a local timestamp without a zone (RFC 3164 syslog) in the repeated hour is placed by when it arrived, or for a file read later by the event before it, and flagged `ambiguous_local_time` in `parse_errors` so you can find it.
- **Skipped hour**: a timestamp in the hour that does not exist when clocks spring forward is read as if the clock had not moved yet and flagged `nonexistent_local_time`.
- The same applies to times inside the message that carry no zone (a firewall's generated time). The flags never mark a parse partial.
- **Charts**: hourly charts in your time zone show the repeated hour as two points instead of one doubled point and one empty one. The comparison with the window before matches days by date across a clock change.
- **Tables and the person Timeline** add the zone to a time in the repeated hour ("1:15 AM PDT", "1:15 AM PST"). The Timeline now groups by your day and shows your clock, like the rest of the app, instead of UTC.
- What changes for existing installs: nothing to do. Events already stored keep their time; search `parse_errors LIKE '%local_time%'` to find new flagged ones.

### Health shows the page rollups; timings in every page response (2026-11-01)

- **Health > Page rollups**: for Attacks and access, Microsoft 365, and AI usage, the days built, closed days still to build, when the last day was built, and when today so far was last built (every 5 minutes). A failed build shows unhealthy; today so far older than 15 minutes needs attention.
- **Server-Timing**: page and query responses say whether they came from the 60-second cache, and how long they waited for a query slot, spent in DuckDB, and spent in the server otherwise. Your browser's network panel shows it under Timing.
- What changes for existing installs: nothing to do. Until the first rollup run after a restart, days still to build reads "not checked yet".
### Operations (2026-11-01)

- **AIDE rules**: with AIDE installed, every update writes `/etc/aide/aide.conf.d/90_aide_remnant`, skipping the data folder's `lake/`, `rollup/`, `tmp/`, `enrichment/`, and `meta.sqlite`, and `frontend/node_modules`. `tls/`, the Python environment, the code, the built UI, and `.git` stay watched. It prints a line when it writes or replaces the file. Re-baselining no longer hashes the lake and 16,000 package files.
- The update script explains git's "dubious ownership" refusal (a checkout owned by another user) and changes nothing.
- The startup line now separates DuckDB threads that can run at once (8 on 4 cores) from the thread limit the server needs (adds the request pool, mostly idle).
- `spill.cleared` is logged on every start, also when nothing was removed.
- What changes for existing installs: on systemd installs with AIDE, the next update writes `90_aide_remnant`; it replaces a file at that path, so remove any other hand-made Remnant rule file, then update with `--aide` to re-baseline.

### Update script reports what it did (2026-11-01)

- `update-systemd.sh` fetches `main` from `origin` itself, before stopping the service. If the fetch fails it says so and exits with an error; it no longer reports success at the old commit.
- Already current: it prints "already up to date at X" and leaves the service running. It reports "Updated to X" only when HEAD matches `origin/main`.
- A checkout with local commits is refused before the service stops.
- What changes for existing installs: nothing to do. If you run the script through your own wrapper, it now exits non-zero when the fetch fails.

### Query memory follows the budget (2026-11-01)

- **Search and export get more memory when it is free**: alone, a search or export can use about 40% of the memory budget (1.6 GB on a 4 GB budget) instead of 20%. Page sections keep their share, and the total never goes past the budget.
- Raising `server.memory_limit_mb` grows both.
- **Disk overflow is capped**: queries that pass their memory write to `data/tmp/duckdb`, at most `server.query_spill_limit_mb` (default 10 GB) for all of them together. The folder is emptied at start, only when it resolves to exactly `data/tmp/duckdb` (a link elsewhere stops the server with a plain message and nothing deleted), and the journal logs the files and MB removed.
- **Out of memory says so**: the error tells you the query ran out of memory and to try a shorter time range.
- The journal has a `query.memory` line when a search falls back to the page share, writes to disk, or fails for memory, with peak memory and MB written.
- What changes for existing installs: nothing to do. Make sure the data volume has 10 GB free for overflow, or set `server.query_spill_limit_mb` lower. The startup log now prints the memory per page section and per search.

### Faster pages, round 3 (2026-10-31)

- **AI usage, AI Watch, the AI inventory, and the person timeline** read today so far from the AI rollup, built every 5 minutes, and only the last few minutes from events.
- **Background builds stay out of the way**: rollup builds run at lower priority with one thread and their own slot, so a page request never waits behind them.
- The person timeline skips rows that cannot be the person before matching names. AI first use still finds people through DHCP, devices, and sign-ins.
- When a data file has no statistics, the start of a source's data is found by a scan instead of being left blank.
- What changes for existing installs: nothing to do. Today's AI facts are kept in `data/rollup/ai/today` (safe to delete; rebuilt within 5 minutes).

### Faster pages, round 2 (owner timings on 4 vCPU, 2026-10-31)

- **Attacks and access** reads a daily rollup of failed sign-ins and VPN logins, like Identity: on the test lake it went from about 2 s to 0.3 s alone.
- **Today so far**: every 5 minutes the server keeps today's Dashboard and Microsoft 365 facts up to a minute ago; pages read only the last few minutes from events. Microsoft 365 > 24 hours is no longer slower than 30 days.
- **Queries share the cores**: by default as many queries run at once as there are cores (2 to 4), each with fewer threads, so the three Dashboard sections loading together no longer slow each other down. `server.query_threads` and `server.max_concurrent_queries` still override.
- **AI Watch** (Dashboard) and **AI usage** are kept for 60 seconds like the Dashboard sections. Any change you make in the app, such as a review, a closed alert, or a setting, clears every kept page, so it shows at once.
- AI Watch counts days in your time zone.
- `/ai/watch` opens AI usage > Settings, where AI Watch is set up (it used to fall through to Health).
- Search names only the sources a query can read also when the query uses `WITH` or `UNION` and every part filters `template_id`.
- What changes for existing installs: nothing to do. The new auth rollup builds after the next lake compaction (`data/rollup/auth`, safe to delete). On a 4-core server, queries now default to 4 at once with 2 threads each (was 4 with 4).

### People and pages (owner walkthrough, 2026-10-31)

- **One person, one row**: the top bar search merges the forms of a name that are the same person (short name, `DOMAIN\user`, organization email, and aliases set on Settings > Identities) and lists the others ("also robin, CORP\robin").
- **Possibly the same person**: a person's timeline lists other names seen on their devices that read as the same person ("robin" beside "robin.okafor@..."). Administrators can make one an alias with one click; nothing is merged without that.
- **Addresses**: a person's "From addresses" counts where they were. Microsoft 365's own addresses on server-side records (Exchange Online and the rest, AS 8075 or Microsoft's published ranges) are shown apart ("12 + 165 Microsoft 365") instead of inflating the count.
- **One way to do each thing**: the per-page Refresh buttons on AI usage, Agents, Health, and People & devices are gone (the top bar's Refresh covers the page). Agents > Overview has one time control. People & devices no longer has its own search box or the Entity / AI flow switch: open a person, address, host, or AI service from the top bar search, or a service's AI flow from its page.
- **AI usage > Services**: review status and allowed data show as text in the table; administrators change them under the row with **Review**. Times are in your time zone.
- What changes for existing installs: nothing to do.

### Charts, sources read, and polish (owner walkthrough, 2026-10-31)

- Dashboard and Microsoft 365 charts count **your** days: the browser sends its time zone and a day runs from your midnight. Hours and dates on those pages are in your time zone (no more "Nov 1" on the evening of Oct 31 in Pacific time).
- A chart no longer draws zeros before its source existed: those points are hatched and the note says "no data before Oct 21".
- Today (or this hour) is still filling, so its point is drawn dashed and labeled "so far" instead of reading as a sharp drop.
- Search's results header names only the sources a query can read: a query with `template_id = 'm365_signin'` reports the Microsoft 365 source, not every source you have (read from file statistics, so nothing extra is scanned).
- **Alerts**: with nothing to decide, the page shows the last five closed alerts under the empty queue.
- The Search page's **Library** button is announced as "Library" (its hint stays on hover).
- What changes for existing installs: nothing to do. Day totals on the Dashboard and Microsoft 365 pages follow your time zone, so they can differ from UTC days by a few hours' events.

### Faster pages (owner walkthrough, 2026-10-31)

- **Dashboard**: Identity now reads the Microsoft 365 rollup instead of parsing every failed sign-in, and each section loads on its own, so a slow one no longer holds up the page. On a test lake sized like a busy office (390,000 DNS, 100,000 auth, and 26,000 Microsoft 365 events a day, 2 vCPU) the 30-day sections went from 14 s to about 1 s.
- Dashboard sections and Microsoft 365 > Overview are kept for 60 seconds per window: a reload in that minute is instant. Each view is still audited (`cached: true`).
- AI usage and AI Watch run their independent reads together.
- **Person timeline**: first use of AI services reads closed days from the AI rollup, not days of raw DNS, which is what ran out of memory for a busy person at 7 days.
- The browser no longer asks twice: an answer is reused for 30 seconds across the page's cards, and a request the server answered (including "busy") is not sent again automatically.
- **Open in Search** from any page now writes the window as `{{start}}` and `{{end}}` and opens Search on the page's exact window (shown as the selected time range, for example "Oct 3, 12:00 AM to Nov 1, 3:12 PM"). Picking another range reruns the same query over it, and a saved copy no longer freezes on the page's dates. The "From ..." line shows times in your time zone.
- What changes for existing installs: nothing to do. Numbers on the Dashboard and Microsoft 365 pages can be up to a minute old; reload after a minute for the latest.

### Inbox rules read for what they do (D132)

- Microsoft 365 > Mail lists each inbox rule's settings as columns: rule name, from, sent to, subject words, action and folder, stop processing.
- Each rule has a class: **organizing** (files mail into a named folder), **hiding** (Junk Email, RSS Feeds, Archive, Conversation History, Deleted Items, or mark read and move), **deleting**, **forwarding** (internal or external), or other. Only hiding, deleting, and external forwarding are risky. A risky rule that watches for invoice, payment, wire, password, MFA, bank, or payroll words, or for mail from finance, IT, security, or leadership addresses, is high severity (business email compromise hides replies this way).
- One person's rules with no gap over 24 hours are one row ("dana@example.com created 62 rules Oct 29 to 30: 60 organizing, 2 hiding"), risky ones first, with the list underneath.
- The Dashboard card is now **Risky mail rules**, with organizing rules as a separate count; Microsoft 365's count row shows the same numbers. DLP matches have their own list on the Mail tab.
- What changes for existing installs: nothing to do. The Dashboard's mail rule count drops to the risky ones; the organizing count beside it opens the rest.

### Live fixes (owner feedback, 2026-10-31)

- Opening a row in Live, or scrolling down, no longer lets new rows push it away or open a different row: new events wait in an "N new events. Show" bar until you click it.
- Live says how events actually arrive: "Sources are about 3 min behind; new events arrive about every 30 s" when sources deliver in batches.
- **Start with the last 5 min** beside the Live switch fills the table with what arrived in the last 5 minutes, so it is not empty while slow sources catch up. The choice is remembered in this browser.
- What changes for existing installs: nothing to do.

### Microsoft 365 Overview from a daily rollup (ADR-0041)

- Microsoft 365 > Overview now reads closed days from a small daily rollup per source and only today (and any partial day) from events. On a test tenant with 60,000 sign-ins a day the 30-day Overview went from 34 s to under 2 s on 2 vCPU, with the same numbers. 24 hours and 7 days use it too.
- Changes and consents reported by both Graph and the Management API are still counted once, also when the two feeds are separate sources and when the copies fall either side of midnight.
- The spike tooltip breaks a tie by name, so it no longer changes between loads.
- What changes for existing installs: nothing to do. The rollup builds after the next lake compaction, up to 60 days per run (a few minutes on a busy tenant); until a day is built it is read from events as before. It lives in `data/rollup/m365` and can be deleted at any time; it is rebuilt.

### Rail, Dashboard, and Microsoft 365 fixes (owner feedback, 2026-10-31)

- **Rail**: groups are now Monitor, Investigate, AI, Connected apps (Microsoft 365; future connectors go here), and System. Connected apps and System start folded the first time; every group remembers open or closed in this browser. Hovering a folded group shows its pages in a menu. Each area's sub-pages fold too (the arrow at the end of its row); Alerts starts folded, since its row shows the open count, and opens its pages on hover. Rows are a little tighter, so the rail fits a 1920x1080 screen without scrolling in its default state.
- **Dashboard, Failures by host**: the per-day bars span the row again (the 20 px bar limit no longer applies to these rows).
- **Microsoft 365, Failure reasons**: a failed sign-in stored without a reason column (events from before `m365_signin` 1.1.0) now takes Entra's own text from the record, and the error code shows beside it ("Invalid username or password. (50126)", or "Error 50053" when only the code is known). "No reason given" means the record has neither. Each row still opens exactly those sign-ins.
- **Mail rules**: one definition for both pages. The Dashboard's "Inbox rules and forwarding" is Microsoft 365's Mail rules plus Forwarding, and says so. Each Exchange record is one change, so two rules made by one person in the same minute now count as two on the Dashboard (they were counted once, which is why it showed fewer).
- **Interrupted and failed chart**: the tooltip names the person and the app with the most failed or interrupted sign-ins at that hour or day, so a repeating spike (a stale password on a scheduled job) reads without clicking.
- What changes for existing installs: nothing to do. The Dashboard's inbox rule count may go up to match Microsoft 365 > Overview.

### CLI and TUI follow on the live stream (ADR-0036 part 3)

- `remnant tail -f` and the TUI tail pane now read the server's live stream instead of polling. They share Live's limits and audit: each counts toward your 2 live searches, stops at the live time limit with a message, and writes one start and one stop audit row instead of one per poll.
- The TUI's Ctrl+T pauses the tail by ending the stream; pressing it again resumes from the last line shown.
- `--interval` on `tail` is still accepted and ignored (the server follows every 2 seconds); the TUI's `--interval` is likewise ignored.
- What changes for existing installs: a long `tail -f` now stops after the live time limit (30 minutes by default; an administrator can raise it to 24 hours). Run it again to keep following.

### Live on Search (ADR-0036 part 2)

- A **Live** switch beside Run on the SQL tab follows new events of the query as they arrive: newest at the top, the last 500 kept, new rows tinted briefly (no motion when your system asks for reduced motion).
- Above the table: "Live since 14:02 UTC" and each source's freshness ("fw-edge 3 s, m365 4 min (pulls every 5 min)"); a source quieter than expected is in the warning color.
- **Pause** ends the stream on the server and keeps your place; **Resume** starts again from the last event shown and first fills in what arrived while paused. **Stop** ends Live. **Export** downloads the query's rows since Live started (audited as any export).
- A query that cannot go live says why ("Live works on event rows. Remove GROUP BY, or use Run."). A third live search lists your open ones, each with Stop.
- Settings > About has the **Live search time limit** (administrators).
- A shared Search link never starts Live: the switch is not part of the address.
- What changes for existing installs: nothing to do.

### Live search, server side (ADR-0036 part 1)

- `GET /api/search/live?q=<sql>` follows new event rows of a row query as server-sent events (`start`, `rows`, `lag`, `notice`, `end`). It polls every 2 seconds on your own sources through the query guard. Queries with GROUP BY, aggregates, DISTINCT, window functions, UNION, WITH, joins, or LIMIT are refused with the reason ("Live works on event rows. Remove GROUP BY, or use Run.").
- At most 2 live searches per person (browser, CLI, and TUI together); a third is refused naming the open ones, which can be stopped (`GET /api/search/live/streams`, `DELETE .../{id}`). Each stops after the live time limit, one administrator setting (default 30 minutes, `PUT /api/settings/live`, audited `settings.live_limit`). More than 1,000 new events in one poll stops the stream and says so; Resume (`since`) first sends what arrived while paused, the newest 1,000.
- A stream ends at the next poll if your source access shrinks. Each source's freshness is sent every 10 seconds, with a connector's pull interval.
- One audit row at start (`search.live_start`, with the SQL and its hash) and one at stop (`search.live_stop`, with the reason, duration, and events sent).
- Live reads events whose own time is within a day before the stream started; an older event that arrives late is in Search, not in Live.
- What changes for existing installs: migration 58 adds the time limit setting. Behind nginx, see `docs/install/tls.md` for the Live location block. The Search toggle and the CLI move to this stream in the next changes.

### Dashboard: Add a pack (ADR-0033 row 5)

- In a dashboard's settings (Edit), **Add a pack** lists the query library packs that fit your sources. Tick queries and **Add**: each becomes your private saved search (your existing copy if you have one), a private schedule with the query's suggested interval (hourly or daily, last 24 hours) and flag, and a panel in a section named after the query's group. Each panel runs once at once so it fills.
- Everything made is an ordinary saved search, schedule, and panel you can change or remove. Each is audited as if made by hand (`search.create`, `schedule.create`, `dashboard.panel_add`, with the library entry).
- What changes for existing installs: nothing to do.

### Query library (ADR-0033)

- **Search > Library** lists shipped, tested queries for the sources you have, in five packs: Microsoft 365 (identity, mail, apps and consent, admin, Copilot, data), Linux sign-ins and privilege, Palo Alto firewalls, DNS and AI services, and ingest health. A query appears only when a source you can read sent events from one of its templates in the last 30 days.
- Clicking a query loads its SQL into the SQL tab, unsaved, with why it matters and what normal looks like above the editor. Running it is the normal Run, through the guard, on your own sources.
- **Save as my own** makes a private saved search (audited `search.create`, with the library entry). When a later version changes a query you copied, the Library shows **Updated in this version** with the difference and **Replace my copy** (audited `search.update`). Your copy is never changed without that.
- Every library query runs in CI on the template fixtures of its sources, so a template change that would break one fails the build.
- The eight example saved searches moved into the library; `examples/saved-searches/` now points there.
- Command palette: **Query library** (also found by typing "grimoire").
- What changes for existing installs: nothing to do. Searches you imported from the examples stay as they are. The image now includes `library/`; a systemd install from the repository reads it from there.

### Likely cause: a first-seen destination

- When no earlier row failed or was blocked, **Likely cause** now marks the nearest earlier row whose destination (host, app, or address) the person or device had not reached in the 30 days before. Its tooltip says which rule picked it. Still a hint; no model is called.
- What changes for existing installs: nothing to do.

### Person page: Sessions, Sign-ins, and Alerts tabs (ADR-0038 row 27)

- A person's page now has five tabs: Summary, Timeline, **Sessions** (Claude sessions in the last 30 days, each opening in Agents), **Sign-ins** (their Microsoft 365 sign-ins in the last 7 days, with outcome), and **Alerts** (alerts that name them, any state).
- The Timeline also lists alerts about the person in its window; an alert row opens the alert.
- `GET /api/ai/sessions?person=` filters sessions to one person under any form of the name.
- What changes for existing installs: nothing to do. Alerts raised before migration 57 name no one, so they do not appear.

### Alerts name who and which devices they are about

- New alerts record the people and devices in the rows that fired: from the run's kept rows, or for a rule run from the matched events (read from the sources the run read). AI Watch items record the person for sensitive-data and Claude Code items, and the people and devices for a service or MCP server. At most 20 of each.
- The alert shows them as links under **People** and **Devices**. `GET /api/alerts?person=` lists the alerts about one person under any form of the name, for the person page.
- Rows that fired from a rule now have **Around** beside each event: the rows within 5 minutes by the same person or device.
- What changes for existing installs: nothing to do. Migration 57 adds the two columns; alerts raised before it have no people or devices.

### Person timeline (ADR-0038 section 9)

- A person's page in People & devices has **Summary** and **Timeline** tabs. Timeline shows one row per action, newest first, grouped by day: Microsoft 365 sign-ins (per app, outcome, and hour), Claude sessions (one row each), AI services first used in the window, app consents, Microsoft 365 audit operations (counted once across Graph and the Management API), and other events grouped by source, message, and hour. Failures are in the warn color; nothing uses severity colors.
- The person is matched across forms of the name (`dana.k@example.com`, `EXAMPLE\dana.k`, and admin aliases); the forms and devices seen are listed under the title.
- Each row opens its own events in Search; **Open in Search** opens all of them. Windows: 24 hours, 7 days, 30 days. Every view is audited `search.timeline`.
- What changes for existing installs: nothing to do.

### Around this event (ADR-0038 section 8)

- Every expanded event in Search (and in the Microsoft 365 lists and saved-search runs) has **Around this event**: the rows within 5 minutes either side by the same person or the same device, from every source you can read, at most 50 (the nearest in time), newest last. Each Agents session step has **Around** too.
- When the event names no person, the person who held its source address then (logons, User-ID, VPN, sign-ins) is used, so a proxy row with only an address joins the person.
- **Likely cause** marks at most one row, in the accent tint: the nearest earlier row from another source with a failure status, or a message that says denied or blocked. The rule is in its tooltip. It is a hint; it never raises or closes an alert. No model is called.
- **Open in Search** opens the same window as SQL. Every lookup is audited `search.around`.
- What changes for existing installs: nothing to do.

### AI usage: Inventory tab (ADR-0038 section 7)

- **AI usage > Inventory** lists everything AI seen in the last 30 days in one table: AI services, agents, MCP servers (from telemetry, the MCP inventory, and the hooks plugin), and Microsoft 365 apps with a granted consent. Each row has type, review status, people, devices, first and last seen, and where it was seen.
- Filter by type (with counts), switch between **Active** and **Excluded**, and group by type or status. An admin can exclude an item with a reason; it moves to Excluded with who excluded it and when, and still shows in Search, alerts, and AI Watch. Audited `ai.inventory_exclude` and `ai.inventory_include`.
- **Export CSV** and **Export JSON** of the current view, for admins and analysts. Every export writes an `ai.inventory_export` audit row with its filters and row count. CSV cells that start like a formula are escaped.
- What changes for existing installs: nothing to do. Migration 56 adds the exclusions table.

### Agents: Overview and Tools tabs (ADR-0038 section 6)

- **Agents > Overview** is the area's first tab: sessions, people, tool calls, failed tool calls, not-approved MCP servers in use, and devices delivering late (records an hour or more behind, the plugin's offline queue), each against the window before and each opening its rows in Search. Devices that sent before the window and nothing in it are named under the numbers.
- **Agents > Tools** lists every built-in tool and MCP server Claude Code called, with type, review status, people, devices, calls, failures, and first and last seen. Each name opens its calls in Search.
- One time window (24 hours, 7 days, 30 days) for both tabs, remembered per browser.
- What changes for existing installs: `/agents` now opens Overview; Sessions moved to `/agents/sessions`. Older links (`/ai#agents`, `/agents#session=...`) still open Sessions.

### Refused credentials are events, with a built-in alert (ADR-0040)

- Every refusal the server makes is now an event in a built-in **server_events** source: refused ingest tokens, refused sign-ins (wrong password, the sign-in rate limit, single sign-on refusals), and refused API tokens, with the address and the reason. Never a password or a token: only a token's id or its first 8 characters. At most 300 a minute are written; the rest are counted.
- A built-in detection, **Refused credentials from one address**, is **on by default**: one High alert per address per hour when an address has 10 or more refusals in 10 minutes. It is on Alerts > Rules, where an admin can turn it off or change the threshold. Other starter rules stay off.
- What changes for existing installs: the `server_events` source appears after the first refusal, visible to admins only until you grant it to a group.

### Feeds: "Out of date" after a successful check (F67)

- A feed whose list has not changed (the server answers Not Modified, or this month's GeoIP edition is already installed) now counts as current from that check, not from when the content last changed. Enrichment shows "Content unchanged, confirmed current 2 min ago" under the download date, and Health uses the same time.
- A threat list that answers Not Found is no longer treated as unchanged: the row shows "The feed server answered HTTP 404". Other failures already showed their reason and are logged as `enrichment.update_failed`.
- What changes for existing installs: nothing to do. The next check of each feed records it.

### Settings > Single sign-on (F64)

- New **Settings > Single sign-on** page: whether sign-in with your identity provider is on, off, or not working (and why), the issuer and client ID in use (never the secret), the exact redirect URI to paste into Entra with **Copy**, the variables to set, **Test sign-in** (reaches the provider and checks its issuer; audited `sso.test`), and who is bound to an identity. Users and access links to it.
- What changes for existing installs: nothing to do. The setup stays server-side, as before.

### Settings > Claude plugins, with a token per deployment

- New **Settings > Claude plugins** page: the hooks plugin for Windows and for macOS and Linux, each with its version, script SHA-256, devices and lost records in the last 24 hours, and two downloads (the plugin, and the managed bundle with `hooks.conf` for endpoint management).
- Each download carries a **named token** ("pilot", "all Windows"): pick an existing one to download the same deployment again, or name a new one. The token list shows each token's first characters, last use, and devices; **Revoke** stops one deployment and leaves the others sending.
- What changes for existing installs: a plugin download no longer replaces the source's token, so copies already installed keep sending. The source's existing token is listed as **Earlier token** and can be revoked there.

### Agents: sessions list and detail, and Claude accounts

- **Sessions** shows the list and the open session side by side, with the session's Claude account tier and evidence, start, calls, failed calls, tools and hosts, and late delivery, then its steps. The open session is in the address, so a link opens it.
- New **Accounts** tab: Claude accounts the hooks plugin reported, by tier (ADR-0030 amendment). A company-domain email is **confirmed** by an Entra sign-in to Claude by the same person in the 30 days before its last use; without a Microsoft 365 source it is **reported**; with one and no match it is **not confirmed**; other domains are **Personal**; no email is **Not checked**. Nothing is blocked or alerted from a tier.
- The Entra app is matched by name (containing "Claude" or "Anthropic"). The Anthropic usage report corroboration (T3) is not used yet.
- What changes for existing installs: set Settings > Identities > organization email domains if you have not, or every account reads Not checked. New `GET /api/agents/accounts`.

### Microsoft 365 area under Monitor

- New **Microsoft 365** area (Monitor > Microsoft 365) with Overview, Sign-ins, Mail, Apps, and Admin tabs and one time window. Overview has sign-ins, failed, outside approved countries, risky, app consents (blocked apart), and admin changes; counts of mail rules, forwarding, DLP matches, file downloads, external shares, and Copilot interactions; the sign-in outcomes; and top failure reasons, countries, and apps. Every number opens its rows in Search; the other tabs list the window's events.
- Sign-ins Entra interrupted (MFA asked, stay signed in, and the like) are now **interrupted**, not failed. The Dashboard's Identity "Failed sign-ins" count, its chart, and top failing users use the same split, so they may read lower than before.
- What changes for existing installs: nothing to do. New `GET /api/m365/overview`.

### AI Watch: every number opens its rows in Search

- Unapproved AI services, People using unapproved AI, the "devices not matched to a person" line, App consent grants and blocked attempts, and Sensitive data to AI each open Search with the rows behind them; the change pill opens the period before; a day on the AI use chart opens that day's use by service. New agents and MCP servers open the review queue (they are review items, not events).
- The AI use queries list only the services the card counts (plus any more specific catalog domain under them), so they stay readable; they read events directly, so a 30-day one can take a few seconds.
- What changes for existing installs: nothing to do. `/api/ai/watch/summary` adds `before`, `chart_drill`, and `drill`, `drill_before`, `devices_drill`, `blocked_drill` on cards.

### Dashboard: every number opens its rows in Search

- On Identity, Attacks and access, and Detections, click a number to open Search with the query behind it, already run over the page window. The change pill opens the window before; a point on the failed sign-ins chart opens that hour or day; a "Failures by host" or "Matches by rule" row opens that host's or rule's rows; a Top sources row opens its addresses; "2 blocked" opens the blocked consents.
- Search says where the query came from ("From Dashboard > Identity > Failed sign-ins, Oct 24 to Oct 30"), and Save and Schedule work as for any query. Back returns to the Dashboard where you were.
- Counts by country or network use `ip_country`, `ip_asn`, and `is_internal` in the query, so it reads as a filter, not a list of addresses. Detections open the matched rules' own conditions.
- What changes for existing installs: nothing to do. `/api/dashboard/sections` adds `before` and a `drill` query on each number, series, and row.

### Search: country, network, and internal-address functions

- Four functions work in any search: `ip_country(ip)`, `ip_asn(ip)`, `ip_org(ip)`, and `is_internal(ip)`. They answer from the local GeoIP files and your Internal networks list, never the network. See `docs/searching.md`.
- They are what Dashboard numbers will open in Search (ADR-0039), so counts like "external sign-in failures" and "outside approved countries" can be shown as a readable query.
- What changes for existing installs: nothing to do. The backend adds `numpy` (DuckDB needs it for server functions).

### Dashboard: no comparison without history, and why an address has no country

- A Dashboard section, and AI Watch, now compares with the window before only when the sources behind it have data for at least 90% of that window. Until then the header says "No comparison yet: data starts Oct 21" and each card says "Not enough history for comparison" instead of showing a change.
- **Top sources** no longer groups addresses as "Unknown". Each row says why there is no country: Not an address, Not a public address, Not in GeoIP file, or No GeoIP file. When the GeoIP file does not list some addresses, a note gives its install date and, for admins, an Update GeoIP link.
- Fixed: the Dashboard looked up countries for only the first 1,000 addresses, so the rest showed as Unknown. It now looks up every address the card counts (up to 5,000).
- What changes for existing installs: nothing to do. `/api/dashboard/sections` adds `history` to each section and `geoip_date`; `/api/ai/watch/summary` adds `compared` and `since`.

### Dashboard: shorter trend charts

- **AI use** is a stacked area by day: approved at the bottom, then unreviewed, then not approved. Point at a day, or use the arrow keys, for its values and total.
- **Failed sign-ins** (Identity) is one amber line, hourly for 24 hours and 7 days and daily for 30 days, with the window before as a faint dashed line to compare against.
- Dashboard charts are at most 160 px tall, and bars in the "Failures by host" and "Matches by rule" rows are at most 20 px wide.
- What changes for existing installs: nothing to do. The `/api/dashboard/sections` field `identity.failed_by_bucket` is replaced by `identity.failed_trend` (points, counts, and the window before).

### Dashboard: one time window and three new sections (ADR-0038 edit 10)

- The Dashboard has one time window, **24 hours**, **7 days**, or **30 days**, beside its title; AI Watch and the new sections follow it, and each says once what it is compared against.
- **Identity** (from Microsoft 365): failed sign-ins, sign-ins outside approved countries, inbox rules and forwarding, app consents, admin role grants, Conditional Access edits, failed sign-ins per day, and top failing users.
- **Attacks and access**: sign-in failures from external addresses, attacking addresses, countries, VPN logins outside approved countries, failures by host (one row each), and top countries and networks.
- **Detections**: rule matches, rules that matched, hosts and users involved, matches by rule, and the hosts and users involved.
- A section shows only when you have its source. KPI numbers are larger on wide screens, with the change as a small pill beside the number.

**What changes for existing installs:** set **Approved countries** and add your company's egress to **Internal networks** (Settings > Enrichment); until then those cards ask for them and office addresses count as external. AI Watch's own 7 or 30 days buttons are gone; with 24 hours its chart still shows 7 days.

### Settings: approved countries and internal networks (ADR-0038 edit 10)

- Settings > Enrichment has a new **Countries and networks** box. **Approved countries** takes two-letter codes (US, CA) and shows their names. **Internal networks** takes addresses and ranges, private or public.
- Internal networks start as the private, loopback, and link-local ranges. Until a public address is listed, the box asks for the company's egress addresses, since office sign-ins and VPN logins come from them.
- The Dashboard's Identity and Attacks sections use both (next release). Saving is in the audit log as `enrichment.places`.

**What changes for existing installs:** a database migration adds the two lists; both start empty or at the private ranges. Nothing counts differently until the Dashboard sections ship.

### Search finds addresses, people, hosts, and AI services (ADR-0038 edit 10)

- Type in the top bar search: an address ("203.0.113"), a user, a host, or an AI service is listed with its country and network or its event count; pick one to open its page. Pages, saved searches, and sources still show, and **Search events for "..."** opens Search on the last 7 days.
- Only values from the sources you can read are offered (the last 30 days). Each lookup is in the audit log as `investigate.lookup`.

**What changes for existing installs:** nothing to do. Typing two or more characters asks the server once typing pauses.

### Shell: grouped menu, centered search, density (ADR-0038 edit 10)

- The left menu is wider (240px) with larger rows, in four groups you can fold: **Monitor** (Dashboard, Alerts), **Investigate** (Search, People & devices, Saved searches), **AI** (AI usage, Agents), **System** (Health, Settings). Every page lists its sub-pages, the current one highlighted; folded groups stay folded in that browser.
- The search sits in the middle of the top bar and is wider; Ctrl K still opens it.
- "Updated" shows once, in the top bar; the Dashboard no longer repeats it under its title.
- Your name in the top bar opens a menu with your account, **Density** (Comfortable or Compact), and Sign out. With no choice, screens 1440px and wider get comfortable rows, narrower ones compact.

**What changes for existing installs:** nothing to do. Bookmarks and links keep working; screens narrower than 1440px start with compact rows until the person picks Comfortable.

### Dashboard: Needs you and AI Watch restyled (ADR-0038, part 2)

- **Needs you**: the first column is severity only (High, Medium); what fired says its kind in the text ("Schedule: Failed SSH by address: 32 addresses over threshold (0)", "Source gap: ...", "AI Watch: ...", "Rule: ...").
- Flagged runs say what they counted: "32 addresses over threshold (0)", "1 source under threshold (1)", "12 rows, was 4: changed 200%", never "32 is above 0". The noun comes from what each row is (addresses, people, devices), or the panel's own label.
- **AI Watch** stays one block with its 7 or 30 days toggle, and everything in it follows the toggle: the cards, the chart (now 7 bars for 7 days), and top services.
- Cards: an (i) on each says what it counts; the change against the previous period is a neutral pill with an arrow ("↓ 6 vs previous 7 days"); the context line wraps to two lines and shows the rest on hover.
- The chart has a y axis with three ticks and dated labels, prints each day's total when it shows 7 days or fewer, and shades the days after the AI sources' newest event with a thin hatched band, saying "no data after Oct 25".

**What changes for existing installs:** runs flagged before the update keep their old reason text ("32 is above 0"); new runs use the new wording.

### Fixed: AI Watch and AI usage failing with query_memory after the people fix (#276)

- #276 read older days' logon, User-ID, VPN, DHCP, and sign-in events straight from the lake, and treated every day built before it as not yet checked, so on a busy install AI Watch and AI usage read 30 days of raw DNS again and failed with `query_memory`. Closed days are read from the AI rollup again, always.
- Who had an address on a closed day now lives in a small file per day beside the rollup (`ident.parquet`): the identity observations reduced to the first and last of each mapping per hour. The address lookup joins those to the rollup's per-hour rows; closed days' events are never opened for it.
- Days built before this get their identity file from a re-check that runs every maintenance tick (about every minute, at most 20 seconds each), newest days first, logged at INFO: `rollup.recheck.started` (days), `rollup.recheck.day` (source, day, rows, left), `rollup.recheck.finished`.
- Until a day is re-checked, AI Watch and AI usage load without people for it and say "Rebuilding people for N of M days". They never fail for it.
- New scale test (`-m scale`): 300k DNS and 100k Linux sign-ins a day for 30 days, DHCP and Microsoft 365 sign-ins, a rollup built before the identity files; every AI page under the default share of a 4 GB server, and no AI use query opens a closed day's events. It fails on the previous release.

**What changes for existing installs:** after the update, people come back over the first few minutes as the re-check runs (watch for `rollup.recheck.finished`); pages load the whole time.

### Fixed: people on closed days, and app names on older sign-ins

- AI usage and AI Watch showed 0 people for every service over ranges of 2 days or more. Since F63, closed days were read from the AI rollup and their event files skipped, including the logon, User-ID, VPN, DHCP, and sign-in events that say who had an address, so use on closed days had no person. (The first fix read those days live and was replaced: see the query_memory fix above.)
- The consent card named an app "an app with no name" when the person's sign-in just before was stored before the sign-ins parser 1.1.0: those sign-ins carry the app only in `message`, which is now used.

**What changes for existing installs:** after the update, the next rollup run checks each existing day once; until then those days are read live (slower on a busy install for a few minutes, never wrong).

### Navigation, second pass (ADR-0038)

- The open area lists its pages under it in the left menu, the current one marked; other areas stay one line. In the icon-only menu (768 to 1100 px), hovering or focusing an area shows its pages. The tabs in the page header stay.
- **Jump to** (Ctrl+K) lists every page by its own name: "MCP servers", "Rules", "Endpoint agents", "People & devices".
- "Security workspace" is gone from the top bar. An admin can set an optional **install name** under **Settings > About and licenses**; it shows in the top bar to signed-in people only (never on the sign-in page), and nothing shows when it is unset. Changes are audited (`install.update`).

### AI Watch: closing an alert can review it; "not reviewed" opens those alerts

- Closing an AI Watch alert for an AI service or MCP server asks for its review status: **Leave unreviewed** (the default), **Approve**, or **Not approved**. Approve and Not approved change it on AI usage too, audited as `ai.service_change` or `ai.mcp_change` with `via: alert.close`. Administrators only; analysts still close, and the status stays not reviewed.
- AI Watch's Unapproved AI services card shows **N not reviewed** as a link to the AI Watch alerts whose service or MCP server is still not reviewed, open and closed (`/alerts#review`). Approve and Not approved are offered on closed ones too.

**What changes for existing installs:** alerts you closed before this keep their service not reviewed; they now appear under **N not reviewed**, where you can approve or not approve each one.

### Areas with tabs (ADR-0038, part 1: navigation)

- The left nav lists **areas**, one row each with an icon: Dashboard, Alerts, Investigate, AI usage, Agents, Health, and Settings at the foot. Between 768 and 1100 px wide it shows icons only.
- Each area's tabs sit in the page header, under its title, and every tab has its own address: `/investigate/search`, `/investigate/people`, `/alerts/rules`, `/ai/people`, `/agents/mcp`, `/health/enrichment`.
- **Detect** is now part of **Alerts** (Rules and Schedules tabs). **Investigations** is now **People & devices** under Investigate. **Agents** and **MCP servers** moved from AI usage to the new **Agents** area. AI usage's Claude usage tab is now **People**, and Review and alerts is now **Review**. Health's last tab is **Delivery**.
- The top bar has **Updated N min ago**, **Refresh** for everything on the page, an **Alerts** button with the open count, and the theme toggle as a sun or moon icon.
- No breadcrumbs: the area and its open tab say where you are.

**What changes for existing installs:** old addresses keep working. `/search`, `/saved`, `/rules`, `/schedules`, `/investigations`, and `#tab` links such as `/ai#mcp` and `/health#agents` open the same place at its new address, so links in alert messages already sent still land right.

### AI Watch: app consents counted once, blocked attempts apart (F66, part 2)

- **App consent grants** counts granted consents only, once each: Graph and the Management API report the same consent, and they are matched by correlation id (else person, minute, and operation). Blocked attempts show under it ("2 blocked consent attempts", "Blocked: Lab Notes App (User.Read) by erin@example.com").
- The card names the app and the permissions asked for. When Entra writes "Unknown", the name comes from another record of the app id, else from the person's sign-in up to 60 seconds before.
- Every AI Watch card opens its rows: the consent counts open the consents in Search, one row per consent with both feeds' event ids.
- Ask knows app consents: the vocabulary says to count distinct correlation ids, and the accuracy suite has six consent questions (116 in all).

**What changes for existing installs:** the consent count can go down: a consent both feeds reported used to count twice, and blocked attempts used to count as grants. Consents stored before the F66 parser update have no correlation id, so they are matched by person and minute.

### Microsoft 365: app, permissions, failure reason, and correlation columns (F66, part 1)

- Six new columns: `resource_name` and `resource_uid` (the app and its application id), `resource_type`, `status_detail` (why a result failed), `privileges` (permissions asked for), and `metadata_correlation_uid`. The correlation id column is **`metadata_correlation_uid`** (there is no `correlation_id`): Graph `correlationId` and Management API `InterSystemsId` land there, confirmed equal for the same consent on a live tenant. Column table: `docs/searching.md`, Microsoft 365 columns. The directory audit, Management Activity, and sign-in parsers fill them; a Graph record and the Management Activity record of the same operation carry the same correlation id.
- Consent records now name the app even when Graph writes "Unknown" in the display name, from the app id in the additional details. Consent type and the resource the permissions are for stay in `unmapped`.
- Parsers declare what an update changes. **Sources** shows each recent parser update, the day it started on this server, and any saved search or scheduled search that filters on a column whose meaning changed (admins only; `GET /api/templates/changes`).
- New parser step `find`: picks the item of a list whose key equals a value (for the name/value lists Microsoft uses).

**What changes for existing installs:** the new parsers apply to events received after the update. Events already stored keep the mapping they were parsed with, so the new columns are empty before that day (the Sources page says which day). No existing column changed meaning.

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
