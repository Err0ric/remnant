# Release notes

## Unreleased

<!-- unreleased:start -->

### One outcome rule for the access card and the entity pages (2026-11-18)

- The address page's "Sign-ins and access" card and the person, address, and host pages' "What it did" and lanes now read an event's outcome (allowed, denied, signed out, succeeded, failed, not counted, other) from one SQL function, `access_outcome`, that every query defines, instead of two copies of the rule.
- The library query "Sign-ins and access for one address" (Addresses pack 1.0.1) calls that function, so its SQL is shorter; its rows and counts are the same, and it reads the Microsoft 365 error code only on Microsoft 365 sign-ins, as the entity pages do.
- Each row of What it did opens exactly its own events in Logs: a sign-in with no outcome recorded (Other) no longer opens the person's other sign-ins to the same target as well, and a row with no user or no target opens only the events without one, not those of every user or target.
- What you will notice: an Other row, or a row with no user or no target, in What it did opens only its own events; the SQL of that library query is shorter in Library and Logs.
- What changes for existing installs: nothing to do. A copy of the Addresses pack's query saved before the update keeps its own SQL and shows as updated in Library. To go back, install the previous version as in `docs/install/` (`update-systemd.sh --rollback`).

### People & devices: faster person, address, and host pages, and a faster AI usage count (2026-11-17)

- A person's page loads in a fraction of the time: the entity pages' sign-in rule reads the Microsoft 365 error code only on Microsoft 365 sign-ins, instead of from every line in the range (the page went from 7.1 s to 0.9 s on the speed check's lake; the sign-in summary query alone from 6.7 s to 0.14 s); the person's activity chart counts failures the same way. Address and host pages gain the same way, and read only their own rows' records (1.5 s to about 0.5 s for an address over 30 days of the work install's volume).
- A person's lanes find their rows with a quick name match before the exact identity test, as the summary above them already did.
- The People & devices ranking reads who used an unreviewed AI service from the daily AI rollup for the day the range starts in too, as AI usage does, instead of reading that day's network logs again.
- The AI usage count in the side rail reads only services and MCP servers, the only items with a review status, and no longer the agents and Microsoft 365 apps.
- Every number, list, and link is the same as before.
- What you will notice: person, address, and host pages open much faster; the People & devices list itself is about as fast as before; nothing else changes.
- What changes for existing installs: nothing to do.

### Ask's time limit in Settings > AI providers (2026-11-17)

- An Admin can set Ask's time limit, the longest one Ask model call may take, in Settings > AI providers (Ask time limit), from 5 to 3600 seconds. The help says: "CPU-only local models may need 240 s or more."
- A saved value takes the place of `ask.model_timeout_s` from the config, and "Use the configured value" clears it; the page says whether the limit in force is saved there or from the install's configuration. Each change is in the audit log as "Changed the Ask time limit", with the old and new value.
- The live search time limit in Settings > About and licenses is drawn by the same control; it looks and works as before.
- What you will notice: Settings > AI providers has an Ask time limit box an Admin can change.
- What changes for existing installs: the default stays 90 seconds, or what `ask.model_timeout_s` says, until an Admin saves a value. CPU-only local models may need 240 s or more. To go back, click "Use the configured value"; rolling back as in `docs/install/` (`update-systemd.sh --rollback`) also works, and the older version ignores the saved value.

### Address resolution reads DHCP lease ended lines (2026-11-17)

- Where an address is matched to a machine (People & devices, the person and address pages, AI usage), a DHCP lease now ends at its "lease ended" line instead of running on until the next lease of the address or 24 hours.
- A lease that started before the time range and ended inside it now names its machine from the end line, so the first hours of a range are matched too.
- An end line logged after another machine took the address no longer cuts that machine's lease short.
- An hour is matched to the same machine whatever time range the page shows, and the address lookup (who had it at a time) reads the lines up to 24 hours after that time too, so it sees the end line of a lease that was still running.
- These are the same rules as the library query "Who had this address", and both read a DHCP line the same way, so the two name the same machine for an address at a time.
- What you will notice: an address is matched to the machine that held it at the time, also in the first hours of a range and after a lease ended.
- What changes for existing installs: nothing to do. Lines already stored are read with the new rule on the next page load; AI usage reads days it summarized before the update with start lines only, and days from the update on with both. To go back, install the previous version as in `docs/install/` (`update-systemd.sh --rollback`).

### Ask AI answers a bare address with its page (2026-11-17)

- Asking Ask AI only an address answers at once, without calling an AI model, with a link to the address page and its four sections in brief for the page's own 7 days, whatever time is chosen in Ask. It works on any turn of a conversation. Host and user names are asked as before.
- What you will notice: Ask AI answers a bare address at once with a link to its page instead of a query.
- What changes for existing installs: nothing to do.

### The address page answers who had it, what it looked up, how it signed in, and which AI services it reached (2026-11-17)

- Typing an address in the top bar search opens its page, even before the search has answered; it no longer drops into a raw SQL search in Logs.
- An address's page under People & devices has four new sections: DHCP and VPN history, the names it looked up in DNS with first and last seen, its sign-ins and firewall allows and denies by kind, and the AI services seen from it as AI usage counts them. Each reads only the sources you may read, says which sources it read, and says plainly when you have no source for it.
- On every person, host, and address page, a sign-out (such as sshd's "Disconnected from user") no longer counts as a sign-in, sign-ins in the activity lanes are one card per outcome, and firewall traffic in What it did reads Allowed or Denied. Outcome badges are the same everywhere; a success from an address is marked once, on its Succeeded number, in amber with a tooltip.
- With no events, an entity page shows one line and no empty numbers or lanes; "View all events in Logs" sits after the opening sentence and is not shown at 0.
- What you will notice: an address typed in the top bar opens its page, which has four new sections; sign-in counts on person, host, and address pages no longer include sign-outs, and empty pages are shorter.
- What changes for existing installs: nothing to do.

### Logs: searching for a word or an address is about twice as fast, and field counts no longer give up on long ranges (2026-11-17)

- A word, phrase, or address typed in Filters is found with a plain substring search instead of a case-insensitive pattern match. It finds exactly the same lines, in the same order. On a 30-day lake at the work install's rate (about 10.7 million events), a search for one address went from 5.4 s to 2.5 s for the first page and from 5.1 s to 2.3 s for the field counts; at 7 days from 1.7 s to 0.8 s. A word with a `*` in it is matched as before.
- When the field counts of a Filters search cannot finish for the whole range in 7 seconds, the Fields panel counts the newest days that hold matches instead (about 2 million events at a time, passing over days without matches) and names the numbers: "Counts from the newest 4 days only (159 of 1,133 items): the whole range took too long to count." Before, it showed only "Counting fields took too long for this range."
- Show SQL and Edit as SQL show the new form of the match, `contains(lower(raw), lower('text'))`, or `contains(raw, '192.0.2.15')` for text with no letter.
- What you will notice: Logs searches over long ranges come back sooner, and the Fields panel shows counts (sometimes from the newest days only, with a note) where it used to say counting took too long.
- What changes for existing installs: nothing to do.

### Ask AI: results first, and no more "Can't reach the server" behind a slow proxy (2026-11-17)

- The Ask AI page now asks in the background and checks on the question every second or so, so no request stays open while the model works and a reverse proxy's time limit no longer ends a question.
- Each question shows its steps as they happen, Writing query, Running query, and Summarizing, the current one with the seconds so far and the finished ones with how long they took.
- The table shows as soon as the query has run; the summary fills in afterward. When the model takes too long to summarize, the table stays and one line under it says "The model took too long to summarize. Results are above."
- Across the app, a request a proxy gave up on says "The request took too long" (or "The server is busy"), and "Can't reach the server" shows only when the request got no answer at all.
- Ask no longer has a Cancel button: the server finishes the question it started.
- What you will notice: Ask AI shows the results table first with its progress steps, and a slow model no longer ends in "Can't reach the server" behind a proxy.
- What changes for existing installs: nothing to do.

### Who had this address: says when there is no lease (2026-11-17)

- When "Who had this address" (`who_had_ip`) finds nothing, Logs and Ask AI say "No DHCP lease for this address in the range. It may be a static address." in place of "Try a wider time range or remove a source filter."
- In Logs this holds while the query opened from Library is unchanged or only its address is; after any other edit the usual text shows.
- A query library pack may give any query its own words for no rows, with the new optional field `empty:` (plain text, at most 160 characters). The Palo Alto pack is now version 1.2.0.
- What you will notice: an address lookup that finds no lease says so, and that the address may be static.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`), but first remove `empty:` from your own packs (the folder `paths.library` names): the older version refuses a pack that has it, and leaves that pack's queries out until it is removed. The packs shipped with the product need nothing.

### Who had this address: the interface, lease ended lines, one row per lease (2026-11-17)

- The library query "Who had this address" (`who_had_ip`) now fills its interface column whether the firewall writes the interface quoted (`interface "vlan20"`) or not (`interface ae0.120`).
- It finds leases and VPN tunnels with a start or end line in the time range: it reads "lease ended" lines as well as "lease started" lines, so a lease that started before the range shows from its end line. A lease with neither line in the range is not found.
- It gives one row per DHCP lease or VPN tunnel, newest first, with the first and last time it was seen in the range (`first_seen`, `last_seen`), in place of one row per log line. A row ends at the next holder's start, even when its end line is logged later.
- Its description now says it reads the time range only; it said it looked back 7 days before the range, which it never could.
- What you will notice: "Who had this address" shows the interface and each lease's first and last time seen, and finds leases with a start or end line in the range.
- What changes for existing installs: lines already stored show the interface and their end times too, since the query reads the stored description; no reparse is needed. A copy saved with Save as my own keeps the old query until you use Replace my copy.

### Logs: the query library is a tab (2026-11-17)

- Logs has a third tab, Library, beside Search and Saved searches, at its own address (`/investigate/library`), so a link or a refresh opens it.
- It lists every shipped, tested query by pack, each with its description, what is normal, and the sources it reads, with Run, Save as my own, and Add to dashboard. Run opens the query in the SQL editor over the last 24 hours; press Run there to see the results.
- A filter row finds a query by pack, name, or description.
- Queries for sources you have no events from are listed at the end under "Needs sources you don't have", with the names of those sources, instead of a count.
- Saved searches points to the Library; the Logs "..." menu and Ctrl+K "Logs › Library" open the tab.
- What you will notice: a Library tab on Logs lists the ready-made queries, including the ones waiting for a source you do not have yet.
- What changes for existing installs: nothing to do.

### One log file is read by one source only (2026-11-17)

- Two sources that reach the same log file (a folder source and a file source inside that folder, a link to the file, or a link to its folder) each stored every line of it, so the lines were counted twice. Now one source reads the file: the most specific one (a source set to that file before a folder source, a folder before a recursive pattern; between equals, the one added first). It stays the reader through log rotations and restarts, so new lines keep its parser, classification, retention, and access. The other source skips that file. When that is every file it lists, it says "Read by" and the source's name, with a hollow dot: it is not counted as a problem or in Sources healthy, it raises no quiet alert (one already open on it is resolved), and under its path Settings > Sources says what to do ("demo.log is already read by dns_bind, so nothing is stored here. Remove this source.", or without the advice when both sources are equally specific); Health shows the same line and lists such sources under their own Status segment, Shared. A source with only some files read elsewhere keeps its usual status and shows the line too. Whichever source reads a file starts where any source last stopped in it, so no line is stored twice: if the reading source is turned off or deleted, or no longer lists the file, the other carries on from there. Windows event log (.evtx) files are not covered yet: two sources over one .evtx folder each store every record.
- Different files that hold the same lines are still both read: for example a syslog daemon that writes each line of the DNS server to two files. Nothing is ever dropped for looking like another line.
- A source that takes over a file reads on from where the other stopped also when a restart or a remount changed the file's device number.
- The ingest guide (`docs/ingest/README.md`) says how to avoid both cases ("Rotating log files") and gives a Logs SQL check that shows where doubled lines came from ("Lines stored twice").
- What you will notice: if two of your sources read the same file, one of them stops storing its lines and says "Read by" the other, without counting as a problem; counts from that file are no longer doubled.
- What changes for existing installs: lines already stored twice stay in the lake until retention removes them; the Logs SQL check in the ingest guide shows which sources the copies came from. Only new lines are stored once. When a source is deleted, a source that lists the same files carries on from where it stopped; a source added later reads the files no other source lists from their start, as before. To go back, install the previous version as `docs/install/` describes (`update-systemd.sh --rollback`); the two sources then both read the file again, and the one that skipped it stores the lines it skipped meanwhile, so they are counted twice again.

### Ask AI: a slow model no longer ends in an error (2026-11-17)

- Ask AI now runs in the background on the server: asking returns at once, and the server keeps the question's progress, the query, the rows, and the summary for the page to pick up (the page moves to this in the next update; until then it works as before).
- Each model call Ask makes has a time limit, 90 seconds by default. When the model takes longer to write the query, Ask says "The model took too long to write a query."; when it takes longer to summarize, the rows and the query stay and Ask says "The model took too long to summarize. Results are above." The request to the model is stopped, not left running.
- The summary is written from at most 10 rows plus how many values and how many different ones each column has, and the range of numbers and times, over the whole result, worked out by the server; no names or other text from the rows not shown are sent.
- What you will notice: nothing visible yet; the Ask page moves to the background job, and with it the end of "Can't reach the server" on a slow model, in the next update.
- What changes for existing installs: a new setting, `ask.model_timeout_s` (default 90; `APP__ASK__MODEL_TIMEOUT_S`), the longest one Ask model call may take; a reverse proxy's timeout no longer matters for Ask once the page uses the background job. Nothing to do. To go back, remove the setting (or the environment line) and roll back as in `docs/install/` (`update-systemd.sh --rollback`); jobs are held in memory only and are lost on any restart.

### Dashboard: loads in its final layout, with nothing moving (2026-11-17)

- The Dashboard draws every part in its final place at once: the key numbers have all their tiles from the start, each a placeholder until its number arrives, and AI Watch, Identity, Attacks and access, and Detections each show their title and cards while their numbers load, in a box of the same size they have when loaded.
- Nothing jumps when a number arrives: the Needs you list, the key numbers, and every section header stay where they first appeared.
- Each section keeps the height it had the last time you opened the Dashboard in this browser, so returning visits load with no empty space; a first visit sizes each section by the time window.
- What is already known to be empty is drawn at its own size from the start: Detections when no rule is enabled and no match is kept from before (administrators only, with Enable rules; others do not see the section, as before), and Attacks and access when the sources it counts sent nothing in the window. Matches kept from rules turned off still show.
- If your list of sources cannot be read, every section still loads on its own, with Retry for the list.
- A tile with nothing to count keeps its place: AI services in use reads 0 ("None in this window"), and a tile without data says "Not available". A section with nothing to show says so, centered in its box: "No sign-in failures from external addresses in this window.", "No AI use in sources you can read."
- Loading placeholders are easier to see in the dark theme.
- The smoke test now loads the Dashboard with its answers held back and fails when anything on it moves.
- What you will notice: the Dashboard no longer jumps while it loads; every section shows its title and grey placeholders until its numbers arrive.
- What changes for existing installs: nothing to do.

### The left menu shows the open page's tabs and what each entry is for (2026-11-16)

- The page you are on lists its own tabs under it in the left menu, indented, with the open tab marked: AI usage (Services, People, Inventory), Agents, Health, Alerts, and Logs. Other pages stay folded, and Settings keeps its own list on its pages.
- Pointing at a menu entry, or moving to it with the keyboard, shows one line on what it is for, such as "Search every event" for Logs. With the narrow icon-only menu it shows the name and that line.
- With nothing pinned yet, Pinned shows "Pin a dashboard or saved search here" instead of being hidden.
- On short windows the recent and pinned lists still give way first, so the menu never scrolls.
- What you will notice: the left menu lists the open page's tabs, explains each entry on hover, and says where pins go.
- What changes for existing installs: nothing to do.

### Times in the app's format on Schedules, bars on Handling, and a paged Microsoft 365 table on a person's page (2026-11-16)

- Alerts > Schedules shows each schedule's last and next run as "Nov 16, 10:00 AM" in your time zone, with the UTC time on hover, instead of "2026-11-16 10:00". The same goes for its alert deliveries, Alert targets' last send, Users' last sign-in, your tokens, parser drafts, the Activity and AI calls tables, the events around an event, the AI Watch failing line, the Agents card, the Logs "Last run" line, and the offline banner.
- Alerts > Handling draws alerts opened and closed per day as bars side by side, so a day's count is never drawn as a curve between days. The legend, the zero baseline, and the exact numbers on hover stay.
- A person's Microsoft 365 table no longer scrolls inside the page: it shows 50 rows a page with Previous and Next above and below, as Logs does. Its headers read App, Outcome, Operation, and Target instead of column names.
- What you will notice: times on Schedules read like the rest of the app, the Handling chart shows bars, and a person's Microsoft 365 rows come in pages.
- What changes for existing installs: nothing to do.

### Agents: its own numbers in the header, a faster Sessions list, and a legend that adds up (2026-11-16)

- The Agents header now counts what the page is about: sessions, people, and tool calls for the time chosen, the same numbers as the tiles below it, instead of AI usage's count of services.
- The comparison line shows once, above the tiles; AI usage's line about new and no longer seen services is no longer repeated on Agents.
- Agents loads faster: the Sessions and Accounts tabs no longer wait on the whole AI usage answer (only the MCP servers tab reads it), and the Sessions list and session pages read only the Claude plugin's records instead of every source of the time chosen.
- On Agents, Needs attention counts not approved and unreviewed MCP servers from the same answer as the tiles, the same on every tab. The chips about services not approved and sensitive-data signals stay on AI usage, where they belong.
- In a session's timeline, the legend puts the three kinds of tool call (in the session, file access, access) under one "Tool calls" total, the same number as the Tool calls tile. Claude Code's own bookkeeping counts as Other, as it already did in the tiles.
- "Not reported" under Tokens stays on one line, and the timeline's "Access" is now called "Web or MCP access".
- The Sessions card has one line that adds its list up to the Sessions tile: listed, empty and hidden, and sessions seen only in Claude Code telemetry. With nothing in the time chosen it says so for that time, and offers the plugin download only when there are no sessions at all.
- Everything on Agents now covers exactly the time you pick: 1 hour is an hour, not a day, and a custom range is that range. The header, the tiles, Needs attention, the Sessions list, Accounts, and the MCP servers table all agree; Needs attention counts the MCP servers the table lists. Placeholder names such as "custom" are no longer counted as an unreviewed MCP server.
- For a range longer than 90 days, Agents shows its last 90 days and says so under the time control.
- When there are more than 100 sessions, the Sessions card says it shows the newest 100 of how many.
- MCP servers with the same number of calls keep the same order on every load.
- What you will notice: the Agents header shows sessions, people, and tool calls, the Sessions list loads faster and says how it adds up to the tile, every number on Agents covers the time you pick, and the timeline's Tool calls match the tile.
- What changes for existing installs: nothing to do.

### AI usage People rows, the Admin view's lists, and one order on every load (2026-11-16)

- AI usage > People: a person seen only on the network keeps each value in its own column. What the network saw is under Network, "Unmatched" and Link in Identities are under the name, cost and tokens say "Not reported", and sessions, tool calls, and errors are empty, with the reason said once above the table; no sentence runs across the columns. "No cost data" is now "None received": Claude Code telemetry reports cost and tokens, and none arrived.
- Logs > Views > Microsoft 365 admin, Sign-ins, and Mail: each list counts its rows in its own words ("1 app consent", "3 sign-ins") and its columns have plain headers ("Person", "App ID") instead of column names.
- AI usage lists keep one order on every load: services and people with equal counts are listed by name, and Inventory items seen at the same time are listed by type, then by name.
- "N new, N no longer seen" beside the time control counts AI services only on AI usage (MCP servers were counted too), so it matches the New badges and the No longer seen card.
- What you will notice: AI usage People rows stay inside their columns, the Admin view says "1 app consent" with plain headers, and AI usage lists no longer change order between loads.
- What changes for existing installs: nothing to do.

### Settings > Sources: one status with Health, parser updates folded away (2026-11-16)

- Settings > Sources shows each source's status in the same words and dot as Health ("Flowing", "Idle", "Quiet 5 d", "Never sent", "Paused", "Unhealthy"), from the one rule the server uses for both. A file that is still being read but has sent nothing for days now reads as quiet on both pages, not as green "Reading".
- What the reader is doing is its own small line under the status, for example "Reader: following the files".
- Parser updates are one line with a closed "What changed" that lists each update in plain words and the searches to check; column names and decision numbers are no longer on the page.
- The "Local only" badge and the "latest ... ago" line no longer break over two lines.
- The Dashboard's Needs you names a source by the same status ("Quiet 33 h", "Unhealthy") with what is wrong ("dns_bind: nothing received for 33 h"), and lists no source that is quiet as normal or paused.
- What you will notice: Settings > Sources and the Dashboard say the same status as Health for every source, and parser updates take one line until you open What changed.
- What changes for existing installs: nothing to do.

### People & devices at full width, with neutral score bars (2026-11-16)

- People & devices uses the full content width, like Alerts and AI usage, instead of a narrow centered card. Names get a bounded share and the counts share the rest evenly, with one-line headers, the same on every tab; every number, rule matches included, is right-aligned.
- The score bars are drawn in a neutral grey instead of red: a score is a size, not a severity. Severity colors stay on the rule match badges.
- The line beside the title, "0 rule matches considered", is gone: it counted stored rule matches of any date, not the page's range. Each tab still shows its own count.
- What you will notice: People & devices fills the page, its score bars are grey, and the title has no count beside it.
- What changes for existing installs: nothing to do.

### Old addresses open the right page, and unknown ones say "Page not found" (2026-11-16)

- Old addresses and bookmarks open the page that holds their content now: `/investigate` opens People & devices, `/investigate/ask` opens Ask AI, and `/settings` opens Sources in Settings, instead of Health. Anything after the address (a person, a filter) is kept, and Back does not return to the old address.
- An address that matches no page shows "Page not found" with the address you typed and a link to the Dashboard, and leaves the address as it is so you can correct it.
- Links in alert messages point at today's pages: the log integrity alerts open the Integrity tab of the audit log, and events sent to you open Logs.
- What you will notice: old links land on the right page, and a mistyped address says "Page not found" instead of opening Health.
- What changes for existing installs: nothing to do.

### Comparison dates, "No earlier data", and the Needs you subject column (2026-11-16)

- "Comparisons start" now gives the day the window before is first covered, from one rule on the server for the Dashboard sections, AI Watch, Agents, and Microsoft 365. Before, the page added two whole windows to the newest source's start, so the date came about 4 days late (on a 30-day window, about 57 days of data are needed, so the date can still be weeks ahead).
- Agents no longer counts the server's own events as an AI telemetry source, so the day the server first ran no longer holds back its comparisons.
- While a section's sources have no data for the window before, no number shows a change: the server sends no earlier value. The Dashboard's Failed sign-ins and Sign-ins outside approved countries tiles say "No earlier data" in its place, instead of a rise from zero. A window before that has data and counted 0 still shows the change.
- Needs you on the Dashboard gives the subject column a fixed share of the row: source ids, host names, and addresses stay on one line and are cut in the middle when long, with the full value on hover and on copy. Titles wrap between words only, never inside a device id or address.
- Top services on the Dashboard shows 0 people as 0, as the Inventory does; "·" stays only for a value that is not known.
- What you will notice: the Dashboard's comparison dates are right, a tile with nothing earlier says "No earlier data", and long names in Needs you no longer break across lines.
- What changes for existing installs: nothing to do.

### One badge style in the left menu, and Health's counts agree (2026-11-16)

- The counts beside Alerts and AI usage now look the same: both are the solid orange badge, because both ask you to act.
- Health shows a small status dot instead of a number, only when something is wrong: red only when Health shows a source in red (an error, or a source that stopped with gaps on its chart), amber otherwise. It also shows when damaged data files were moved aside. Hovering it, or a screen reader, says how many ("Health: 2 sources need attention").
- On Health, the Sources tab's count, the Problems count, the rows listed, and the dot in the left menu now come from one rule on the server. When the tab's count includes enrichment feeds as well as sources, its tooltip says so, and a link beside the filters ("Show 1 problem in Enrichment feeds") opens them.
- The note under Health's source chart says "Times in UTC." when your time zone is UTC, instead of offering a hover that shows the same time.
- What you will notice: Alerts and AI usage counts look alike, Health has a colored dot instead of a number, and Health's counts add up.
- What changes for existing installs: nothing to do.

### Ask AI lists every AI service and says what it counted (2026-11-16)

- "Which AI services are people using?" now counts AI services the way AI usage does, from every source that can show one (DNS, proxy, firewall, Microsoft 365, and the rest), so its list matches AI usage > Services for the same time range. Each service shows the sources it was seen in. A saved copy of this query (Save as my own, or a pack added to a dashboard) keeps the service list as it was when saved.
- An answer made of counts, with no events to cite, now has one plain "What was counted" line in place of "No summary": the sources read, the time range, and what was counted. An answer with nothing found is one line that says what was read.
- "Sources read" under How I got this lists only the sources the question actually read, not every source you can see.
- The question box is wider (up to 1200 px), and Ask is the page's one blue button once there is text.
- What you will notice: Ask AI's AI services answer matches AI usage, says what it counted, and names only the sources it read.
- What changes for existing installs: nothing to do.

### One "to review" number on AI usage (2026-11-16)

- The header, the AI usage count in the left menu, the Inventory's Unreviewed rows, and the Needs attention line now all show the same number of items to review, counted once on the server. Before, Needs attention counted AI services only, over the page's time range, so it could say 1 while the rest said 2.
- Needs attention reads the same on Services, People, and Inventory: open alerts, items to review, items marked Not approved (each opening the Inventory on that list), and sensitive-data signals in the time chosen on Services and People. Following one of these links keeps that time choice.
- The Inventory tab no longer shows the "not approved in use" and "sensitive-data signals" tags beside the time control: they count the time chosen on the other tabs, and that tab has no time control.
- The Dashboard's AI services tile now says "N of them unreviewed": AI services in its time range only.
- The Inventory tab has no time control any more: it always shows the last 30 days, as its card says. The other tabs keep the time you chose.
- The Inventory's filters are one row; Export CSV and Export JSON are in the page header and are off when there is nothing to export. Type lists only the kinds of item in the view, and Group by only groupings that make more than one group. The card under the tab is titled "Everything AI seen" instead of repeating "Inventory".
- What you will notice: AI usage states one "to review" number everywhere, and the Inventory tab shows only the controls that do something there.
- What changes for existing installs: nothing to do.

### Every dropdown is drawn in the app's theme (2026-11-16)

- Every dropdown (filters such as the AI inventory's Status, and the choices in forms) is now the app's own list instead of the browser's, so its options follow the dark and light themes.
- The current choice has a check mark; only an option that really cannot be chosen is greyed out. The keyboard works as before: arrows, Home, End, typing the first letters, Enter, and Escape.
- What you will notice: every dropdown is readable in the dark theme and looks the same on every page.
- What changes for existing installs: nothing to do.

### README screenshots of the current console, in both themes (2026-11-15)

- The README screenshots are retaken from the synthetic demo after the console redesign: Dashboard, Logs, Ask AI, the Microsoft 365 admin view of Logs, AI usage, Agents > Sessions with a session open, Health, and the command palette, each in the dark and the light theme. The social preview image is rebuilt from the new Dashboard.
- `scripts/screenshots/capture.py` follows today's pages and controls, takes every shot in both themes, waits for each page to finish drawing, and stops with the shot's name when something is missing or a page shows an error.
- What you will notice: the README pictures show the current console, in the dark and the light theme.
- What changes for existing installs: nothing to do.

### Clearer quiet alerts, and AI Watch's "no data after" follows the events' dates (2026-11-15)

- When a source's newest event is much older than its last delivery (an offline queue, an import), its quiet alert now reads "No new events for 7 d. Newest event dated ... UTC; last data arrived ... UTC." In the ordinary case it still reads "No events received for 7 d".
- AI Watch's chart on the Dashboard says "no data after" the newest event's own date, so old events that arrived just now no longer make it look complete up to today.
- What you will notice: clearer quiet alert text in that case, and AI Watch's chart marks the days with no data yet correctly.
- What changes for existing installs: nothing to do.

### How long a source has been quiet counts from its newest event (2026-11-14)

- "Quiet", "Idle", and "No events for" on Health, Sources, and the Sources healthy line now count from the newest event's own time, the same time the status is judged from.
- Before, they counted from when a record last arrived, so old events delivered now (a Claude plugin's offline queue, a history import) read "Quiet 7 s" for a source with nothing newer than two days. "Last received" still shows when a record last arrived.
- What you will notice: a source that just received old events reads "Quiet 2 d" (or "Idle, No events for 2 d"), not a few seconds.
- What changes for existing installs: nothing to do.

### A time without a zone means UTC everywhere (2026-11-14)

- An API or CLI request whose start, end, or other time has no zone (`2026-11-14T08:00:00`) is now read as UTC in every step: which days of data are read, the row filter, the rollups AI usage and Microsoft 365 read, and the Proxmox guest lookup. Before, on a server whose own zone was not UTC, such a window near midnight could leave out the events of a day or read a day it did not need.
- The audit log filters, a rule run, and a saved search's time parameters now read such a time as UTC too, where they used to refuse it.
- What you will notice: nothing in the web pages, which always send times with a zone; API scripts that send times without one now get the days they asked for.
- What changes for existing installs: nothing to do.

### Logs reads the newest day first (2026-11-14)

- A Logs search over a long window reads the newest day's files first and goes back only as far as it must to fill the page, so a 30-day search with matches on the newest day costs about what a one-day search costs.
- The rows, their order, and the count are the same as before; when two events have the same time, the one with the higher event id comes first, every time.
- A search with no match in the newest day reads that day first and then the rest, so it can take slightly longer: on a 30-day lake at the size of a production install, a search with no match at all took 2.4 s instead of 2.1 s.
- SQL typed in the SQL tab, saved searches written as SQL, and SQL another page hands over run as written. The Fields panel and the field check still count over the whole window.
- What you will notice: long Logs searches show their results sooner.
- What changes for existing installs: nothing to do.

### Calmer colors for the session timeline (2026-11-14)

- The timeline bar on Agents > Sessions now uses two quiet colors and gray: prompts in ice (a light cyan), tool calls in graphite, tool results in gray.
- File access and access (web and MCP) are drawn with stripes, in graphite and ice: these are the steps that reach outside the session (a file, the web, or an MCP server). The stripes read without any color.
- A small tick under the bar marks every place where a step reached outside the session, also in a very long session where several steps share one part of the bar; the legend explains it.
- No color on the bar is one used elsewhere for health, warnings, severities, links, or the Cloud badge.
- What you will notice: the session timeline bar is ice, graphite, and gray, with stripes on file and web steps and a tick under the bar wherever a step reached outside the session.
- What changes for existing installs: nothing to do.

### The merge queue checks each pull request for real-looking names (2026-11-14)

- The merge queue now runs the allowlist scan (the synthetic-only rule) on the files a pull request adds or changes, renamed files under their new names, leaving out what is never published. A pull request that changes the scan's own rules (the export rules, the allowlist, the reviewed binaries, or the scanner) gets the whole tree scanned instead. A real-looking domain, address, or file name stops the queue at merge instead of at publish, and so does a scan that could not run. The publish step still scans the whole tree.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do.

### A test address in a reserved form (2026-11-14)

- A test used an address whose first part read as a real domain to the publish allowlist scan; it is written with a hyphen now. The scan finds nothing on the tree.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do.

### Alerts opens faster with many AI Watch alerts (2026-11-14)

- When many open AI Watch alerts name devices, the Alerts list looks up who used each device once per device instead of once per device and record. On synthetic data with 200 open alerts of 20 devices each and a month of hook records, the list went from about 1 second to 0.2 seconds. Who is named on each device, and what each viewer may see, is the same.
- Two page sections that both had to use disk space at the same time could spoil each other's temporary files, so one of them failed with a "Corrupt temporary file" error that read as a bad request. Each now keeps its own temporary files, and a page that runs out of memory always says so.
- What you will notice: Alerts opens faster when many AI Watch alerts are open.
- What changes for existing installs: nothing to do.

### Logs counts its fields in one pass (2026-11-14)

- The Fields panel beside Logs results (top values of source, host, user, addresses, severity, status, class, and parse status) now counts every field in one pass over only the columns it needs. Before, it ran the search once per field over every column and sorted the rows first. A text search over 7 days at the work install's rate took 12 seconds and timed out at 10; it now takes about 1.3 seconds, and 5 seconds over 30 days. The counts are the same.
- If counting ever takes too long, the panel says so in plain words with a Retry button; the results stay on the page.
- What you will notice: the Fields panel fills in quickly on long time ranges instead of showing a timeout.
- What changes for existing installs: nothing to do.

### A timeline bar for each agent session (2026-11-14)

- An open session on Agents > Sessions now shows a bar of its steps from start to end, one segment per step in order, colored by kind: prompt, tool call, tool result, file access, and access (web and MCP). A failed step has a small red mark above it.
- The legend under the bar names each kind with its count for the whole session. Choosing a segment takes you to that step in the list below. With Flagged only, steps that are not flagged are dimmed on the bar.
- For a very long session the bar draws the first 2,000 steps and says so; the counts still cover the whole session.
- Charts gain five calm series colors, checked for contrast in both themes; they are never used for severity or warnings.
- What you will notice: an open session on Agents > Sessions has a colored bar of its steps under its numbers, with a legend you can read without the colors.
- What changes for existing installs: nothing to do.

### Quiet is normal now also holds the quiet alert (2026-11-14)

- On a source marked "Quiet is normal for up to" some days, its quiet alert waits for those days: no alert and no message while the silence is inside them.
- Once the days pass, the alert fires once, as it would have, with when the silence started. Taking the mark off checks the alert again at the next check, within 30 seconds.
- An alert that is already firing stays until events resume or someone closes it. Errors and refused records are raised as before.
- What you will notice: a marked source that is quiet for a few hours no longer sends a "stopped sending" alert; the setting says its quiet alert is held for these days.
- What changes for existing installs: sources already marked Quiet is normal now also have their quiet alert held for their days; nothing changes for unmarked sources. Going back to the previous version sends quiet alerts as before (`docs/install/`, `update-systemd.sh --rollback`).

### The speed check's lake is kept as an install keeps its data (2026-11-14)

- The speed check's default lake, the one the merge queue times every change on, is now kept compacted with its daily rollups built, as the 30-day lake already was. Before, each timed server built those rollups while it was being timed, so pages read those days from raw events meanwhile.
- A kept lake is built again once for this, and from now on once each UTC day (a lake built before midnight has a new day with no rollup after it). A build takes about three minutes longer (97 s to 279 s).
- On the kept lake the rows read what an install's pages cost: in the first tables the Dashboard row went from 0.80 to 0.66 s, AI usage from 0.43 to 0.35 s, People & devices from 0.64 to 0.52 s, and the Person page stayed at about 4.2 s, on both sides alike.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do.

### Alerts keep an AI Watch alert's time range and devices current (2026-11-14)

- An AI Watch alert for a service or MCP server is kept current by the hourly review, and its time range now is too: it covers the last 7 days the alert counts, not the time since it was first raised. Who used a device is looked up over that range, so a person seen on the device in those 7 days is named (to viewers who may see people), and Show events in Logs opens that range.
- Other alerts kept current keep the start of their range as before: Refused credentials covers the whole burst from its first refusal, and Sensitive data its day.
- An alert lists at most 20 devices. It now keeps host names first, the most recently seen first, then their addresses, so a busy alert no longer loses every host name to addresses. The alert's text names its first five devices in that order too (it was alphabetical). When the list is cut, the alert says so ("20 of 85 devices and addresses").
- What you will notice: AI Watch alerts on busy services show their devices by name, can say who used them, and say when the list is cut.
- What changes for existing installs: nothing to do. Open AI Watch alerts take the new range and device order at their next hourly review, within an hour of the update; closed alerts stay as they were. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); the new column is left unused.

### A clearer page for one agent session (2026-11-14)

- Agents > Sessions keeps the list on the left and opens the chosen session beside it. On a small window the session takes the page, with Back to sessions.
- The open session starts with its numbers for the whole session: requests, tool calls with how many failed or were blocked, tokens in and out (or "Not reported" when Claude Code telemetry sent none), files with how many were written outside the session's folder, and flags.
- Its steps show as Execution (every step in order, with its type: prompt, tool call, tool result, file access, or access) or Conversation (by turn, as before, with a line for what each prompt led to), all steps or only the flagged ones. The page says when a very long session shows only its first steps, and Show events in Logs opens the session's records.
- One line says that content is not collected: the page shows sizes and names only, as before.
- What you will notice: opening a session on Agents > Sessions shows it beside the list with its numbers at the top, and you can switch between every step in order and the session by turn.
- What changes for existing installs: nothing to do.

### One agent session in numbers, from the server (2026-11-14)

- New `GET /api/ai/sessions/{session_id}/summary`: for one Claude Code or Cowork session, its prompts, tool calls with how many failed or got no result, tokens in and out when Claude Code telemetry reported them for the session (otherwise empty, never 0), files touched and how many were written outside the session's folder, what the session's flags are read from, the length, and a count per step type. It counts the whole session, also past the 2,000 steps the steps list shows, and says when that list is cut.
- Each step of `GET /api/ai/sessions/{session_id}` now says its type: prompt, tool call, tool result, file access, access (web and MCP), or other. The server works it out from the hook record when it is read; nothing new is stored.
- Metadata only, as before. Without View people in AI usage the machine stands in for the person and the account, and each answer writes an audit row as opening a session does.
- What you will notice: nothing visible yet; the session page that uses it follows.
- What changes for existing installs: nothing to do.

### Alerts > Handling: how alerts are being handled (2026-11-14)

- A new Handling tab on Alerts, beside the Queue, shows whether alerts are being handled (D261): the median and 90th percentile time to close (closes by a person), alerts overdue now, every alert open now (the Queue counts at most its newest 200), alerts opened against closed per day, open alerts by kind, and by severity with each severity's overdue days and times to close.
- It follows the page's time control (30 days unless chosen); open and overdue counts are always as of now. Each open count opens the Queue with that Severity or Category filter, and the time to close opens the alerts closed in the same window.
- It counts only the alerts the Queue shows you; alerts in sources you cannot read are never counted, and the page says some exist.
- What you will notice: a Handling tab on Alerts with time to close, overdue and open alerts, and opened against closed by day.
- What changes for existing installs: nothing to do. An open alert is overdue after 1 day (Critical), 3 days (High), 7 days (Medium), or 30 days (Low, and alerts with no severity); change these in `config/app.yaml` under `alerts:` (`overdue_days_high` and the others) or with `APP__ALERTS__OVERDUE_DAYS_HIGH` and the like, then restart. To go back, first remove the `alerts:` section and any `APP__ALERTS__` variables (an older version refuses to start with settings it does not know), then roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Alert handling numbers from the server (2026-11-14)

- New `GET /api/alerts/metrics`: time to close (median and 90th percentile, overall and by severity), alerts opened and closed per day over a range, alerts open now by severity and by kind, and alerts overdue now by severity, with the overdue days in the answer (D261). It counts only the alerts the Alerts queue shows the caller; open now is every open alert, where the Queue counts at most the newest 200.
- An open alert is overdue once it has been open longer than 1 day (Critical), 3 days (High), 7 days (Medium), or 30 days (Low, and alerts with no severity).
- What you will notice: nothing visible; the Alerts page shows these numbers in a later update.
- What changes for existing installs: nothing to do. The overdue days can be changed in `config/app.yaml` under `alerts:` (`overdue_days_critical`, `overdue_days_high`, `overdue_days_medium`, `overdue_days_low`) or with `APP__ALERTS__OVERDUE_DAYS_HIGH` and the like, then a restart. To go back, first remove the `alerts:` section from `config/app.yaml` and any `APP__ALERTS__` variables (an older version refuses to start with settings it does not know, from the file or the environment), then roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Quiet is normal for sources that send only while people work (2026-11-14)

- An OpenTelemetry or syslog listener source can be set to "Quiet is normal for up to" 1, 3, 7, 14, or 30 days, under its status on Settings > Sources (administrators).
- Inside those days a silent source counts as healthy. Health and Sources say "Idle" with how long it has been, and the Dashboard does not list it under Needs you.
- Errors, a listener that is down, refused records, and quiet or gap alerts still count. A source silent for longer than its days, or one that never sent, reads as quiet as before.
- A quiet alert still fires inside those days. Collector OpenTelemetry sources and syslog listener sources get a 1-hour quiet alert when they are added, so marking one of them changes nothing after an hour of silence until you turn that alert off or lengthen it; the setting says so when the source has a quiet alert on.
- New Claude Code sources start at 7 days.
- What you will notice: Claude Code sources nobody used for a day read "Idle" and no longer lower Sources healthy, once marked.
- What changes for existing installs: nothing until an administrator marks a source; you may want to set your existing Claude Code sources to 7 days on Settings > Sources. Going back to the previous version leaves the new setting unused (`docs/install/`, `update-systemd.sh --rollback`).

### AI usage opens faster on large installs (2026-11-14)

- AI usage reads the period before the chosen range at the same time as the range itself, instead of after it.
- The first day of a range is read from the daily AI summary for its whole hours after the start, and only the rest of the start's own hour from the raw events, when that day's summary is complete with who had which address. A day whose summary is not ready yet is still read from the events. The AI inventory, which asks the same question, reads it the same way. Every number on both stays the same.
- A start sent with a time zone offset of half or three quarters of an hour (for example +05:30) is now cut at the UTC hour the summaries are kept by; before, a start on such a zone's hour could leave out up to an hour of use after it.
- What you will notice: AI usage and the AI inventory open faster on large installs.
- What changes for existing installs: nothing to do.

### Pinned saved searches and dashboards in the left menu (2026-11-14)

- Pin a saved search from its row or when it is open, and a dashboard beside the dashboard picker. The left menu lists your pins under Pinned, above Recent; each opens its search or dashboard.
- Pins are yours only and kept on the server, so they follow you to any browser. A pin disappears when its search or dashboard is deleted or no longer shared with you.
- Up to five pins; unpin one to pin another. On short windows the menu shows fewer Recent and then fewer Pinned rows.
- What you will notice: a Pin button on saved searches and dashboards, and a Pinned list in the left menu.
- What changes for existing installs: nothing to do. Going back to the previous version leaves the pins table unused (`docs/install/`, `update-systemd.sh --rollback`).

### The Dashboard's Detections and Agents read less on large installs (2026-11-14)

- Detections on the Dashboard looks up the person and host of each matched event in the sources those matches came from, from the first match on, instead of in every source over the window and the window before. On 30 days of synthetic data at the work install's rate that lookup took 1.7 seconds and now takes a few milliseconds, with the same events.
- Agents (on the Dashboard's AI Watch and on Agents) reads only the sources whose files can hold Claude Code telemetry, hook records, MCP inventories, or usage reports, decided by each file's own statistics, so a new or custom source that receives such records is still read. The answers are the same.
- What you will notice: the Dashboard and Agents open faster on large installs.
- What changes for existing installs: nothing to do.

### Recent and counts in the left menu (2026-11-14)

- The left menu lists the last five people, hosts, and addresses you opened under Recent, newest first; each opens its page. It is hidden until you open one, and on short windows it shows fewer rows.
- Recent is kept in your browser for your account only, not on the server, and cleared when you sign out. Without View people in AI usage it lists and keeps no people.
- AI usage shows how many items are still to review, and then opens the Inventory.
- Health shows how many sources need attention in place of the dot; nothing when all is well.
- What you will notice: the left menu shows what you opened recently and how many AI items and sources need a look.
- What changes for existing installs: nothing to do.

### An exact copy of the raw event (2026-11-14)

- The raw event in an expanded Logs row has a Copy button that copies the line exactly as stored, with its line breaks, tabs, and spaces.
- Copy as JSON, and every other Copy button (tokens, links, signing keys, setup blocks), copies its value exactly; tests now hold them to it.
- A long name with a line break or tab is still drawn on one line in tables and lists; the raw event and Copy as JSON are where to copy it exactly.
- What you will notice: a Copy button beside the raw event in an expanded Logs row.
- What changes for existing installs: nothing to do.

### The speed check can time a lake the size of production (2026-11-13)

- `scripts/bench_compare.py --real-days N` sets how many days the real-shaped part of the lake holds (7 by default), so a lake of 30 days at the work install's rate is one command: `--lake ../data/bench/lake-prod30 --real-shape 0.313 --real-days 30`. The days are kept with the lake, and a kept lake of other days is built again. The real-shaped sign-ins, DNS queries, and hook records are now configured sources of that lake, as they are on an install, so the Dashboard's sections and the Alerts lookup read them, and the lake is kept with its closed days compacted and rolled up, as on an install: before, each timed server built the rollups while it was being timed, which made the Dashboard on 30 days look about 4 seconds slower than it is (6.7 s against 2.3 s).
- The bench lake now holds open AI Watch alerts for AI services that name machines, with Claude hooks records saying who used most of them, so the Alerts row times the people lookup the install runs. Kept lakes are built again once for it. A build whose AI Watch check did not raise those alerts, or (for a large lake) whose rollups did not finish within an hour, now fails instead of keeping the lake, and a large lake built on an earlier UTC day is built again.
- CLAUDE.md section 9 says when to run the large lake by hand: before a release, and when a change touches the Dashboard sections, AI usage, or People & devices.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do.

### Long names and emails cut where they hurt least (2026-11-14)

- An email address keeps the part before the "@" for as long as it can: the domain is greyed and is cut first.
- Long names such as source ids, hosts, apps, and networks are cut in the middle and keep their last 8 characters, so `m365_management_activity` reads as its start, "…", and "activity". Hover shows the whole value (and keyboard focus does, on values that are not links), and copying gives each value whole, on one line, however much you select.
- On the Dashboard, Needs you reads severity, kind, who or what, what happened, then when, with no wide gap before the name. Alert titles there and in the Alerts queue use up to two lines before they are cut.
- The Network column of Top sources and the App column of "Apps signed in to" get the free space of their card; the Person column on AI usage > People is wide enough that an email never breaks inside a word.
- While AI usage and Agents load, the grey placeholder rows have the shape of the table, and the "Needs attention" line keeps its place, so the page no longer jumps when the data arrives. If AI usage cannot be loaded, the error shows without a placeholder above it.
- Not done yet: hiding your organization's own domain in emails.
- What you will notice: long names and emails are cut in the middle or at the domain with the full value on hover, and AI usage no longer jumps while it loads.
- What changes for existing installs: nothing to do.

### Ask AI starts with the question (2026-11-14)

- Ask AI opens with one large question box at the top, "Ask about your logs", with the Ask button inside it.
- Time, Sources, and Model are three small buttons in one row under the box; Model shows the provider's name and whether it is Local or Cloud.
- Answers appear right under the question box, newest first; each answer's heading shows when it was asked and its Local or Cloud badge. A follow-up still refines the answer directly under the box.
- New question is in the page header. Example questions show only before the first question.
- A KQL or SPL query can still be pasted in; the box's tooltip says so.
- What you will notice: Ask AI looks like a search page, with the newest answer at the top.
- What changes for existing installs: nothing to do.

### Health: one filter row and calmer rows (2026-11-14)

- Health has one filter row: Status (All, Problems, Paused, Healthy, with counts) and Type, with the number of rows at the right. Problems holds what was Unhealthy and Needs attention.
- A tab shows a number only when something on it needs attention, outlined in orange; there are no totals beside the tabs.
- The four numbers at the top look like the Dashboard's, in one strip; Alert delivery reads "0 failed" with "All delivered" under it. The sentence "No detections in 24 hours..." is gone; the detections and paused schedules card shows only when it has something to list.
- The Sources list has Status and Peak columns, and Last received shows the time in your local format (UTC on hover). A source that is only quiet is drawn in grey; a gap keeps its red shading and sentence.
- While Health loads, the numbers show grey bars instead of zeros or "All delivered".
- Old Health addresses (the former tabs) still open the same view.
- If part of Health cannot be read, its numbers say "Could not load" with Retry instead of showing zeros.
- What you will notice: Health has one filter row, tab numbers only for problems, and no all-clear before it has checked.
- What changes for existing installs: nothing to do.

### Cards share one title row (2026-11-14)

- Every card on the Dashboard, AI usage, Agents, and a person's page has the same title row: the title, an optional (i), a short muted note, and one link at the top right. No card title row has a fill of its own any more.
- Needs you: the "N more on Alerts" link at the bottom is now **View all** at the top right; the count stays beside the title.
- Identity, Attacks and access, and Detections each get **View all** (the Microsoft 365 Sign-ins view, Logs, and Alerts > Rules); "Changes against the previous 7 days" moves beside the title.
- AI Watch's "AI use" chart and "Top services" are panels of one height side by side.
- On AI usage and Agents, "Names are hidden" is a notice above the list instead of part of the title row; the Inventory's Group by and Export buttons and the Sessions "Hide sessions with no tool calls or prompts" box sit in their filter rows; how a list is counted (for example, that cost is Claude Code's own estimate) is behind the (i) beside its title.
- Attacks and access **View all** opens its external sign-in failures in Logs for the page window. A person's Timeline, What it did, and the Hosts and Users lists on an address or host use the same title row.
- What you will notice: card headers line up across the pages, and each card's link to its full list is at the top right.
- What changes for existing installs: nothing to do.

### Person page: the name is hidden in the title, Accounts, and Timeline without View people in AI usage (2026-11-14)

- D242 (owner, 2026-11-14). For someone without View people in AI usage, a person's page is titled "Name hidden" (still marked Person), and the Accounts box and the Timeline say how many names are hidden ("2 names hidden") in place of the names. The Entity card in How it connects reads "Name hidden", and an empty How it connects says "this person".
- The names counted as the person are not sent to the browser for those viewers: `GET /api/people/{person}/record` and `GET /api/people/{person}/timeline` send `forms` empty with the count in `forms_hidden`, and the timeline's "Possibly the same person" list empty.
- Opening Logs from the page says "From this person > ..." in place of the name.
- In "What it did", the "by <name>" label is left out for those viewers; the example log line under it is log data and is unchanged.
- The notice above the summary now reads "Names are hidden: this person's name and AI activity are not shown." and says an admin can turn on the permission.
- The page address still names the person, and the identity rows on the page (sign-ins, alerts, devices, addresses, and the Logs queries) still name the account, since that is log data the viewer may read in Logs.
- What you will notice: without View people in AI usage, a person's page shows "Name hidden" as its title and a count of hidden names in Accounts and the Timeline; with the permission, nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Two flaky tests made steady; a quick quit of the terminal app no longer shows an error (2026-11-14)

- `remnant tui`: when the list of sources arrived while the app was closing, filling it could fail and print an error on exit. A list that arrives at that moment is now ignored, as one that arrives after the app has closed already was.
- The merge queue's lock (developer tooling): where `mkdir` lets two takers in at once, the taker that had just written the lock could see the other one enter the guard as it left it, report the guard as changed, and give up, so neither queue held the lock. Leaving the guard is now not counted as a change; the lock is still checked to be its own.
- Both tests now hold the moment that went wrong still, so they fail every time the fault comes back instead of once in a while on a busy machine.
- What you will notice: quitting `remnant tui` quickly no longer prints an error; nothing else visible.
- What changes for existing installs: nothing to do.

### Log rotation: a rotated file is watched for 30 seconds more (2026-11-13)

- D252 (ADR-0051 row 3). After a rotation, a program often keeps writing to the old file for a moment, until it is told to reopen its log. The server now keeps the renamed file open for 30 seconds after it has read it to its end, and reads what is still written to it in that time. Before, it closed the file as soon as it had read it to its end, so those lines were lost on a source that watches a single file.
- A last line without a line ending in the renamed file is stored when the file is closed, not at the moment of the rotation. A line the program finishes within those 30 seconds is stored whole.
- The file is closed 5 minutes after the rotation at the latest, as before.
- What you will notice: nothing in the app. The last lines before a rotation arrive up to 30 seconds later when they had no line ending yet.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Log rotation: the read position follows the file, part 3 (2026-11-13)

- ADR-0051 (D250), the last part. Read positions of files that have not been listed or read for 30 days are removed by the daily maintenance. Before, they stayed for ever. A position is removed only when its file is known to be gone: the folder is there, on the same disk, without the file. A share that is not mounted, or a folder that is away, keeps its positions, so nothing is read twice when it returns.
- After a restart, when a log file was rotated while the server was not running, the source shows a warning on Health and Sources for a day: lines written to the old file after the time named, if there were any, were not read. There is no warning when the source's pattern also matches the rotated file, since it is then read like any file, and none for rotations while the server runs.
- The rotation guide (`docs/ingest/README.md`, "Rotating log files") describes the new behaviour: rotate with `create`; rotated files that are not compressed and that a source's pattern matches are not read twice; with `copytruncate` keep the copies out; what can still be missed.
- What you will notice: nothing, unless a file was rotated while the server was down; then a warning on that source says so.
- What changes for existing installs: nothing to do. Do not delete and re-add a source to change its file pattern: a source added again reads its files from the start. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Log rotation: the read position follows the file, part 2 (2026-11-13)

- ADR-0051 (D250), audit 2026-11 finding H5. The server keeps each log file it read from in the last 5 minutes open (at most 256 files). When a file is renamed or deleted by a rotation, what was written to it just before is still read, through that open file, also for a source that watches a single file, and also while no new file has the name yet. The file is closed as soon as it is read to its end, and 5 minutes after the rename at the latest.
- A last line that has no line ending yet is held, as before, so a line still being written is stored whole. New: when the file is rotated, or has not grown for 5 minutes, that line is stored as it is and marked `parse_status` `partial` (reason `no_newline`), also when it does not parse (a cut JSON line), and with `truncated` when it is longer than a line may be. It is never dropped. If its rest arrives later, the rest is stored as a line of its own.
- The warning for a file emptied and refilled in place (`copytruncate`) is exact while the server still holds the file open: it no longer says "or replaced by a new file" then.
- Limits that remain: after a restart of the server there are no open files, so lines written to a file just before a rename that happened while the server was down are read only if the source also lists the renamed file; the same holds for a file that had not been read from for 5 minutes. And the renamed file is closed as soon as it is read to its end: a program that keeps writing to the old file after the rotation (before it is told to reopen its log) loses those lines unless the source also lists the renamed file. If it was in the middle of a line, the first half is stored as `partial`.
- What you will notice: nothing in the app. Rotated logs no longer lose their last lines, and an unfinished last line shows up after 5 minutes instead of never.
- What changes for existing installs: nothing to do. No data or settings change; the server holds up to 256 more open files. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Log rotation: the read position follows the file, part 1 (2026-11-13)

- ADR-0051 (D250), audit 2026-11 finding H5. A text file's read position now belongs to the file itself, not to its name. A rotated copy that a folder source also lists is no longer read a second time, and a new file is never continued from an older file's position.
- A file that was emptied and refilled in place (logrotate `copytruncate`) is read again from its start, also when it had already grown past the old position. The source then shows a warning on Health and Sources for a day, naming the file: lines written during such a rotation can be lost before anything reads them, so rotate with `create`. The same warning can appear once when a correctly rotated file's replacement was given the old file's number by the file system; nothing is lost then.
- A file that has not changed is not opened at all.
- A disk whose device number changes after a restart or a remount does not cause files to be read again: the same file number with the same content is the same file, also when it was renamed meanwhile.
- Deleting a source and adding it again under the same id reads its files from the start, as before.
- Not in this part: lines written to a single-file source just before a rename are still lost, as before. Following the renamed file is part 2.
- What you will notice: nothing, unless a source rotates with `copytruncate`; then a warning on Health and Sources says so.
- What changes for existing installs: nothing to do. At the first start the server copies its read positions into a new table (`file_positions`, migration 77), so nothing is read twice; a file that is missing or cannot be opened then (a folder not mounted yet, a permission) keeps its old position until it can be read, for up to 7 days. The spool files of push sources are covered too. The old table is still written: to go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`) and the older version reads on from where this one stopped. Updating again after that picks up from where the older version stopped.

### Logs results: a pager you cannot miss, and a table that fits (2026-11-13)

- A results table with more than 50 rows has Previous and Next as buttons right beside the count ("1 to 50 of 10,000"), above the rows and again below them, and a Rows per page choice of 50, 100, or 500 that the browser remembers. Before, Previous and Next were two small links at the far right under row 50, easy to miss; they were never removed, and nothing in the redesign changed them.
- The results table is as wide as its box. Message takes the width the other columns leave and is cut with the full text on hover and in the expanded row. Before, a long message made the table wider than its box, so Message ran off the right edge and the table scrolled sideways. It still scrolls sideways inside its box when the chosen columns alone need more room.
- The same table is used by the Microsoft 365 views, a person's Microsoft 365 list, and saved search runs, so they get both changes.
- The smoke test now fails when a results list of more than one page has no pager, a pager whose Next button is off screen or disabled, or a Next that does not show other rows.
- What you will notice: Previous, Next, and Rows per page at the top left of the results, and no sideways scrolling for long messages.
- What changes for existing installs: nothing to do.

### AI usage: rows hold the place while it loads, and a plainer line (2026-11-13)

- While AI usage (and Agents > MCP servers) loads, each table shows placeholder rows, as other pages do. Before, the table headings were drawn with nothing under them for as long as the load took.
- On the Claude row, "Seen through: both 0, plugin only 1, network only 7" now reads "People: 7 seen only on the network, 1 only by the Claude Code plugin, 0 by both".
- What you will notice: AI usage no longer looks empty while it loads.
- What changes for existing installs: nothing to do.

### Design: the page pattern is checked on every change (2026-11-13)

- Console redesign, build row 24 (ADR-0052, DESIGN.md 6.0). The layout check that opens every page in both themes at 1280px now also fails when a page has more than 10 rail entries, more than 5 tabs, or more than one filled button. It opens every tab at its own address and a person, address, and host page.
- Three pages had more than one filled button and now have none: the Save buttons on Settings > About, Download plugin on Settings > Plugins, and Add domain and Add alias on Settings > Identities are outlined buttons. They do the same thing.
- What you will notice: a few Settings buttons are outlined instead of filled.
- What changes for existing installs: nothing to do.

### Design: the person page is one page (2026-11-13)

- Console redesign, build row 22 (ADR-0052, DESIGN.md 6.3). A person's page no longer has tabs. It leads with one sentence and five numbers (Open alerts, Sign-ins, Devices, Addresses, AI services), then Open alerts, Activity per day, Microsoft 365, AI use, and What it did, with Accounts, Devices, and Addresses at the side.
- Activity per day is new: one bar per day with failed sign-ins marked (real failures only; a sign-in that was interrupted or expired is not a failure), and a bar opens that day's events in Logs.
- Devices and Addresses list every row with events, failed sign-ins, and last seen, as the old Hosts and devices tab did, in the side column.
- Microsoft 365 is one table with a Sign-ins, Mail, Admin switch and Open in Logs. It is shown only when you can read a Microsoft 365 source. The server builds and runs each list with your own source access.
- The pages of a person, an address, and a host have the entity as the title, "People & devices" above it to go back, and Open in Logs as the one filled button.
- How it connects and the Timeline are folded at the foot of a person's page and are read only when opened, so the page loads faster.
- Without View people in AI usage, a notice above the summary says the person's AI activity is not shown, and the AI services number reads "Hidden".
- New read-only API: `GET /api/people/{person}/record` and `GET /api/people/{person}/m365` (in `docs/api.md`). `GET /api/people/{person}/signins` is unchanged.
- What you will notice: a person's page is one scrolling page instead of five tabs, with a chart of activity per day and Mail and Admin rows beside the sign-ins.
- What changes for existing installs: nothing to do. Links to a person's page work as before; a link that named the AI use tab opens the page at AI use.

### Design: the Dashboard's Detections section (2026-11-13)

- Console redesign, build row 18 (ADR-0052, DESIGN.md 6.3). The table of hosts and people involved also shows how many rules matched each one and when its last match was. The fourth number reads "People involved".
- A rule's name in "Matches by rule" opens Alerts > Rules with that name in the filter; its total opens the matched events in Logs, as every number does.
- When the system has paused detection, the section says so in its header ("Detection is not running for 1 schedule: ..."), and a number that would be zero reads "Not running" instead, so a quiet section is not mistaken for "nothing happened". A number above zero is still shown.
- With no rule enabled, an administrator sees "No rules are enabled." with Enable rules. Others see no section, as before.
- What you will notice: two more columns in the Detections table, rule names that open the rule list filtered by that name, and "Not running" in place of a zero while detection is paused.
- What changes for existing installs: nothing to do.

### Design: less explanatory text on the pages (2026-11-13)

- Console redesign, build rows 15 and 16 (ADR-0052 section 3.7; owner, 2026-11-13). Lines that only explained what a page is are gone (People & devices "Everyone seen in this range...", the AI flow's "Select a card...", the Agents card's first sentence, the Alert targets introduction).
- Notes about one column moved to an (i) on that column's title: how the People & devices score adds up, when a saved search's schedules update, which sources a rule runs on, what counts as a risky mail rule, how a company email is confirmed on Accounts, and what Wait and DuckDB mean on Speed. Hover over the (i), tab to it, or tap it to read the note.
- Every line about access, permissions, masking, or where data goes stays on the page: "Saved searches run with your own source access", "Only sources you may read are counted", "Alerts carry a summary and a link back, never log content", and the others like them.
- The AI review list on Alerts says in one line what it is and who reviews.
- What you will notice: shorter pages, and a small (i) beside some column titles.
- What changes for existing installs: nothing to do.

### Backups, Page rollups, and Speed are sent to administrators only (2026-11-13)

- Owner decision of 2026-11-13, following Settings > System (ADR-0052 section 3.3). The server now leaves the state of scheduled backups and the page rollups out of what it sends to Analysts and Auditors: `GET /api/health-checks` answers `backup: null` and `rollups: []` for them. Page speed was already for administrators. Before this, only the web page hid them.
- A failed or overdue backup still raises an alert that everyone sees.
- The panels that count whole days back from now say so: the Agents numbers, sessions and tool rows, and a person's AI activity and devices are labeled "Last 7 days" (or 24 hours, or the days counted), whatever the page's time choice is.
- What you will notice: the Agents numbers, sessions and tool rows, and a person's AI activity and devices now start with "Last 7 days" (or the days they count). Nothing else changes on the page for anyone: Settings > System was already hidden from Analysts and Auditors.
- What changes for existing installs: nothing to do. A script that read `backup` or `rollups` from `/api/health-checks` with an Analyst's or Auditor's token now gets null and an empty list; use an administrator's token.

### Design: Microsoft 365 is three views of Logs (2026-11-13)

- Console redesign, build row 9 (ADR-0052 section 3.3; owner, 2026-11-13). Microsoft 365 has no area of its own. Logs has a Views menu on every one of its tabs, with Microsoft 365 sign-ins, Microsoft 365 mail, and Microsoft 365 admin. Each view shows the lists the server builds and runs on the sources you can read, so they need no SQL access and show no editor: everyone who could open Microsoft 365 before can open the views.
- Nothing was dropped. The charts and lists of the old Overview (sign-in outcomes, failure reasons, sign-ins outside approved countries, apps signed in to) are at the top of the Sign-ins view. The app consents and app registrations lists of the old Apps tab are at the foot of the Admin view; the register of apps is AI usage > Inventory with Type set to Microsoft 365 apps.
- Old addresses still open: `/m365` and `/m365/sign-ins` open the Sign-ins view, `/m365/mail` and `/m365/admin` their views, and `/m365/apps` the Inventory on Microsoft 365 apps. The time window you chose is kept.
- Without a Microsoft 365 source a view says so, with Add a source.
- The views keep their 24 hours, 7 days, 30 days window for now.
- What you will notice: Microsoft 365 pages open under Logs, from a Views menu at the top right.
- What changes for existing installs: nothing to do. Bookmarks and links in alert messages keep working.

### Design: AI usage has no Review tab; its settings are under Settings (2026-11-13)

- Console redesign (ADR-0052 section 3.3; owner, 2026-11-13). Reviewing AI services and MCP servers is done in AI usage > Inventory, with its Status filter. The Review tab is gone, and its old address opens the Inventory, on Unreviewed while something waits for a review.
- What the tab held is under Settings > AI > AI watch and catalog, for administrators as before: what AI Watch alerts on, the MCP server rules, and the catalog of AI services.
- What you will notice: AI usage has three tabs (Services, People, Inventory); administrators find the AI watch settings under Settings.
- What changes for existing installs: nothing to do.

### Design: Health has three tabs; Backups, Page rollups, and Speed are in Settings (2026-11-13)

- Console redesign, build row 12 (ADR-0052 section 3.3; owner, 2026-11-13). Health has Sources, Collectors, and Delivery. Enrichment feeds are a Type of Sources; Endpoint agents and Watched devices are the two Types of Collectors. The Type choice is in the address.
- The Sources tab counts log sources only, as the Dashboard's Sources tile does; a problem on an enrichment feed still shows on the tab.
- Backups, Page rollups, and Speed moved to Settings > System, for administrators only. Analysts and Auditors no longer see these three lists. A failed backup still raises an alert, which everyone sees on the Dashboard and in Alerts.
- Old addresses still open their new places. For an Analyst or Auditor, an old Backups, Page rollups or Speed address opens System with a line saying it is for administrators.
- What you will notice: five fewer tabs on Health, a Type choice on Sources and Collectors, and System under Settings for administrators.
- What changes for existing installs: nothing to do. To go back, install the previous version with `update-systemd.sh --rollback` (docs/install/).

### Design: Agents has three tabs (2026-11-13)

- Console redesign, build row 11 (ADR-0052 section 3.3; owner, 2026-11-13). Agents has Sessions, MCP servers, and Accounts. The numbers of the old Overview tab (sessions, people, tool calls, failed calls, not-approved MCP servers in use, devices delivering late) are a strip at the top of Sessions.
- The Tools tab is gone: on MCP servers every server's row opens to its figures (people, devices, calls, failures, first and last seen), and one Built-in row opens to the tools Claude Code has built in (Bash, Read, Edit and others), one by one.
- The strip, the sessions list, and the tool rows follow the page's time choice in whole days back from now: 1 hour and 24 hours show the last day, and Custom the days since its start (30 at most).
- Old addresses still open: Overview opens Sessions, and Tools opens MCP servers.
- What you will notice: two fewer tabs on Agents, the numbers above the sessions, and an arrow on each MCP server row.
- What changes for existing installs: nothing to do.

### Design: AI usage, Agents, and People & devices use the same five time choices (2026-11-13)

- Console redesign, build row 7, time controls, part 3 (ADR-0052 section 3.7; owner, 2026-11-13). The time filter of AI usage, Agents (all tabs but Overview), and People & devices is 1 hour, 24 hours, 7 days, 30 days, or Custom with a start and an end in your own time zone. "All time" is gone: Custom with no dates is everything kept.
- On AI usage and Agents the choice is in the address (`#time=30d`), so it can be bookmarked, with a Reset link when it is not the usual 7 days. A Custom range is compared against the period of the same length before it.
- On People & devices the choice stays with the page while you move from one person or device to the next. A person's AI activity and devices count whole days back from now, so with Custom they cover the days since its start (30 at most).
- Choosing Custom starts from the window you were looking at, with its start filled in. Clear the start to see everything kept.
- The time you chose stays when you move between the tabs of AI usage or Agents.
- The Alerts address now writes a Custom range as UTC times, as Logs does, so a link opens on the same moments for a reader in another time zone.
- What you will notice: five time buttons on these pages, and two date boxes for Custom.
- What changes for existing installs: nothing to do.

### Design: Logs and Ask AI use the same five time choices (2026-11-13)

- Console redesign, build row 7, time controls, part 2 (ADR-0052 section 3.7; owner, 2026-11-13). The time filter of Logs and of Ask AI is 1 hour, 24 hours, 7 days, 30 days, or Custom, as on Alerts. Custom is a start and an end in your own time zone (hover for UTC); an empty side is open.
- "Last 15 minutes" and "All time" are gone. Custom with no dates is everything kept, which is what a query opened from another page (a rule's matches, Ask AI's "Open in Logs") now opens on.
- Old links keep working: an address with All time opens as Custom with no dates, and one with 15 minutes opens on 1 hour. A number opened from the Dashboard still shows exactly its own window, now as Custom with its two dates, and keeps it through a reload. A link with a Custom range opens on the same moments for a reader in another time zone.
- What you will notice: time is five buttons on Logs and Ask AI, with two date boxes for Custom.
- What changes for existing installs: nothing to do. Bookmarks keep working.

### Design: a Time filter on closed and muted alerts (2026-11-13)

- Console redesign, build row 7, time controls, first part (ADR-0052 section 3.7; owner, 2026-11-13). The filter bar's Time control has five choices: 1 hour, 24 hours, 7 days, 30 days, and Custom. Custom is a start and an end, as a date and time in your own time zone (hover for UTC); leaving one empty leaves that side open, so Custom with no dates is everything kept.
- Alerts: open alerts are never filtered by time, so an old open alert cannot drop out of the queue, and Open shows no Time control. Closed lists what was closed in the window, newest closed first, 7 days unless you choose another; the server picks them, so an alert raised long ago and closed yesterday is there. Muted always lists the mutes in force, and adds the ones that ended in the window, marked "ended".
- An alert opened from a link is shown whatever the window.
- API: `GET /api/alerts` takes `closed_from` and `closed_to` with `state=closed`; `GET /api/alerts/mutes` takes `ended`, `from` and `to`. A Closed list that holds only the newest of a long window says so.
- What you will notice: Closed shows the last 7 days by default; choose 30 days or Custom to see older ones.
- What changes for existing installs: nothing to do. Bookmarks to Closed open on the last 7 days.

### Design: the same loading and empty states on every page (2026-11-13)

- Console redesign, build row 15, first part (ADR-0052, DESIGN.md 6.0). The pages that still showed a grey block or "Loading…" while loading now hold the place of their rows (AI usage, Agents, People & devices, Microsoft 365, Logs panels, Audit log, Settings pages). Empty lists are left-aligned at the top with at most two lines, in the same words as before.
- Two texts are shorter: Agents > Sessions says "Pick a session.", and Users no longer says the install runs without sign-in (it has not since sign-in became required).
- Not in this part: removing the paragraphs that explain a page (the help text sweeps).
- What you will notice: empty lists read from the top left instead of the middle, and pages keep their shape while loading.
- What changes for existing installs: nothing to do.

### Design: loading, errors, and empty pages look the same everywhere they are used (2026-11-13)

- Console redesign, build row 14 (ADR-0052, DESIGN.md 6.0). Shared pieces for the states of a page: placeholder rows while a list loads (no jump when the data arrives, no spinner), an error in place with Retry, and an empty state at the top left with at most two lines and one action. Alerts and the Dashboard use them first.
- Alerts: an empty queue reads "No open alerts. Checked 2 min ago."; when the filters hide everything there is a Reset filters button; when the only alerts are in sources you cannot read, the page says so and does not say there are none.
- Dashboard: "No panels yet." with Go to Schedules.
- What you will notice: shorter, left-aligned messages on empty lists, and rows held in place while Alerts loads.
- What changes for existing installs: nothing to do.

### Design: review AI items in the Inventory (2026-11-13)

- Console redesign, build row 10 (ADR-0052 section 3.3). AI usage > Inventory has one filter bar: Active or Excluded, Type (AI services, Agents, MCP servers, Microsoft 365 apps), and Status. It opens on Unreviewed while something waits for a review, and on All when nothing does. The page header says how many wait ("3 to review").
- An administrator sets Approved or Not approved in the Status column of an AI service or MCP server. It is the same audited change as on the Services and MCP server lists; everyone else sees the status as text.
- The filters are in the address, and Export CSV and Export JSON now export what the Status filter shows (the export's audit row records it).
- The Review tab is unchanged for now.
- What you will notice: the Inventory opens on what still needs a review, with a Status filter.
- What changes for existing installs: nothing to do.

### Design: the Agents sessions filters use the shared filter bar (2026-11-13)

- Console redesign, build row 7, first part (ADR-0052, DESIGN.md 6.0). On Agents > Sessions the Person, Machine, and Tool filters and the "Has flags" box are now one filter bar like the one on Alerts: each reads "Machine ws-0042", Flags is Any or Flagged, the count of sessions is on the right, and Reset appears while something is filtered.
- The filters are in the address, next to the open session, so a filtered list can be bookmarked or sent.
- Not in this part: the time controls of Logs, AI usage, Agents, Health, and People & devices. They keep today's choices until the owner decides what Custom and "All time" become.
- What you will notice: the session filters look like the Alerts filters, with a Reset link.
- What changes for existing installs: nothing to do.

### Design: Saved searches shows what is scheduled (2026-11-13)

- Console redesign, build row 8 (ADR-0052 section 3.3). Saved searches is a tab of Logs (since the new rail) and its table has a Scheduled column: a search that runs on a schedule shows when ("Daily at 07:00"), and that is a link to the schedule on Alerts > Schedules, which opens with that schedule marked. A search with no schedule says No.
- Only schedules you can see are listed, the same ones Alerts > Schedules shows you.
- The old address `/saved` still opens the tab.
- What you will notice: a Scheduled column on Saved searches.
- What changes for existing installs: nothing to do.

### Design: one filter bar, first on Alerts (2026-11-12)

- Console redesign, build row 6 (ADR-0052, DESIGN.md 6.0). A shared filter bar in a fixed order: Time, State, the other filters, the text box, with the count on the right. Alerts uses it: State is three buttons (Open with its count, Closed, Muted), Severity and Category read as "Severity High", and the count says how many alerts are listed ("2 alerts", "1 of 2 alerts"). The count is only of alerts you can read.
- Filters are in the address (`/alerts#state=closed&sev=high`), so a filtered list can be bookmarked or sent, and Back undoes a filter. Reset appears only while a filter is off its default.
- The Alerts queue has no Time filter yet: every open alert is listed, as before.
- What you will notice: the Alerts filters look like one bar, with a Reset link when something is filtered.
- What changes for existing installs: nothing to do.

### Design: Alerts has three tabs; Open, Closed, and Muted are a State filter (2026-11-12)

- Console redesign, build row 5 (ADR-0052 sections 3.3 and 3.4, D246). The Alerts tabs are Queue, Rules, and Schedules. Open, Closed, and Muted are no longer tabs: they are the State filter, first in the row of filters on the Queue, with Open as the default and the open count beside it.
- The address shows the choice (`/alerts#state=closed`). Old addresses still work: `/alerts/closed`, `/alerts/muted`, and `/alerts/open` open the Queue with that state, without adding a step to Back, and a link to one alert (`#item=<id>`) opens it as before, closed ones too.
- What you will notice: two fewer tabs on Alerts, and a State menu where Closed and Muted now are.
- What changes for existing installs: nothing to do. Bookmarks and links in alert messages keep working.

### Design: a slimmer alert pane with one filled button (2026-11-12)

- Console redesign, build row 19 (ADR-0052, DESIGN.md 6.2e). The pane beside the alert list shows what you need to decide: severity, kind, state, and the alert's ID; the title; what fired; why it matters; who and what it is about; when; the next steps; then the actions. Close is the one filled button. "Show events in Logs" sits beside it and opens the alert's own events.
- Changes today, the rows that fired, Approve or Not approved, and the history are still in the pane, in one section called "Evidence, changes, and history" that starts closed. They move to the full alert page when that page is built; until then nothing is lost, it is one click away.
- The summary strip above the list (open by severity, new today, oldest open, by category) is removed. The Severity and Category filters under the tabs do the same filtering. The note about alerts in sources you cannot read is at the foot of the list, with no count.
- What you will notice: the alert pane is shorter and fits a laptop screen without scrolling; to approve a service or read the history from an alert, open "Evidence, changes, and history" first.
- What changes for existing installs: nothing.

### Design: one Needs you list on the Dashboard, blind states first; key numbers in one strip (2026-11-12)

- Console redesign, build row 17 (ADR-0052 section 3.9, D247). The Dashboard opens with one list of everything that needs you. Blind states are pinned first and are never folded away: a source that is down or in error, a source stored without its parser because its template is missing, and detection that the system paused (a schedule you paused yourself is your choice and is not listed). They sit on a pale amber row with a bar on the left and a "Blind" tag, and never look like an alert. Then come High alerts, then other alerts, then AI services waiting for review, five rows at most, with "N more on Alerts" under them.
- Each row says what kind it is, what it is, who or what it is about (a link), and when. A source gap alert is a blind row that opens its alert; an AI review row opens AI usage.
- This replaces three things that said the same in different places: the Health banner at the top, the one-line "Needs attention" strip, and the Sources line at the bottom. A blind state is now said once, here, and on Health (D243's banner is superseded by D247).
- Under the list, one strip of key numbers for the chosen window: Open alerts, Failed sign-ins, Sign-ins outside approved countries, AI services in use (with how many are to review), and Sources healthy (the same count as on Health, in amber when not all are). Each number opens the place to act on it, and each has its "how this is counted" note. A tile shows only when you have its source.
- The note about alerts in sources you cannot read stays at the foot of the list, with no count.
- For the "AI services in use" number the AI Watch summary (`/api/ai/watch/summary`) gained one field, `services_in_use`.
- The few alert lines the Dashboard asks for (`/api/alerts/lines`) now come in the list's own order (High, other alerts, then AI review items), with a `review` field naming the review items, so services waiting for review can never push a real alert out of the five rows.
- A source gap alert whose source is sending again is an ordinary alert row asking to be closed, not a blind row.
- What you will notice: the top of the Dashboard is one list and one row of numbers; the amber Health banner, the "Needs attention" line, and the Sources line at the bottom are gone. The "risky mail rule" and "blocked app consent" counts that were in that line are still in the Identity section below.
- What changes for existing installs: nothing.

### Design: the rail lists pages only (2026-11-12)

- Console redesign, build row 4 (ADR-0052 section 3.2, D246). The left rail is nine entries with nothing under them and nothing to fold: Monitor (Dashboard, Alerts), Investigate (Logs, Ask AI, People & devices), AI (AI usage, Agents), and, pinned at the bottom, Health and Settings. A page's tabs are in its header. The rail is narrower (208px) and fits a laptop screen without scrolling.
- Logs, Ask AI, and People & devices are pages of their own, each titled by its own name. Saved searches is a tab of Logs. Addresses are unchanged.
- Microsoft 365 is no longer in the rail. Its pages still open by their address and from Ctrl+K ("Microsoft 365") until they move into Logs, the person page, and the AI inventory in later steps.
- Health shows a small dot in the rail only when one of the sources you can read needs attention; a source paused on purpose does not count. On the Dashboard and Health the dot follows what the page itself shows, as it refreshes. On other pages it asks a new numbers-only request, `/api/health/count`, once every five minutes, so there it can be up to five minutes behind; that request names no source and writes no audit row, like the alert count, and it never stands in for the recorded read of Health or Sources: opening those pages is still recorded as before.
- An Auditor sees only what they can open: no Ask AI, and Logs opens on Saved searches unless an administrator has allowed Auditors to run SQL.
- The open-alert counts in the rail and on the bell use the solid High color. Ctrl+K lists every page and every tab under Navigate.
- What you will notice: a shorter left menu with no sub-items; Saved searches is now a tab on Logs; Microsoft 365 is found through Ctrl+K.
- What changes for existing installs: nothing to do. Bookmarks keep working. The rail no longer remembers folded groups, since there is nothing to fold.

### Design: every page uses the one page header; the command bar is gone (2026-11-12)

- Console redesign, build row 3 (ADR-0052 section 3.5, D246). Every page now has the same header: its name and a short count or status on the left, and its buttons at the top right, with at most one filled button. The row of text commands under the title is removed everywhere.
- Logs: Save and Open are buttons at the top right; New search, Library, Schedule, Add to dashboard, and Export CSV are under the "More" button next to them. Run stays beside the search box and the SQL editor, where it already was, and is the page's one filled button.
- Alerts > Rules: "Enable selected", "Disable selected", and "Schedule selected" sit directly above the rule list they act on.
- Audit log: Export CSV is an outlined button at the top right; the "Append-only" sentence under the title is removed.
- Logs: while an export from the More menu runs, "Exporting…" shows beside the page title.
- On a phone the header's buttons take their own row under the title and tabs.
- `scripts/check-layout.py` also fails when a page has no `h1` or more than one.
- What you will notice: buttons moved from a row under the page title to the top right of the page, and on Logs five less-used commands are behind "More".
- What changes for existing installs: nothing.

### Design: severity colors only for severities; states are outlined tags (2026-11-12)

- Console redesign, build row 1b, last of four changes (ADR-0052 section 3.10, D248). The tinted red, orange, and yellow boxes that marked things other than an alert severity are gone: errors, failed checks, blocked requests, and "Out of date" are outlined in the error color; warnings, "Needs attention", denied outcomes, "Changed", and sensitive-data counts are outlined in the warning color; neutral tags (success, built in, counts) sit on the plain gray tag fill, and "New agent" is a neutral outlined tag, because the accent color is kept for links and selection. Solid red and orange now always mean a Critical or High severity.
- The Health page's per-source flow lines have no filled area, like the other charts, and its header row is flat.
- The old tinted color tokens are removed from `tokens.css`.
- What you will notice: error and warning messages are a colored outline with colored text instead of a tinted box; nothing moved.
- What changes for existing installs: nothing.

### Design: one page header, first on Alerts and the Dashboard (2026-11-12)

- Console redesign, build row 2 (ADR-0052 section 3.5, D246). `PageHeader` is the one header every page will use: the page's name and an optional count on the left; on the right up to two outlined buttons, a "More" menu for the rest, and at most one filled button, last. The page's tabs follow. With the keyboard the order is title, tabs, then the buttons.
- Alerts and the Dashboard use it now; the other pages follow in the next change and keep their row of text commands until then.
- Dashboard: the heading is always "Dashboard". A board's own name is in the board picker and at the right of the row under the header. "Edit layout" and "New dashboard" are buttons at the top right.
- Alerts: the sentence under the tabs ("Everything that fired and needs a decision...") is removed; the page does not explain itself in a paragraph.
- What you will notice: on the Dashboard and Alerts the title row is slimmer and the buttons sit at the top right.
- What changes for existing installs: nothing.

### Design: charts as lines, one change pill, one cited ID chip (2026-11-12)

- Console redesign, build row 1b, third of four changes (ADR-0052 section 3.10, D248). Trend charts are thin lines with no filled area. Where a chart used to stack its parts into bands (AI use by review status on the Dashboard, failed sign-ins by class on Microsoft 365), each part is now its own line at its own value; the legend names them and the hover still gives the total.
- The change beside a headline number ("↑ 53", "same") is one neutral pill everywhere, and a cited event ID in an explanation or an Ask summary is one chip. A cited ID that was not among the events sent is outlined in the error color instead of filled.
- `scripts/check-layout.py` waits for the app's fonts and fails when Geist or Geist Mono is not the font in use, so pages are measured as users see them.
- `docs/BACKLOG.md`: a 2027 item for company-wide local AI through one gateway (nothing built).
- What you will notice: the Dashboard charts are lines, not filled bands; on the AI use chart and the Microsoft 365 failed sign-ins chart the lines no longer sit on top of each other, so read each line against the scale by itself.
- What changes for existing installs: nothing.

### Design: flat table headers, clearer edges on inputs and checkboxes (2026-11-12)

- Console redesign, build row 1b, second of four changes (ADR-0052 section 3.10, D248). Every table header is the same: no fill, small text in the secondary color over a thin divider.
- Text inputs, selects, and checkboxes have a darker edge (`--border-control`, at least 3:1 against what they sit on), so a field is visible before you click it. Checkboxes are drawn by the app in both themes and fill with the accent color when ticked. Buttons with a text label keep their lighter edge.
- What you will notice: quieter table headers, and input boxes and checkboxes that are easier to see, mostly in the light theme.
- What changes for existing installs: nothing.

### Design: solid badges for Critical and High only, dots for the rest, sentence-case panel titles (2026-11-12)

- Console redesign, first half of build row 1b (ADR-0052 section 3.10, D248). Severity looks the same everywhere it appears (Logs, Alerts, the Dashboard's Needs attention list, rules, People & devices, mail rules): Critical and High are solid badges; Medium, Low, and Info are a small square dot followed by the word. Low is no longer blue. Every mark keeps its word.
- AI review status is a dot and the word: Approved a filled green dot, Unreviewed a hollow dot in the accent color, Not approved a hollow dot in the warning color. It no longer uses the red of a Critical alert, because a review status is not an alert; the same holds for the AI use chart on the Dashboard (Unreviewed in the accent color, Not approved in the warning color) and the "not approved in use" count on AI usage.
- Panel titles are 14px in sentence case; nothing in the app is set in upper case any more.
- What you will notice: fewer colored boxes on a calm screen, and only Critical and High stand out as filled badges.
- What changes for existing installs: nothing.

### Design: the Graphite colors, Geist fonts, and Comfortable rows for everyone (2026-11-12)

- First build step of the console redesign (ADR-0052, D248). The colors in both themes are the Graphite set: flatter, with cards drawn by their border. Text is set in Geist and data in Geist Mono (license OFL-1.1, shipped with the app, nothing fetched); the Source fonts are gone. Layout, navigation, and badges are unchanged in this step.
- Comfortable is now the row density for everyone on every screen width, with rows 34px tall (36px before). Compact is still in the user menu and is remembered per user in the browser; it now also makes text one size smaller (13px for text, 12px for data, smaller headline numbers), where before it only made rows shorter. Before, a window under 1440px wide started Compact.
- Two contrast fixes the owner approved: the edge color for text inputs in the light theme is darker (`#808896`), and keyboard focus inside the top bar has its own ring color, since the top bar is dark in both themes.
- `scripts/check-contrast.py` runs in CI: 160 color pairs across both themes must meet WCAG AA, and `tokens.css` must match `docs/DESIGN.md` section 11. `scripts/check-layout.py` now checks every page in the light theme too. On the Users page the last sign-in time may wrap onto two lines so the table fits a 1280px window.
- What you will notice: new colors and a new typeface on every page, slightly taller rows if your window is under 1440px wide and you never picked a density, and smaller text if you picked Compact.
- What changes for existing installs: nothing to do. A density you picked before is kept. To get the denser rows back, choose Compact in the user menu. Going back to the release before this one restores the old look (`docs/install/`, `update-systemd.sh --rollback`).

### Design: the console redesign is accepted; DESIGN.md describes it (2026-11-12)

- The owner accepted ADR-0052, "Navigation and page pattern built around top tasks" (decisions D246 to D248): a rail of 10 pages with no sub-pages, one page header with at most one filled primary button, one filter bar, five page layouts, one Needs you list on the Dashboard with blind states pinned first, and the Graphite look (new colors, solid badges for Critical and High only, Geist fonts, Comfortable density by default).
- `docs/DESIGN.md` sections 1 to 8 and 11 are edited to it. This change is documents only: the app looks and works as before until the build's own changes land, tokens and fonts first.
- What you will notice: nothing visible yet.
- What changes for existing installs: nothing.

### Audit: AI Watch on the Dashboard is part of the visit's entry unless it shows a name (2026-11-12)

- A Dashboard visit wrote its `dashboard.view` entry and, for AI Watch, a separate `ai.view` entry on every load and every refresh. Now AI Watch that names no one, for the window the page shows, is listed as `ai_watch` in the visit's entry and writes nothing of its own (owner decision; ADR-0029 G3 amended).
- AI Watch that shows a person's name still writes `ai.view_people` every time, so the list of who saw people's AI usage stays complete.
- Requests outside a Dashboard visit (the CLI, scripts), and AI Watch asked for another range than the page's window, are audited one by one as before.
- What you will notice: nothing on screen; fewer "Viewed AI usage" entries in the audit log.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/team-vm.md`, Rolling back); entries already written stay as they are.

### One audit entry per Dashboard visit and per People & devices load (2026-11-12)

- Opening the Dashboard now writes one `dashboard.view` audit entry for the visit, listing every part the page loads (Identity, Attacks and access, Detections, the Overview numbers), the window, and the sources the viewer can read, instead of three `dashboard.sections` entries and an `overview.view` entry. The audit log records access, not requests (owner, 2026-11-12).
- The entry is written by the page's first request, before it is answered, and is never held back: a crash or restart loses no entry.
- The page sends one visit id and the list of parts it loads with its requests. A request without them, from the CLI or a script, is audited on its own as before. An id covers only the same person's requests, while the page stays open (its own refresh every minute keeps the visit going) and for at most 12 hours; after a minute without requests, or past 12 hours, the next request starts a new entry; a part not in the list, another window, or a change in the sources the viewer can read gets its own entry at once.
- AI Watch and the Needs you lines keep their own entries: `ai.view_people` whenever they show names (ADR-0029 G3).
- People & devices writes one entry per load instead of two: `ai.view_people` (surface `investigate.risk`) when the answer shows AI usage by person, otherwise `investigate.risk`, which now says that no names were shown and for which range (ADR-0029 G3, amended by the owner). To list every load of that page, search the audit log for both actions.
- For developers: `scripts/dev/queue.sh` holds a lock while it merges, and `scripts/dev/heavy.sh <command>` runs full suites, speed checks, and loops only while no merge is running (exit code 75 otherwise, `--wait` to wait).
- What you will notice: nothing on screen; the audit log gets one entry per Dashboard visit instead of four, and one per People & devices load instead of two.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`): the older version writes one entry per request again; entries already written stay as they are.

### Setup: a valid setup link works even when wrong ones reached the limit (2026-11-12)

- Wrong setup links are limited per address (5 in 5 minutes). Behind a reverse proxy without `trusted_proxies` every person has the proxy's address, so someone sending wrong links could keep the real first setup out. A valid, unexpired link now passes that limit (owner decision, D245 amended); wrong and expired links still count and are refused, and the link check is unchanged.
- `docs/install/tls.md` says to set `trusted_proxies` so the limits count each person's own address.
- What you will notice: nothing visible, unless your first setup was being blocked with "Too many failed attempts".
- What changes for existing installs: nothing. To go back: `update-systemd.sh --rollback` (see `docs/install/team-vm.md`, Rolling back).

### Docs: D244 accepted (2026-11-12)

- The owner confirmed decision D244 (lake maintenance is one of the never-silent paths) as written; its status now reads Accepted.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.

### Development: handoff after the owner's decisions on the audit batch (2026-11-12)

- `docs/handoff.md` (development only, not published) records #538 and #539 as merged, ADR-0051 as a draft waiting for the owner, the decision to fold the People & devices AI view audit row into the page's visit row with the audit volume item, and what is left before the next publish.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.

### Security: no access without an account, also on the machine itself (2026-11-12)

- Found by the 2026-11 audit (H1): an install bound to `127.0.0.1` with no accounts treated every request as the administrator. Behind a reverse proxy on the same machine, as `docs/install/tls.md` describes, every request comes from `127.0.0.1`, so until the first account existed anyone who could reach the proxy was the administrator. No header check closes this (a plain `proxy_pass` sends none), so the mode without sign-in is removed (D245, amends ADR-0001).
- With no accounts the server now only accepts the one-time setup link, on every address. The link is in the server log at each start, and `app-admin setup-link` on the server prints a fresh one (single use, 30 minutes). On a loopback install the link opens on the machine itself; from another computer use an SSH tunnel (`docs/install/tls.md`, "First setup through a proxy") or set the public name and URL first.
- An install that ran without sign-in keeps its work: saved searches, schedules, dashboards and alert items of the old built-in `local` user become the first administrator's when that account is created (recorded in the audit log). Until then schedules keep running, and Claude Code telemetry sources keep delivering with their token.
- Development tools (`make demo`, the speed check, the smoke test, screenshots) create their throwaway server's administrator through the same link; the demo's password is generated per run in `data/demo/state/dev-account.json`.
- What you will notice: nothing if you already sign in. If your install opened without a sign-in page, it now shows the setup page, which asks for the one-time link, until you open that link and create your administrator account; after that you sign in as on any other install.
- What changes for existing installs: installs with accounts, nothing. Installs without accounts: after the update, run `app-admin setup-link` on the server (or read the link from the server log), open it, and create the administrator; ingest, schedules and alerts run in the meantime. To go back: `update-systemd.sh --rollback` (see `docs/install/team-vm.md`, Rolling back). The older version ignores the new `setup_link` table; if you already created the administrator it keeps asking for that sign-in, and the items it took over stay with it.

### Docs: rotate with create, not copytruncate; rotation ADR draft; the session handoff is not published (2026-11-12)

- `docs/ingest/README.md` and the rsyslog guide now say to rotate log files by rename (logrotate `create`), not `copytruncate`, to keep rotated copies out of a source's file pattern, and name the gap that remains (a line written in the last seconds before a rename can be missed). The rsyslog guide no longer says both styles are handled. Found by the 2026-11 audit (H5).
- `docs/adr/ADR-0051-file-rotation.md` is a draft for the owner's review: one read position per file, not per path. Nothing in it is built.
- Development only: `docs/handoff.md` (open work and owner questions) is left out of the published tree, and `publish.sh` stops if it would be published. The install guide `docs/install/handoff.md` is unaffected.
- What you will notice: nothing visible in the app. If your logrotate rule uses `copytruncate`, change it to `create` as the guide shows.
- What changes for existing installs: nothing.

### Lake maintenance keeps going past a bad folder and says when it is stuck (2026-11-12)

- Hourly compaction stopped at the first day folder it could not read and never reached the folders after it, and a failed retention delete skipped compaction, the AI rollups, and the integrity check for that run. The only sign was a warning in the server log once a minute (found by the 2026-11 audit).
- Each maintenance job now runs on its own: one failing does not skip the others, and one day folder that cannot be compacted does not stop the rest. A file whose content cannot be read (its footer reads, its data does not) is moved to `data/quarantine/`, as files with an unreadable footer already were, so searches over that day work again. An error of the system (out of memory, a disk error) never moves a file.
- A job that fails, or a compaction run that left a folder undone, is listed on Health under failing jobs. If it lasts 15 minutes, alert targets get one "stopped" message and, when it works again, one "running again" message, with the usual flap limit (D236, D244). A job that failed outright (retention, compaction, the integrity run) is tried again on the next tick, a minute later; the AI rollup build waits for a compaction run that got through.
- What you will notice: nothing visible while maintenance is healthy. If it gets stuck, Health lists the job and, after 15 minutes, your alert targets get one message.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`); files already moved to `data/quarantine/` stay there.

### Development: publishing checks its folder, its source, and names outside file contents (2026-11-12)

- Development tooling only (`scripts/publish/publish.sh`, not part of the public tree). Found by the 2026-11 audit: the script emptied whatever folder `PUB_DIR` named without checking it, copied the local `main` instead of what the merge queue had put on `origin/main`, and matched the name list against file contents only.
- It now stops, before removing anything, unless `PUB_DIR` is a separate clone standing exactly on the public `main` (never the development checkout or one of its worktrees); publishes `origin/main` and stops when the local `main` differs from it; refuses a tree that still contains `scripts/dev/`; checks the name list against file names, the commit message, and the tag; fixes the public commit's author and committer whatever the environment says; and checks that the one new commit sits directly on the public `main` before pushing.
- Not decided here: whether `docs/handoff.md` should stay in the public tree (owner).
- What you will notice: nothing visible.
- What changes for existing installs: nothing.

### Development: the publish scan catches more real-looking names (2026-11-12)

- Development tooling only (`scripts/publish/`, not part of the public tree). The scan that stops a publish when the tree names a real organization missed some forms (found by the 2026-11 audit): names in capitals, names in code comments, some country and business endings, a customer's own subdomain under an allowed vendor (a Slack workspace, a Microsoft tenant), links to another owner's repositories, names in a file's own name, and images, which it could not read at all.
- It now reads names in any letter case and in comments, knows more endings, allows tenant-bearing vendors by exact host only, checks the owner in repository links against a list, scans file names, and stops on an image (or any file that is not text) that is not in the reviewed list `scripts/publish/binaries.txt`. The leak scan also knows the shape of a real Slack webhook path and a signed webhook URL.
- The images already in the tree are listed as they were; they were not looked at again.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.

### A failed update leaves a known version; nightly backups no longer show in the AIDE check (2026-11-12)

- `update-systemd.sh`: when the build of the new version failed after the checkout had moved, the service was started on the new code with the old packages, and `--rollback` then went two versions back (found by the 2026-11 audit). Now the script returns the checkout to the version the service last ran, rebuilds it, and starts it. A rollback whose build fails does the same.
- When the new version was built but did not start, the script records the version it replaced before it stops, and says so: `--rollback` returns to the version that was running, not to the one before it, and reports the build that did not start as what it left (D226).
- The AIDE rules the script writes (`/etc/aide/aide.conf.d/90_aide_remnant`) now skip the files in the data folder's `backups/` (scheduled backups write a new archive every night) and keep watching the `backups/` folder and the data folder themselves for owner, group, and mode.
- What you will notice: nightly backups no longer appear in the update's AIDE check, and a failed update no longer needs manual repair before a rollback.
- What changes for existing installs: the rules file is replaced on the next update, as on every update; with `--aide` that run reports the rules file as changed once, which is expected. If you added your own rules file for backups (for example `/etc/aide/aide.conf.d/90_remnant`), you can delete it. To go back, `update-systemd.sh --rollback` (see `docs/install/team-vm.md`, Rolling back); the older script writes the older rules on its next run.

### A failed write to the lake no longer stores the same events again and again (2026-11-12)

- Ingest saves its position in a file only after the events are written. When a write failed part way (the integrity ledger could not be written because the disk was full or the database was locked, or a second day's file could not be written), the file already written stayed in the lake, and the next pass two seconds later wrote the same lines again, on every pass while the fault lasted. Searches then showed each event many times (found by the 2026-11 audit).
- A write is now all or nothing: on a failure the files it had written are removed before the error is reported, so the retry stores each event once. The source still shows its error while the fault lasts, as before.
- The same when the events were written but the position could not be saved (the database was locked or full at that moment): the files are taken back, with the removal recorded in the integrity ledger. This covers files, the syslog spool, Windows event logs, Loki, and API sources (tested on the file path; the others share the same step). If the removal cannot be recorded either, ingest writes nothing more until it can, tries again on every pass, and compaction is told to leave those files alone.
- Compaction leaves files newer than a minute for its next run, so it does not merge a file ingest is about to take back. A failed write no longer leaves a temporary file behind on a full disk, and a write whose folder could not be synced to disk is taken back like any other failed write.
- Files are taken back under the same lock as compaction, retention, and the integrity check, so a check never sees a recorded file disappear under it; while that lock is held the take-back waits for the next pass.
- Not covered: a restart while a file is still owed to an undo repeats that one batch once; a file changed on disk after it was written is left for the integrity check to report instead of being removed; a file whose removal was recorded but which could not be deleted from disk stays and its lines are stored again; a reparse started while a file is owed can keep a copy of its rows.
- A crash (power loss, the process killed) between the write and saving the position can still repeat up to one read (8 MB) of a file once, as before.
- What you will notice: nothing visible; a full disk or a locked database no longer leaves repeated events behind.
- What changes for existing installs: nothing to do. Events already stored twice by an earlier fault are not removed. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`).

### The merge queue stops when the CI changes job fails (2026-11-12)

- Development tooling only. The CI `changes` job decides whether the backend and frontend jobs run. When it failed, both were skipped, and the merge queue read "architecture passed, the others skipped" as a green run and merged (found by the 2026-11 audit).
- The queue now requires the `changes` job to succeed, and requires the job each changed path needs (backend for `backend/`, `library/`, `templates/`, `scripts/`; frontend for `frontend/`) to succeed, not to be skipped. Docs-only PRs still run no CI.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.

### People & devices hides a person's AI watch flags without View people in AI usage (2026-11-12)

- People & devices listed, next to each person's name, the AI watch flags on them (personal Claude account, unreviewed AI service, new MCP server, blocked or failed tool calls) and counted AI Watch alerts about them, for every viewer. That is AI usage by person, which **View people in AI usage** is meant to keep to the people an admin chose (D242, ADR-0029 G2; found by the 2026-11 audit).
- Without the permission, a person's row now carries no AI watch flags, counts no AI Watch alerts, and its score leaves both out. The AI watch flags column says "Hidden" for people. Machines and addresses keep their flags and alerts, as on the AI pages (machines, never names). The check is on the server (`GET /api/entities/risk`).
- Administrators and anyone with the permission see the page as before.
- Each load of the ranking is recorded as on the AI pages (ADR-0029 G3): `ai.view_people` (page `investigate.risk`) when it showed a person with an AI watch flag or an AI Watch alert, otherwise `ai.view`. This is one more audit entry per load, next to `investigate.risk`.
- What you will notice: without View people in AI usage, the AI watch flags column on People & devices says "Hidden" for people, and their scores no longer include AI watch flags or AI Watch alerts.
- What changes for existing installs: nothing to do. An admin can turn on View people in AI usage for someone on the Users page. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`).

### The start page is always the Dashboard, and the alerts note no longer counts what you can't read (2026-11-12)

- Opening the address of the app, or the product mark, now always opens the Dashboard, also when it has no panels yet (D243). Before, it opened Health when the Dashboard had no panel.
- When a source is not healthy or has a gap open, a one-line Health banner at the top of the Dashboard says so in the same words as the Sources line at the bottom, with Open Health.
- When an open alert is in a source you can't read, the Alerts summary and the Dashboard's Needs you banner say "Some alerts are in sources you can't read. Ask an admin for access." instead of how many there are. The alert API answers `restricted` as true or false, no longer a count. Admins read every source, so they never see the note.
- While the Health banner shows, the Sources line at the bottom of the Dashboard is hidden, so the problem is said once; the banner links to the gap alert when there is one, otherwise to Health. When every source is healthy the banner is gone and the bottom line shows as before (owner, 2026-11-12).
- What you will notice: the start page is always the Dashboard, with a banner when something needs attention on Health, and the alerts note no longer says how many alerts are in sources you can't read.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`): the older version opens Health again when the Dashboard has no panel and shows the count.

### Tests: a Claude Code session across midnight UTC counts once (2026-11-11)

- A session from 23:50 to 00:10 UTC (4 PM in UTC-8) was checked on every page that counts sessions: AI usage People and MCP servers, Agents Sessions, Accounts, and Overview, the person page's AI activity and timeline, with the AI rollup built or not, ending today or on closed days, over the last 7 days; AI usage People also for ranges that start or end at midnight. Each counts it once; sessions are counted from the events, never added up per day.
- The two sessions a test saw at 23:56 UTC came from the test's own helper, which named each session after the day of the month, so records either side of midnight had two session ids. The helper now uses one session id, and the new test keeps every page to one.
- What you will notice: nothing visible; a session across midnight already counted once.
- What changes for existing installs: nothing to do; tests only, the app and the AI rollup are unchanged and nothing rebuilds. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`).

### The Audit log hides names from AI pages without View people in AI usage (2026-11-11)

- Audit entries that store a person from an AI page keep the names they recorded, so the audit log stays complete and no stored entry changes: AI Watch's own entries (`ai.sighting`, `ai.sensitive`, `ai.agent_change`), approving an agent from its alert (`ai.review`), AI views of a person (`ai.view` and `ai.view_people` with the person asked for or the AI flow of a person, and `investigate.graph` for that flow), excluding or including a Claude Code agent in the inventory (`ai.inventory_exclude`, `ai.inventory_include` with a `cc|` key), and closing, reopening, muting, or unmuting an AI watch alert (`alert.close`, `alert.reopen`, `alert.mute`, `alert.unmute`, whose subject can hold a person for alerts stored before they stored no names). The Audit page and its CSV export now show "a person" in place of each name to anyone without **View people in AI usage**, using the same rules as AI watch alerts, and the entry's own user stays (D242). A machine stays visible only where the entry itself proves it is a machine (the AI agent lines, "Claude Code, a person: WS-1"); in AI service and MCP sighting entries nothing proves that, so the device is hidden too. Alert entries about other kinds of alert are shown as stored.
- Opening a person's page writes `search.timeline` with the person, as before: the person page is not an AI page, so that entry keeps the name. The `ai.view` or `ai.view_people` entry the same page writes no longer repeats the person; it keeps the page, the days, the sources, and whether names were shown.
- The Audit page says once, above the list, "Names are hidden. An admin can turn on View people in AI usage for you." when an entry on the page has hidden names.
- The audit filters (action, user, outcome, time) never search the entry's details, so no filter can find an entry by a hidden name.
- An export that carries these names, for an administrator or anyone with the permission, is also recorded as `ai.export_people` with the number of rows.
- Entries for services, MCP servers, apps, MCP clients and API keys (`mcp|<machine>|...`, `key|<id>`), and exports (`ai.inventory_export`, `ai.export_people`) name no one and are shown as stored. A Claude Code agent keyed by its machine (`cc|<host>`) cannot be told from one keyed by a person in an entry, so it shows "a person" too, and a machine in an AI agent line can be hidden when the same entry also names a person: this hides more than needed, never less.
- What you will notice: without View people in AI usage, audit entries from AI pages on the Audit page and in its export show "a person" instead of names, and nothing stored changes.
- What changes for existing installs: nothing to do; stored audit entries are unchanged. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`): the older version shows these entries with names again to every admin and auditor.

### A script that turns AI watch alert codes back into names (2026-11-11)

- A new script, `scripts/restore_alert_text.py`, is for an administrator who rolls back to a version from before AI watch alerts stored codes such as `{p:3f2a9c0b1d4e5f60}` in place of names, and wants the older version to show and match those alerts by name again. It turns each code in AI watch alerts and their mutes back into the name it stands for, in place: it finds the name in that alert's own People with the install key (`.key` in the data folder), as the server does when it shows an alert. Everything else stays as it is, including what changed since the update: new lines in an alert's changes, people added, counts, alerts raised since, alert states and notes, rule alerts, where each source had read up to, the lake file ledger, and the audit log so far. Each run that changes something is recorded in the audit log as `alerts.restore_text`, with counts only (and the server account that ran it), chained like every other audit row; a `--dry-run` or a run with nothing to do adds no row.
- With `--backup` and one of the copies the server made before rewriting (`backups/meta-before-alert-rewrite-<time>.sqlite`), a code whose name has since left the alert's People is also looked up in the People that alert had in the copy; nothing else is taken from the copy. A code no one matches stays, as does an alert the older version has raised again since the rollback (two alerts cannot share a reference or group); the script counts both. To check the key, the server now stores, with its record that AI watch alerts are coded, the code of a fixed text; the script makes that code with its key file and, when the two differ, refuses (exit 3) and changes nothing, whatever is left to decode. A database coded before the server kept that value is checked by matching instead: the script refuses only when codes are left and not one matches a name, and otherwise stores the value so later runs check it the first way. It prints counts only, never names. Running it again is safe: a second run decodes what it can (more with `--backup`), counts again the codes no one matches, and changes nothing else. Add `--dry-run` to see the counts without changing anything.
- Steps with systemd: before rolling back, copy the script out (the older version does not have it): `sudo cp /opt/remnant/scripts/restore_alert_text.py /var/lib/remnant/backups/`. Roll back (`sudo sh /opt/remnant/scripts/update-systemd.sh --rollback`, see `docs/install/team-vm.md`), then `sudo systemctl stop remnant`, then `sudo -u remnant python3 /var/lib/remnant/backups/restore_alert_text.py --meta /var/lib/remnant/meta.sqlite --backup /var/lib/remnant/backups/meta-before-alert-rewrite-<time>.sqlite` (the newest copy from `ls /var/lib/remnant/backups/`), then `sudo systemctl start remnant`.
- Steps with Docker: before rolling back, copy the script out of the checkout: `cp /opt/remnant/scripts/restore_alert_text.py "$HOME/restore_alert_text.py"`. Roll back as `docs/install/team-vm.md` describes (check out the earlier commit and rebuild), then `cd /opt/remnant && docker compose stop app`, list the copies with `docker compose run --rm --no-deps app ls /srv/data/backups`, run `docker compose run --rm --no-deps -v "$HOME/restore_alert_text.py:/restore_alert_text.py:ro" app python3 /restore_alert_text.py --meta /srv/data/meta.sqlite --backup /srv/data/backups/meta-before-alert-rewrite-<time>.sqlite`, then `docker compose start app`.
- What you will notice: nothing visible; the script runs only when an administrator runs it by hand.
- What changes for existing installs: the settings database gets one new empty column for that stored value (`one_time_fixes.value`), filled at the next start; an older version ignores it. Nothing else changes until the script is run, and the server never runs it. To go back after running it, stop the server and copy back the `meta.sqlite` you had before (or roll forward again, which copies `meta.sqlite` to a new file and codes the names again); update and rollback steps are in `docs/install/` (`update-systemd.sh --rollback`).

### AI watch alerts store no names (2026-11-11)

- AI Watch alerts no longer store names in their title, details, changes, or subject. Each person is kept only in the alert's People field, and the text holds a code in its place (a keyed hash of that exact spelling, the same for one person every time, so repeats still join the same alert and mutes still match). The code goes only where a person stands (the person a sensitive-data or account alert is about, an agent's owners, who used a service): machine, host, and client names are never changed, even when they contain a name. When an alert is read, the names are put back exactly as they were for administrators and anyone with **View people in AI usage**, and "a person" is shown to everyone else (ADR-0029 C6, D242).
- At each start, AI Watch alerts and their mutes stored with names (all of them at the first start after this update) are rewritten the same way, and names that were only in the text move into the People field. An alert whose rewritten reference would clash with another is left as it was and still shows "a person" without the permission. The server logs how many it rewrote and left, never the names.
- Just before that rewrite, the server copies its settings database (`meta.sqlite`) to a new file, `backups/meta-before-alert-rewrite-<time>.sqlite` (the time in UTC, such as `20261111T093000Z`), in the data folder (`/var/lib/remnant/backups/` with systemd, `/srv/data/backups/` with Docker), readable by the service account only. It never overwrites an earlier copy, and it makes one only when there is something to rewrite. An alert left as it was never causes a copy on its own. If the copy fails (a full disk, permissions), nothing is rewritten at that start. At the first start, new AI watch alerts then keep names in their stored text as before, so mutes and repeats keep matching; once a start has rewritten them, new alerts keep their codes and only what is still stored with names waits for the next start. Either way, Health shows "AI watch alerts still store names: the backup before the rewrite failed. They stay hidden when read; the next start tries again." Viewers without the permission still see "a person" throughout.
- What you will notice: nothing visible; alerts read as before.
- What changes for existing installs: stored AI watch alerts are rewritten at the first start (text and subjects get codes, names move to the People field), after a copy of `meta.sqlite`; nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`): the older version then shows the rewritten alerts with codes such as `{p:3f2a9c0b1d4e5f60}` in place of names in their text and subjects, opens new alerts beside them instead of joining them, and its mutes of a person's alerts stop matching; rolling forward again copies `meta.sqlite` to a new file and rewrites what it raised. To turn those codes back into names, run `scripts/restore_alert_text.py` as the note "A script that turns AI watch alert codes back into names" describes, starting before the rollback.

### AI watch alert messages carry only a reference and a link; summaries record no AI view on load (2026-11-11)

- Messages to alert targets (Teams, Slack, email, webhooks) for AI watch alerts carry only a reference and a link: "AI watch alert", the kind, the severity, how many items are new or changed, and a link to Alerts. No person, machine, service, or MCP name and no line of the item is sent (D242, replacing the per-target setting ADR-0029 G5 described). The audit log entry for each message keeps what AI Watch saw, as before.
- The alert badge, the collapsed rail's alert button, and the Dashboard's open-alerts count read a new count-only answer (`GET /api/alerts/count`) and write no audit row.
- The Dashboard's "Needs you" lines and Health's newest open alert read only the lines they show (`GET /api/alerts/lines`). They write an `ai.view_people` audit row only when a shown line names someone to a viewer with View people in AI usage, and no row otherwise. Opening Alerts or an alert is recorded as before.
- What you will notice: AI watch alert messages to Teams, Slack, email, or webhooks no longer list items or names, only the count, the severity, and a link to Alerts; the audit log no longer gets an AI view entry from the alert badge or from a Dashboard or Health load that shows no name.
- What changes for existing installs: nothing to do; no stored data or settings change. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`): messages list the items again and the badge, Dashboard, and Health read the full alert list.

### AI watch alerts hide names without View people in AI usage (2026-11-11)

- On Alerts, a viewer without the **View people in AI usage** permission sees AI Watch alerts with "a person" in place of each name in the title, the details, and the changes, including alerts raised before this update. The People row says names are hidden, and "Person on device" gives the count without names. Rule, saved search, and source alerts are unchanged (ADR-0029 G2, D242).
- Muted AI Watch alerts are listed the same way, and closing an AI Watch alert as Approved still decides the agent, service, or MCP server it is about.
- Blocked-call and sensitive-data alerts about a machine where no person was seen now list the machine as a device, so it is shown as the machine, not hidden as a person; when a value may be a person, it is hidden. A mute keeps no device list, so a muted machine shows as "a person" there.
- Each Alerts list, alert view, and close, reopen, or mute answer that includes AI Watch alerts is audited `ai.view_people` when it showed names and `ai.view` when it did not (G3).
- What you will notice: without View people in AI usage, AI watch alerts show "a person" or the machine instead of names, including alerts raised before this update. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing already stored changes; names are hidden when an alert is read. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### AI watch, the AI flow, and a person's timeline hide names without View people in AI usage (2026-11-11)

- On the Dashboard, a viewer without the **View people in AI usage** permission sees the AI Watch cards with machines instead of names: "Most from ws-0042" on the sensitive data card, app consents without who granted them, and new Claude Code agents by their machines. Counts stay the same, and a named view is never served to them from the page cache (ADR-0029 G2, D242).
- In Investigate, the AI flow shows each person as the machine they used most (or "Hidden"), in the People group, with Open in Logs by machine and no "Investigate this"; asking the AI flow for one person answers "Needs View people in AI usage". Devices and addresses with no person are listed as before.
- A person's timeline leaves out Claude sessions, first use of AI services, AI telemetry events, and AI Watch alerts for a viewer without the permission; the rest of the timeline is unchanged.
- Each AI Watch, AI flow, and timeline view is audited `ai.view_people` when it showed names and `ai.view` when it did not, with the surface and the sources (G3).
- What you will notice: without View people in AI usage, AI watch cards on the Dashboard, the AI flow in Investigate, and AI rows on a person's timeline show machines or leave names out. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing stored changes. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Agents and the AI inventory hide names without View people in AI usage (2026-11-11)

- On AI usage and Agents, a viewer without the **View people in AI usage** permission sees each Claude Code agent by its machines ("Claude Code: ws-0042") with no owners, and the AI inventory and its CSV or JSON export list agents the same way. Counts, machines, and exclusions stay the same (ADR-0029 G2, D242).
- A person's Alerts tab works again for everyone: without the permission, AI Watch items are left out of the person filter on `/api/alerts`; other alerts about the person are listed as before (D242, amended 2026-11-11).
- Each agents and inventory view is audited `ai.view_people` when it showed names and `ai.view` when it did not, with the surface, the time range, and the sources (G3).
- What you will notice: without View people in AI usage, agents and the AI inventory show machines instead of owners' names, and a person's Alerts tab works again, without AI watch items. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing stored changes. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### A read during compaction never counts events twice (2026-11-11)

- When a whole merge of small lake files started and finished while a read was listing a day's files, that read could include both the merged file and the files it replaced, so counts and lists on any page could briefly show some events twice. A read now also rechecks the retired list after listing and looks again when it changed.
- What you will notice: nothing visible, except that a rare, brief double count on busy installs no longer happens.
- What changes for existing installs: nothing stored changes; no action needed.

### Agent sessions and Claude accounts hide names without View people in AI usage (2026-11-11)

- On Agents, a viewer without the **View people in AI usage** permission sees each session's person and Claude account as the session's machine (or "Hidden"), and each Claude account as its first device with no OS users, as plain text with no person link. The person filter on Sessions is left out, and a machine is never matched to another account's tier. Counts stay the same (ADR-0029 G2, D242).
- A person's AI activity (`/api/ai/people/{person}/activity`) and the `person` filter on sessions and alerts answer 403 "Needs View people in AI usage" without the permission, before anything is read, audited `access.denied`. The person page's AI use and Alerts tabs say so instead of asking.
- Each sessions, session, accounts, and AI activity view is audited `ai.view_people` when it showed names and `ai.view` when it did not, with the surface, the time range, and the sources (G3). Session step paths can still contain user names (a residual in D242).
- What you will notice: without View people in AI usage, AI sessions and accounts show machines instead of names, and a person's AI activity says "Needs View people in AI usage". Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing stored changes. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### AI usage page hides names without View people in AI usage (2026-11-11)

- On the AI usage page, a viewer without the **View people in AI usage** permission sees each person on the People tab as the machine they used most (or "Hidden" when no record names one), as plain text with no person link. Services list their machines instead of people, and the "may be" hint on network rows is left out. Two people on one machine stay two rows (ADR-0029 G2, D242).
- The server removes the names from its answer, kept apart in the 60-second page cache, so a named answer is never served to a viewer without the permission. Each view is audited `ai.view_people` when it showed names and `ai.view` when it did not, with the surface, the time range, and the sources read (G3).
- What you will notice: analysts and auditors without View people in AI usage see machines instead of names on the AI usage page, with a short note that names are hidden; every count stays the same. Administrators, and anyone an administrator gave the permission, see no change.
- What changes for existing installs: nothing to do and nothing stored changes. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### View people in AI usage permission (2026-11-11)

- Users and access has a new per-user permission, **View people in AI usage**. Administrators always have it. Analysts and Auditors, new and existing, start without it; an administrator turns it on per user, and each change is in the audit log as `admin.change` (ADR-0029 G1, D242).
- Without it, the next updates show the machine or address instead of a person's name on AI pages, or "Hidden" where there is none; counts of people stay. The server removes the names from its answers, not only the page (G2). Views that show names are recorded as `ai.view_people`, others as `ai.view` (G3).
- What you will notice: administrators get a "View people in AI usage" switch per user on the Users page; analysts and auditors will stop seeing names on AI pages as the following updates land, until an administrator turns it on for them.
- What changes for existing installs: nothing to do; the update adds one column to the users table, off for every existing analyst and auditor. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); the column stays and the older release ignores it.

### Handoff after ADR-0050 (2026-11-11)

- `docs/handoff.md` records ADR-0050 as done (#494, #497, #500, #503), decisions D239 to D241, and names ADR-0048 slice 0 as the next item.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Documentation only.

### One message each way for a missing parser; reparse count in the integrity report (2026-11-11)

- A source storing events without its parser no longer also sends the general "Detection stopped" and "Detection running again" messages after 15 minutes. Its own two messages ("Source without its parser" and "Source parser back") cover it, so one outage sends two messages instead of four (D239).
- The integrity report now shows how many files and events were reparsed in its period (D240).
- What you will notice: fewer duplicate alert messages when a parser goes missing; a reparse count in the integrity report.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### The terminal interface no longer errors when closed quickly (2026-11-11)

- In the terminal interface (`app tui`), the source list loads in the background. Closing the window before it arrived could end with an error; a result that arrives after the window is gone is now ignored. This also fixes a test that failed now and then.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Development: the merge queue posts the speed table on every app PR (2026-11-11)

- The merge queue now adds the speed check table to each app PR as a comment, also when no page is flagged, as CLAUDE.md section 9 asks. Before, it posted it only for a flagged page merged with the owner's OK.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. A development script only.

### Rules can run over reparsed events (2026-11-11)

- After a reparse finishes, an administrator can choose "Run rules over the reparsed range" on Sources. The server runs every enabled rule that applies to the source over the events that reparse rewrote, and only those, in the background, and shows the result on the source: matches, rules run, and alerts raised or updated (ADR-0050 row 7, D233). Events stored without an event time are included, and events that parsed normally between two outages are not alerted on again. If a reparse stops before it finishes, the next reparse of the source includes the events the stopped one rewrote, so the rules run over them too; if it had already rewritten the last waiting events, Sources offers the rule run on the stopped reparse itself.
- Matches are stored as normal rule matches and raise alerts the way scheduled rule runs do: an alert already open today for the same rule grows instead of a second one appearing. These alerts carry a "Late" badge on Alerts with the time range of the reparsed events (D241).
- When the run ends, each alert target of a matched rule's schedules gets one "Late detection from reparse" message for the run, listing the rules that matched, their match counts, the source, and the time range of the events. A schedule's targets hear about a rule only when a scheduled run of that schedule would have alerted on these matches: the schedule is not paused, its owner can read the source, and the matches meet its threshold. A rule that runs on no such schedule, or a muted rule, sends nothing (its alert is on Alerts), nothing is sent when nothing matched, and no message is sent twice. Retrying the remaining rules sends one more message only for the rules that matched then.
- If a stopped reparse rewrote some events but others are still waiting, starting the rules says how many: "Reparse the remaining N events first".
- It runs once per reparse: a second start is refused. If a rule cannot run (for example it takes too long), the source lists it with the reason and offers "Run the remaining rules". If the server stops during it, starting it again runs only the rules that had not finished; no match or alert count is added twice.
- Analysts and auditors cannot start it, and the source list shows reparse jobs to administrators only. The start and the result are in the audit log as `source.reparse_rules`, and each rule run as `rule.run`.
- What you will notice: on Sources, after a reparse, an administrator sees "Run rules over the reparsed range", then its matches and alerts; alerts it finds carry a "Late" badge, and the rules' alert targets get one "Late detection from reparse" message.
- What changes for existing installs: nothing to do; the update adds columns to the table of reparse jobs, a table of the events each reparse rewrites, a table of each rule's progress for a reparse, and late-detection columns to alerts. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); matches and alerts already raised stay, and the older release ignores the new columns and tables.

### Server logs follow the current error stream (2026-11-11)

- The server's log lines are written to the error stream as it is at each write, not as it was when logging started. A server is unchanged; tests no longer fail now and then with "I/O operation on closed file" when one test's captured output was closed before another logged.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Stopping the server stops a query that was just starting (2026-11-11)

- When the server stops, it interrupts running queries and waits for them (#490). A query that was just starting could miss that interrupt and keep the stop waiting for up to 10 seconds. The server now repeats the interrupt until every query has stopped.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Events stored without their parser can be reparsed (2026-11-11)

- When a source's template was missing for a while, its events were stored with the basic parser and marked `template_missing`. Once the template loads again, an administrator can now choose "Reparse N events" on Sources. The server parses those events again with the template, in the background, and shows the job's progress and result on the source (ADR-0050 rows 7 and 8, D233).
- Only that source's `template_missing` events inside its retention period change. Each event keeps its event ID, its original line, its time, and its classification; other events are not touched. Files are rewritten the way compaction rewrites them, so a stop or crash mid-job leaves either the old events or the new ones, never both. Each rewrite is recorded in the integrity ledger, and the start and the result are in the audit log as `source.reparse`.
- Analysts and auditors cannot start a reparse. Running the rules over the reparsed time range follows in the next change.
- What ingest adds after the parser stays: a syslog listener event keeps the sender's address as its device IP when the template finds none in the line, and a Loki event keeps its stream labels.
- Loki sources: an event is parsed again from its stored line only; Loki stream labels are not used as parser input, so a field that only a label supplied stays empty.
- Sources reads no event files to decide where to offer a reparse: a source is offered one after its template loads again, until a reparse of it finishes.
- What you will notice: on Sources, an administrator sees "Reparse N events" on a source whose template is back after events were stored without it, then the job's progress and result.
- What changes for existing installs: nothing to do; the update adds a table for reparse jobs and a column to the table of sources storing without their parser. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); events already reparsed stay reparsed, the older release ignores the new table and column, and a source whose template already loaded again may send one more "template loads again" message.

### Tests no longer fail on a slow test machine (2026-11-11)

- Tests that measured elapsed time with tight limits failed on busy CI machines and cost extra runs. Each now checks the shape of the work (how many queries, no list written into the SQL), waits for the event it needs with a generous ceiling, or uses a fixed clock; real slowdowns are caught by the speed check on every app change.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Tests only.

### A source without its parser says so on Health and to alert targets (2026-11-10)

- When a source keeps storing events without its parser (its template is not available), Health and Sources now say which source and which template, and that rules and searches using the template's fields miss those events until they are reparsed. Analysts who read the source see the same words, not "cannot be read right now".
- Every alert target gets one message when it starts ("Source without its parser") and one when the template loads again ("Source parser back"), with how many events were stored without it. Nothing repeats while it lasts, also across restarts. Both are in the audit log (ADR-0050 rows 4 to 6).
- If the outage lasts more than 15 minutes, the general "Detection stopped" and "Detection running again" messages also go out, so four messages in all; whether to leave this case out of them is with the owner.
- What you will notice: a clearer Health message for such a source, and alert messages when it starts and ends (two, or four past 15 minutes).
- What changes for existing installs: nothing to do. The update adds one small table to the settings database. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`); the older release ignores the table.

### Development: the session check fast-forwards main (2026-11-10)

- `scripts/dev/session-check.sh` now fast-forwards a local `main` that is only behind `origin/main` (when it is not checked out elsewhere and has no local changes), so tools never compare against a stale `main`. A `main` with commits of its own is still only reported.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. A development script only.

### Handoff after ADR-0050 slice 1 (2026-11-10)

- `docs/handoff.md` records #492 to #494 and names ADR-0050 slice 2 as the next item.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Documentation only.

### A source whose parser is missing keeps storing its events (2026-11-10)

- Before, a source whose template could not load (a rollback to an older release, a broken edit, a missing file) stopped. A syslog listener or agent source then filled its waiting space and refused new messages, which were lost.
- Now the source keeps storing every event with the basic parser for its format: the original line is kept exactly, time, host, and message are filled where the format allows, and each event is marked `template_missing`, so a search on the template still finds it. CSV files are read without taking any line as a header, so no line is lost; the cells are kept by position. When the template loads again, new events are parsed with it from the next pass (ADR-0050, D233).
- Sources still shows the source as an error ("Storing events without its parser: template ... is not available"), and the "Detection stopped" message still goes out, until the template is back. A clearer Health message and alerts follow in the next part.
- What you will notice: a source with a missing template keeps receiving events instead of stopping; its error on Sources reads "Storing events without its parser".
- What changes for existing installs: nothing to do; no settings change. Events stored while a template was missing keep the `template_missing` mark. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Backlog: DuckDB out-of-memory crash, retest on 2.0.1 (2026-11-10)

- `docs/BACKLOG.md` row 54 records the DuckDB out-of-memory crash findings, what is ruled out, and when to retest and report it upstream.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Documentation only.

### Development: a local patch for a command-hold tool (2026-11-10)

- A development-only patch, kept in `.claude/patches/` (not published), lets cleanup inside throwaway containers and temporary folders run without a confirmation prompt during development sessions.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Development files only.

### Handoff for the next batch (2026-11-10)

- `docs/handoff.md` lists what merged in this batch (#482, #484 to #490), the DuckDB out-of-memory crash findings, and what waits on the owner.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Documentation only.

### The server stops its running queries before it exits (2026-11-10)

- When the server stops, it now stops any query still running and waits for it to close before the process exits. Before, a query left running after another one ran out of memory could make the process end with an abort on the way out (about 1 exit in 10 in a test loop), so a normal stop or restart could be reported as a failure.
- Queries that arrive while the server is stopping are refused with "The server is shutting down".
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do; no data or settings change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### DuckDB 1.5.6 (2026-11-10)

- The query engine moves from DuckDB 1.5.5 to 1.5.6, a patch release. In a 200-run test where a query runs out of memory, the server process crashed in 12% of runs on 1.5.6 against 20.5% on 1.5.5 (Linux arm64); the rest answered with the usual "Out of memory" message. The crash is not fixed upstream yet; this lowers how often it happens. DuckDB 2.0 stays out for now.
- What you will notice: nothing visible.
- What changes for existing installs: the update installs DuckDB 1.5.6 with the other packages; no data or settings change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Development roles kept out of the public repository (2026-11-10)

- CLAUDE.md section 10 imports the development roles and owner checkpoints from `.claude/factory.md` (D238). That file, the development agents and commands (`.claude/`), and design and bug proposals (`docs/proposals/`) are left out of the public repository.
- The publish script now stops if `.claude/` or `docs/proposals/` would be published, so a missing `.gitattributes` line cannot leak them.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Development files only; nothing in the app, data, settings, or update steps changes.

### Slash commands for the development workflow (2026-11-10)

- Five Claude Code commands in `.claude/commands/`: `/next` (session check, handoff, plan the next item), `/review <pr>` (the reviewer agent on a PR), `/report` (merged, failed, needs owner decision, status items closed; 15 lines at most), `/design-pass` and `/bug-hunt` (the designer or tester on the synthetic demo; proposals only).
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Development files only; nothing in the app, data, settings, or update steps changes.

### Reviewer, designer, and tester agents for development (2026-11-10)

- Three Claude Code subagents in `.claude/agents/` for building this project: a reviewer that reads only CLAUDE.md, the PR's ADR or handoff item, and the diff, and posts one ranked comment; a designer and a tester that work only on the synthetic demo and write proposals to `docs/proposals/`. None of them edits code, approves, or merges.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Development files only; nothing in the app, data, settings, or update steps changes.

### Development scripts and tests run on macOS too (2026-11-10)

- The update script (`scripts/update-systemd.sh`) used two Linux-only commands (`find -perm /0111` and `stat -c`); it now uses forms that work on Linux and macOS, with the same result on Linux.
- The speed check reads the server's CPU time through `ps` where `/proc` is missing, so its CPU confirmation works on macOS.
- Tests that need Linux (file names that are not UTF-8, per-thread priority) skip on macOS with the reason; Linux and CI still run them. The out-of-memory test for AI usage also skips on macOS: DuckDB crashes there about 1 run in 3 when that query runs out of memory. The AI usage memory test fixes two threads per query, as a 4 vCPU install gets.
- The merge queue runs the smoke test through the backend's environment (`uv run`), where Playwright is installed, instead of whichever `python3` is first on the path.
- The merge queue marks a draft PR ready with `gh pr ready` (the path it used only worked through the old cloud session) and stamps its push time with GNU or BSD `date`.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. The update script behaves the same on Linux; to go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Server events keep sign-ins, changes, exports, and denials only (2026-11-10)

- The built-in `server_events` source recorded every request that was not a GET, so each search, count, facet, Ask, and Explain became an event. It now records only sign-ins, setup, user and token changes, exports and hand-offs, and admin and settings changes, plus any request that was denied or throttled (401, 403, 429) and any query the safety check blocked (for example ATTACH, read_csv, or COPY). A typo in a query is not recorded.
- Searches and other reads are still in the audit log with the user, as before; only the copy in `server_events` stops.
- A new endpoint has to be listed as recorded or read-only, or a test fails, so a change is never dropped by accident.
- What you will notice: far fewer `server.request` events in Logs for the `server_events` source; searches no longer appear there.
- What changes for existing installs: nothing to do. Events already stored stay; no settings or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### The speed check no longer waits on its own requests (2026-11-10)

- The speed check waits for each server's event count to hold still before timing. Since #469 the server records every changing request in its built-in `server_events` source, and the count query is itself such a request, so on a lake built after #469 the count rose by one every read and never held still. The check now leaves `server_events` out of that count.
- It also never waits silently: a copied lake that is still adding events after 10 minutes (a new lake: 60 minutes) stops the check with the last counts, and while it waits it prints the count once a minute.
- Stopping the check (a timeout or a kill) now stops its two servers too; before, they kept running and took CPU from whatever ran next.
- What you will notice: nothing visible.
- What changes for existing installs: nothing to do. Only a developer script changes; no data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Detection never stops silently (2026-11-10)

- When something that feeds detection stops on its own, your alert targets hear about it: a source or connector that cannot read for 15 minutes, an AI Watch check failing for 15 minutes, a threat feed that cannot update for a day, a schedule that pauses itself, and a failed integrity check. Each sends "Detection stopped" once and "Detection running again" once when it recovers.
- Only real errors count (a failed fetch, a listener that is down, a full spool, a missing parser), never a quiet period or a connector running behind. A source whose spool is full now shows that on Health.
- Something that keeps failing and recovering sends one stop and one recovery message an hour at most, then one "still flapping" message until it settles for an hour.
- Anything with no alert targets of its own now tells every alert target instead of nobody.
- Settings > Backups waits for its saved settings before showing the form, so an edit made while they load is no longer lost (found as a flaky test).
- What you will notice: "Detection stopped", "Detection running again", and "Detection flapping" messages, a "Spool full" error on Health when a spool refuses messages, and schedule pause messages even for schedules with no targets chosen.
- What changes for existing installs: three new settings tables, added on start. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`); the extra tables are ignored by the older version.

### Vendor alert pause messages (2026-11-10)

- When a vendor alert source goes over 100 new alerts an hour, its alert targets now get a short message right away saying alert creation is paused and that High and Critical alerts still raise. The summary with held counts still comes when the pause ends.
- If the source has no alert targets chosen, both messages go to every alert target.
- What you will notice: a "Vendor alerts paused" message when a pause starts and a "Vendor alerts resumed" message when it ends.
- What changes for existing installs: nothing to do. To go back, roll back the update (`update-systemd.sh --rollback`, see `docs/install/`); no data or settings change.

### Template fallback decided, and threat numbers checked (2026-11-10)

- ADR-0050 accepted: a source whose parser template cannot load will keep storing its events, say so on Health, and send one alert; the events can be reparsed later and the rules re-run over them. Built in the next three changes.
- The release tooling now refuses a design record that reuses a threat number another one already owns.
- What you will notice: nothing visible.
- What changes for existing installs: nothing.

### Vendor alerts: a rise after a close opens a new alert, and a starter CEF alert parser (2026-11-10)

- When another security tool resends an alert at a higher severity after you closed it, a new alert opens. It says how the earlier one was closed and links to it; the closed alert and its reason stay as you left them.
- New starter parser "CEF security alerts" for sources that receive only alerts from another security tool in CEF. It is never picked automatically: choose it for the source.
- What you will notice: a closed vendor alert that comes back more severe now shows as a new alert with a "Follows" link, where before nothing appeared.
- What changes for existing installs: nothing to do. The update adds one column to the settings database. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the new column, does not open new alerts for a rise after a close, and does not list the new parser, so pick another parser for a source that used it before rolling back.

### Vendor alerts: an hourly cap and optional messages (2026-11-09)

- A source that sends alerts from another security tool can create up to 100 new alerts an hour. Past that, High and Critical alerts still appear; lower ones are stored and searchable but do not appear as alerts until the hour is back under 100.
- Health and Sources show a source over its cap with how many alerts were held, by severity. Its chosen alert targets get one message when the pause ends, with those counts.
- New: "Vendor alert messages" on such a source. "Notify alert targets" is off by default; when on, new alerts at or above a minimum severity (High unless changed) go to the targets you pick.
- What you will notice: nothing unless a vendor alert source sends more than 100 new alerts in an hour, or an admin turns on its messages.
- What changes for existing installs: nothing to do; messages stay off until an admin turns them on. The update adds four tables to the settings database. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the new tables, raises every vendor alert with no cap, and sends no vendor alert messages; the settings come back if you update again.

### An external alert lists every vendor alert it groups (2026-11-09)

- An alert from another security tool shows how many vendor alerts it groups and the first 50 of their IDs; Show all loads the rest 200 at a time.
- Show alert events lists those alerts' own lines, newest first, read only from the alert's sources and time range.
- A resend or a higher severity on any grouped vendor alert updates the same alert.
- What you will notice: external alerts have a Vendor alerts list and a Show alert events button in their Evidence section.
- What changes for existing installs: nothing to do. The update adds one index to the settings database; to go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the index, and external alerts show their Evidence as before.

### Alerts from other security tools can land in Alerts (2026-11-09)

- A parser template can now mark its source as an alert source (`emits: alerts`, with where the vendor's alert ID and product are). Such a template takes effect only after an admin approves it, like every user template.
- Each alert from that source becomes an item in Alerts within about a minute, with the vendor's title and severity (High or Medium; a low or informational alert has no severity badge and says its level), the person and device it names, and an Open in Search link to the alert's own lines. Alerts about the same person with the same title on the same day add to one item.
- The same alert sent again raises nothing new; sent again at a higher severity, the open item's severity rises.
- An alert line missing its ID, product, time, title, severity, or who or what it is about is still stored and searchable, marked partial, and raises no item. An alert whose own time is more than 7 days old when it arrives is stored but raises no item.
- No starter template uses this yet, and these items send no notifications yet.
- What you will notice: nothing visible until an admin approves a template with `emits: alerts`; after that, its alerts appear in Alerts.
- What changes for existing installs: nothing to do. The update adds one table to the settings database, which an older version ignores; items already raised stay in Alerts. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`), but first, if any template uses `emits: alerts`, remove its `emits:` and `alert:` lines, or do not roll back and roll forward instead. The older version cannot load a template with those lines, and a source set to that template stops: Sources shows "Template ... is not available", file sources are not read until it is fixed, and syslog listener and OTLP sources hold up to 512 MB of waiting messages and then drop new ones. With the lines removed, its events are stored as ordinary events, raw line kept. Sources using the Automatic parser are not affected.

### Sign-ins and changes to this server are searchable in Logs (2026-11-08)

- The built-in `server_events` source now also records successful sign-ins (password and single sign-on) and every request that changes something or exports data: the time, user id and name, client address (through trusted proxies), method, route, status, and duration. Searching an address in Logs answers "who is this", not only the server journal.
- Never recorded: page reads, health polling, static files, ingest pushes, query strings, request bodies, headers, cookies, passwords, or tokens.
- Records are capped at 300 a minute for requests and 300 for sign-ins and refusals together, so a flood cannot fill the disk or crowd out a refused sign-in. The refused-credentials alert still counts refusals only.
- The source stays local-only and admin-only unless an admin adds it to a group. Health and the Dashboard still never call it quiet on a day nobody signs in. In GET /api/sources and GET /api/overview, the `events_on_failure` flag is now `quiet_expected`.
- What you will notice: sign-ins and admin changes to this server can be searched in Logs under the `server_events` source, for example by an address.
- What changes for existing installs: nothing to do; records start with the first sign-in after the update. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version stops writing these records and the ones already stored stay searchable.

### Daily backups by the server (2026-11-08)

- The server now backs up its data folder every day at 02:15 (install time zone) and keeps the last 14, with no cron entry or script. Administrators change the time, the count, or turn it off under Settings, About and licenses, Backups; every change is in the audit log.
- Health has a Backups tab: the last run in your local time (UTC on hover), its result and size, how many are on disk, and the next run. A failed run shows as Unhealthy with the reason.
- With no successful backup for 48 hours, one alert opens on Alerts; the next successful backup closes it.
- Old backups are deleted only after a new one succeeds. A run that would leave the disk nearly full is skipped and shown on Health instead. A restore now leaves the `backups/` folder in place.
- The install guides (backup.md, team-vm.md, single-user.md) say where backups are, how to restore one, what a backup holds, and how a restore and a rollback differ.
- What you will notice: a Backups tab on Health and a Backups section in Settings, About and licenses; backup files appear in the data folder's `backups/` after the first 02:15.
- What changes for existing installs: backups turn on automatically; the first one runs at the next 02:15 after the update, never at once. They use disk space in the data folder (about 14 times one backup); set `APP__BACKUP__DIR` to put them elsewhere, or turn them off in Settings. Your hand-made backups are never deleted. To go back, roll back the update (`docs/install/team-vm.md`, Rolling back, `update-systemd.sh --rollback`): the older version ignores the new settings and leaves the backup files in place for you to keep or delete.

### Plain User-ID lines on the person page, suggested groups for Automatic sources, Logs opens on Filters (2026-11-08)

- Person page, What it did: a Palo Alto User-ID row stored before 2026-11-06 no longer shows the raw CSV line as its subtitle. Any line whose message is a whole delimited record now reads as a plain summary of its parsed fields, for example "Palo Alto Networks User-ID: alice at 192.0.2.20, learned from globalprotect". View in Logs still opens the same rows.
- Settings, Users and access: suggested source groups now cover Automatic sources by the templates that read their lines in the last 30 days, so a firewall or server feed on Automatic is suggested under its category and vendor. The server's own built-in source of refusals is never suggested. Suggestions still grant nothing until an admin approves them.
- Logs opens on the Filters tab. Only a click on a tab is remembered; opening a saved or library search in SQL, Edit as SQL, or a field click in SQL switches the tab for that visit only. A link that names a tab still opens it, and Auditors with SQL turned off still see no editor.
- What you will notice: Logs opens on Filters, User-ID rows on a person page read as a plain sentence, and Users and access suggests groups for your Automatic sources.
- What changes for existing installs: nothing to do. Each browser opens Logs on Filters once, then remembers the tab you click. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### AI service alerts name who used the device, and say why by the service's status (2026-11-08)

- An AI service or MCP server alert that named only a device now shows a Person on device line when the Claude hooks plugin has records from that host in the alert's time range: "erin@example.com, seen on this host in the hooks plugin". Two names that Identities links into one person are shown once, with "(names linked in Identities)".
- When several people used the host in that range, the line says "Possible: erin@example.com or frank@example.com, 2 people seen on this host in the hooks plugin" and picks nobody. These names are not added to the alert's people or counts.
- The names come only from hooks sources you can read; without them you see the device as before.
- "Why it matters" and the next steps now follow the service's status in the AI service catalog today: Not approved, Unreviewed, a service not in the catalog, and Approved (after the alert was raised) each have their own wording. GET /api/alerts adds `review_status` and `device_people` to each alert.
- What you will notice: on an alert such as one for Gemini, the person who used the device when the hooks plugin saw them, and wording that says the service is Not approved.
- What changes for existing installs: nothing to do. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Health and the Dashboard agree on how many sources are healthy (2026-11-08)

- The Sources tile on Health and the Sources line at the bottom of the Dashboard now read one count, worked out once on the server. Before, Health could say "4 of 6 healthy" with two quiet sources while the Dashboard said "6 of 6 flowing, no gaps".
- Both say it in the same words, for example "4 of 6 healthy, 2 quiet: win_dc 2 d, vpn 6 h, no gaps in 24 hours". The count is the one Health already showed: a quiet source (nothing in 24 hours, a quiet alert firing, or an open gap alert) or one with a gap in the last 24 hours is not healthy, and a paused source counts in the total but is never healthy. The Needs you banner is unchanged.
- The built-in source of refused sign-ins and tokens (`server_events`) is expected to be quiet: it is never called quiet and never named as the longest wait. GET /api/sources marks it with `built_in` and `events_on_failure`; GET /api/overview adds a `condition` per source and a `source_summary`.
- What you will notice: the Dashboard's Sources line now says "N of M healthy" and names quiet sources, matching Health.
- What changes for existing installs: nothing to do. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### AI usage counts Windows DNS lookups and each hook record once (2026-11-08)

- Windows DNS, Unbound, and PowerDNS put the looked-up name in `message`, which AI usage did not read, so their lookups of AI services were missed. AI usage, AI Watch, and the AI parts of People & devices and the top bar lookup now read it on DNS events. A name kept in the extra fields still comes first.
- Finding AI service lookups no longer reads the extra fields of sign-ins (Windows sign-ins carry about 1.5 KB each), and parses those fields only when they hold a host. On a synthetic day of 1.36 million sign-ins and 814,500 Windows DNS queries, today's AI check went from about 2.7 s to 1.6 s while now reading the DNS lookups.
- AI usage, People: a hook record the plugin sent twice counts once, as on Agents and Sessions. People seen only through the hooks plugin show for Last 7 days with or without the AI rollup built (tests added).
- What you will notice: Windows DNS lookups of AI services now count in AI usage; tool call counts in People no longer double for a record the plugin resent.
- What changes for existing installs: nothing to do. Days the AI rollup already built keep their counts until those days change; new days and today include Windows DNS lookups. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### People & devices opens faster on large installs (2026-11-08)

- People & devices no longer reads the extra fields of every sign-in. Windows sign-ins carry about 1.5 KB of fields with no column of their own; two checks read them for every sign-in in the range: the test record check in who counts as a person (a test record names no one, and every row there names someone) and the Claude Code hook fields in the ranking (now read from hook rows alone).
- On a synthetic week of 1.9 million sign-ins and 5.7 million DNS queries, the page's server time went from about 7.9 s to 1.4 s, and its server CPU from about 15 s to 2.4 s. The ranking, scores, and Identities scoping are unchanged.
- The speed check can add the same real-shaped week to its lake (`--real-shape`, off by default).
- What you will notice: People & devices opens much faster on large installs.
- What changes for existing installs: nothing to do. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### Ask answers library questions without waiting for the model (2026-11-08)

- Ask now matches a question to the library in code first. When one library query is a confident match (its own example question, in the same words once synonyms, time words, and the people, addresses, and machines named are set aside), it answers with no model call. Before, every first question waited on a routing call to the model, about 25 s on a CPU-only local model.
- Every other question goes to the model exactly as before: a near miss, a question shaped like general guidance ("how do I", "what is"), and a library query that takes its own values.
- How I got this says "A data question, matched to the library without the model" for these answers.
- The Ask audit row's route now records which route answered (`via`: `library` or `model`, with the library entry when one was used) and how long routing took (`ms`), so the two can be compared later. A library answer is audited as an Ask with no model call.
- What you will notice: library questions in Ask answer in a couple of seconds, without waiting for the model.
- What changes for existing installs: nothing to do. No data, settings, or update steps change; the audit row details gain two fields. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).

### The app's own lists are built on the server (2026-11-08)

- The person page's sign-ins, the Microsoft 365 Sign-ins, Mail, Apps, and Admin lists, and the Sources page's event counts and parser mix no longer send SQL from the browser to the query endpoint. They call their own endpoints (`/api/people/{person}/signins`, `/api/m365/list`, `/api/sources/event-counts`, `/api/sources/parser-mix`), which build the SQL on the server and run it on your own sources, through the same guard, and audited as `query.view` with the list's name.
- These lists are display, like the dashboards, so they keep working for Auditors whatever the SQL setting for Auditors says.
- What you will notice: nothing visible.
- What changes for existing installs: the audit log shows `query.view` rows with a view name for these lists instead of `query.run` rows with their SQL. No data or settings change.

### Roll back a systemd install with one command (2026-11-08)

- `sudo sh /opt/remnant/scripts/update-systemd.sh --rollback` puts a systemd install back on the version it ran before the last update: it stops the service, checks that commit out, rebuilds the web UI and Python packages, starts the service, and prints the startup lines. It goes back one update only, and refuses with nothing changed when no previous version is recorded or tracked files were edited by hand. The next ordinary update rolls forward.
- Every successful update now keeps the commit it replaced in `previous_commit` next to `installed_commit`, written by root under the same rules.
- An older version started on a database a newer version migrated logs `meta.schema_newer` and leaves the newer tables and columns alone. A source of a kind this version does not know is skipped with a warning instead of stopping ingest for every source, and keeps its retention.
- The install guides have Rolling back sections for systemd, Docker Compose, and single-user installs, with what happens to data and migrations.
- What you will notice: nothing visible.
- What changes for existing installs: the update after this one records the first rollback target, in `previous_commit` in the data folder (the update that installs this version runs the old script). AIDE checks treat that file and `rolled_back_from` like `installed_commit`.

### Dashboard, AI Watch, Agents, and AI usage numbers count what they say (2026-11-08)

- Detections leads with matched events, each event once, and states rule matches below it ("466 events", "747 rule matches"), per D221. Opening the number, a rule's row, or hosts and users involved in Logs limits each rule to the sources it matched on, so Logs shows the rows that were counted.
- AI Watch "24 hours" is now the last 24 hours ending now, not the day since local midnight (D221). 7 and 30 days still count whole days in your time zone.
- Clicking a day on the AI Watch chart opens that day in your time zone, the day the bar counts, not the UTC day.
- "New agents and MCP servers" counts agents and MCP servers first seen in the window, whether or not an alert was raised for them.
- Agents > Overview counts Claude Code telemetry and the MCP inventory as well as the hooks plugin: sessions and tool calls a session reports through both are counted once, people include the MCP inventory, and MCP servers not approved include those only telemetry or the inventory reported.
- AI usage > People shows "No cost data" for cost and tokens when Claude Code telemetry arrived without cost or token metrics, instead of 0.00 and 0.
- Times in Logs, Microsoft 365, and other results tables, the Logs "Last run" line, and Live read in your time zone with the UTC time on hover. Log tables keep the seconds.
- The Ask AI headline reads times in your time zone and uses plain column names ("user", "source IP").
- Dashboard and AI Watch number labels wrap to two lines instead of being cut off at narrower widths.
- Rule runs, the page rollups on Health, and the Integrity check time read in your time zone. Integrity says "Nothing verified yet" when a check found no lake files, instead of "Verified".
- Ask AI says when the question's own time ("this week") is used instead of the time range picker.
- AI usage says "1 service and 1 MCP server not approved in use" instead of adding the two together.
- The Expired sign-ins series on Microsoft 365 uses a new neutral chart color with at least 3:1 contrast in both themes.
- The investigation graph shows an activity's own line when it never varies ("Office 365 Exchange Online"), and the number-masked pattern only when its lines differ.
- What you will notice: Dashboard, AI Watch, and Agents numbers match what opens in Logs, and times read in your time zone everywhere.
- What changes for existing installs: no data or settings change. Some numbers change on upgrade because they now count as labelled: Detections' headline is lower (distinct events), AI Watch over 24 hours can be higher just after midnight, Agents > Overview can be higher, and the new agents card can differ from the alerts list.

### Auditors run no SQL until an admin allows it (2026-11-08)

- An Auditor reviews the audit log, dashboards, and reports. Logs (SQL, live search, and the field counts), export of query results, saved-search runs, Ask, the CLI `query`, and the MCP server now refuse an Auditor with a plain message (D220).
- New setting **Let Auditors run SQL** in Settings > Users and access, admins only, off by default. Each change is recorded in the audit log as `settings.auditor_sql` with who made it. When on, an Auditor searches only the sources their groups grant, through the same guard as anyone.
- For an Auditor with the setting off, Logs shows the reason instead of the editor, Ask is hidden, and Run is turned off on Saved searches.
- What you will notice: an Auditor no longer sees the SQL editor, Ask, or Run on saved searches until an admin turns on Let Auditors run SQL.
- What changes for existing installs: Auditors lose SQL until an admin turns the setting on.

### Query connections can read only the files a query needs (2026-11-08)

- Every query from Logs, Search, saved and scheduled searches, exports, Ask, and MCP now runs on a connection that may open only the exact lake and rollup files its views read. No new file can be written in the lake, the rollups, or anywhere else, even by SQL that got past the query check.
- DuckDB's own parser now checks that a query is a single SELECT before it runs, as a second check after the existing one.
- Extensions are no longer installed or loaded on demand by a query, and persistent secrets are off.
- Queries using `json_execute_serialized_sql`, `json_serialize_sql`, `parquet_kv_metadata` or another `parquet_*` function, or `load_aws_credentials` are refused.
- What you will notice: nothing visible; searches and pages work as before.
- What changes for existing installs: nothing to do. A saved search or Ask query that used one of the functions above now fails with "Function not allowed"; query speed is unchanged.

### Trusted certificate list updated (2026-11-08)

- The bundled list of trusted certificate authorities (`certifi`) moves to 2026.10.23, which drops a root whose revoked intermediates had compromised keys (PYSEC-2026-4320). Outbound HTTPS (feeds, connectors, alert targets, AI providers) no longer trusts it.
- The CI exception for that advisory is removed, and Dependabot now opens grouped security updates, still held to the 14-day minimum age.
- What you will notice: nothing visible.
- What changes for existing installs: update to pick up the new certificate list; nothing to configure.

### Security fix: the Identities alias map could be read by anyone who can run SQL (2026-11-08)

- What was exposed: the list of accounts an administrator linked to each person in Identities (for example a person's personal email address) and the organization email domains. Any signed-in user, any API or CLI token, and any MCP token could read them by writing SQL that names the values the server binds for `{{person:...}}` and `{{org_domains}}` (`$id_from`, `$id_to`, `$id_org`), whatever sources they were allowed to read. Investigate's person pages also listed every linked account of a person in their "open in Search" SQL.
- Who is affected: installs that use Identities (linked accounts or organization domains). Installs with the MCP server turned on should update first, since an outside assistant holding a token could read the map. Any analyst could also reach it from Logs SQL, a saved or scheduled search, export, an Ask answer, or the CLI.
- What changes: SQL may no longer name those values (`$id_...`, `{{id_org}}`, `{{id_from}}`, `{{id_to}}`); it is refused with a plain message, including saved searches that already hold it, which now fail when they run. `{{person:...}}`, `{{org_domains}}`, Investigate, and Ask use only the links whose accounts appear in the caller's own sources for the range, so someone who cannot read a source no longer sees a person grouped with an account from it (D219). The same holds for the person page's timeline, hosts and devices, AI activity, Claude sessions, and alerts, and for names on AI usage, which also no longer show a person in an organization domain the viewer's events do not show. Administrators get the whole map, as the Identities page shows it to them; every other role is scoped, including an analyst who holds every source group (D223).
- The check of which accounts the caller's sources show runs once per user, sources, and range and is kept for a minute, so a page that asks several times (the person page) pays for it once; an account seen only in the first or last minute of the range, or first seen in the last minute, may show as its own person until the next check. A search using only `{{org_domains}}` (no `{{person:...}}`) runs again; it failed with "excess parameters id_from, id_to".
- To check whether it was used: the audit log keeps the SQL of every query, export, saved search run, and MCP call; search its details for `$id_` or `id_from`.
- What you will notice: administrators notice nothing; other users notice nothing visible unless a person's accounts span sources they cannot read, in which case that person shows as separate accounts to them.
- What changes for existing installs: update; saved or scheduled searches that name `$id_...` stop running and need rewriting with `{{person:<column>}}`; a person may show as separate accounts to a user who cannot read every source their accounts are in.

### Host pages match Proxmox guests by name only when the name is unique (2026-11-07)

- A host page shows a Proxmox guest by its name only when exactly one guest has that name, and labels it "matched by name". When several guests share the name, they are all listed as possible matches and none is picked.
- Common default names (localhost, debian, ubuntu, pve and similar, also with a number such as debian-12) never match a guest by name alone. IP and MAC matches are unchanged.
- What changes for existing installs: a host whose name several guests share, or a default name, no longer shows a single guest as its match.

### Closed-by-rule-change alerts say why (2026-11-07)

- An alert closed as "Superseded by rule change" on upgrade now says why in its note: "built-in Claude Code tools no longer raise an alert when they change", "quiet alerts off for this source", or "this source was removed".
- What changes for existing installs: alerts closed this way from now on carry the reason; ones closed before keep the short note.

### Which Proxmox guest an address is, and why an address has no events (2026-11-07)

- The top bar search, IP and host pages, and People and devices name the Proxmox guest behind an exact IP, MAC, or host name: "Proxmox VM 104 build-runner on pve2", with first and last seen and Show events. An address two guests held at different times shows both.
- When an address has no events, the top bar, its IP page, and an empty Ask answer that names it say what was searched, category by category: "DNS (2 sources): no lookups by this address", which sources were not receiving or are turned off, which kinds of source you have none of, whether it is in the Proxmox inventory, and Add a source for administrators. Written by the app from your sources' settings and health, never by the AI model.
- Only sources you may read are searched or named; others get one line, "Sources you don't have access to were not searched."
- What changes for existing installs: nothing to do; the lines appear where they apply, and the inventory line needs a Proxmox source.

### People and devices loads faster (2026-11-07)

- People and devices loads faster. The signals behind the ranking no longer test every event's address in Python: events are counted per user, address, and host in one pass, the signals are read only from sign-ins, hook events, and consents, and "internal" is decided in SQL once per distinct address of a failed sign-in. Rankings, scores, and their order are unchanged. On a 2 vCPU test server with 30 days and 7.3 million events (DNS, firewall traffic with probes from many outside addresses, sign-ins with a password spray, Claude Code hooks), median of 3 loads:

  | Server-Timing part | Before (ms) | After (ms) |
  |---|---:|---:|
  | signals_seen | 18,496 | 1,755 |
  | signals_mail_rules | 34 | 28 |
  | signals_new_mcp | 68 | 68 |
  | signals_unreviewed_ai | 493 | 502 |
  | people_split | 327 | 371 |
  | people_attackers | 128 | 138 |
  | scoring | 5 | 4 |
  | audit | 4 | 4 |
  | db | 19,374 | 2,636 |
  | app | 570 | 65 |
  | total | 19,944 | 2,930 |

- What changes for existing installs: nothing to do; the page reads the same data and the Internal networks list in Settings > Enrichment, only faster.

### Proxmox guest inventory source (2026-11-06)

- New source kind **Proxmox VE**: reads which VMs and containers exist, their node, status, tags, MACs, and IP addresses, with a read-only PVEAuditor API token. Setup: `docs/install/proxmox.md`. Verified on Proxmox 8 and 9: pending.
- A token that can do more than read (for example `Sys.Modify` or `VM.Allocate`) is refused when the source is saved, when its token is replaced, and on every poll. The certificate is always checked; a self-signed cluster CA can be pinned.
- Each event is the connector's own short record, never Proxmox's response: guest descriptions, notes, and cloud-init settings (user, password, SSH keys) are never stored or logged.
- Events are written only when a guest appears, changes, or disappears, plus one heartbeat per guest a day. On Proxmox 8, VM addresses come from the config only and Sources says "Agent IPs not available with this token".
- New starter template `proxmox_inventory`, category Inventory.
- What changes for existing installs: nothing until a Proxmox source is added; the database gains the `proxmox` source kind on upgrade.

### Import SigmaHQ core rules (2026-11-07)

- Detection rules has an **Import SigmaHQ core rules** button for administrators. It downloads the SigmaHQ core rule package for the release pinned in the app (`r2026-07-01`) from GitHub, only when you click, and imports it only if its SHA-256 matches. Without internet access, upload the same `sigma_core.zip` instead.
- Imported rules start disabled and show up under **Recommended rules for your sources** when one of your sources would run them. Importing the same release again adds nothing and keeps rules you enabled.
- A broken rule file in a package or folder is skipped with its reason instead of stopping the import; the result counts rules imported, skipped, and not compiling.
- What changes for existing installs: nothing until an administrator clicks the button or uploads a package; no rules are fetched on start-up or on a schedule.

### Hooks records not delivered: idle machines apart from stuck ones (2026-11-06)

- A machine whose Claude hooks plugin holds records and has delivered none for 3 days is now told apart by whether it still sends anything else. If it still sends other telemetry (Claude Code OpenTelemetry, the MCP inventory), the plugin cannot reach the server: Health shows it as unhealthy and a medium "Claude hooks records not delivered" alert is raised. If it sends nothing at all, the machine looks idle or offline: Health shows it as attention with the records waiting and the last contact, and no alert is raised.
- The alert says how many records are waiting, or that the plugin does not report its queue, and when the machine was last in contact, by hooks and by other telemetry. A plugin that does not report its queue now raises the alert too, when the machine keeps sending other telemetry and no hook record arrives.
- What changes for existing installs: idle or offline machines no longer raise new alerts, and their Health state moves from unhealthy to attention. Alerts already open stay until closed.

### Alerts that current rules no longer raise close on upgrade (2026-11-06)

- On the first start after this upgrade, the server checks every open alert against the current rules and closes the ones they would no longer raise, with the reason "Superseded by rule change". Today that is two kinds: "AI agent changed" alerts about built-in Claude Code tools only (built-in tools no longer raise "changed", ADR-0043), and source gap alerts for a source that was removed or whose Alert if quiet is off.
- Alerts the current rules would still raise stay open, and so does any alert someone already acted on (reopened, or with a note). The check runs once per version and never again on its own.
- To see which alerts were closed: Alerts > Closed shows the reason "Superseded by rule change" on each, with the closing in its history; Audit lists one `alert.close` row per alert with reason `superseded` and no user. Any of them can be reopened.
- What changes for existing installs: on the next start, open alerts from retired rules close by themselves, each with an audit row; nothing to do unless you want to reopen one.

### People and devices says it is loading, and where the time goes (2026-11-06)

- While People and devices loads, its tabs show no counts (no more "Users (0)") and the table area says it is counting, with a progress bar; the counts appear when the ranking arrives.
- The page's response carries a Server-Timing header with a named time for each part of the load (signals, rule matches, the people split, enrichment, identities, audit), so the browser's network panel shows what is slow. Only fixed names and durations, never data.
- What changes for existing installs: nothing to set up.

### The Sources line agrees with the gap alerts (2026-11-06)

- The Sources line at the bottom of the Dashboard and the Sources tile on Health now count every source with an open source gap alert, from the same state the alerts use. Before, they could say "6 of 6 flowing, no gaps" while two gap alerts were open and a source had sent nothing for days.
- When gaps are open the line names them, for example "4 of 6 flowing, 2 gaps: server_events quiet 4 d, win_dc quiet 3 h", and opens those alerts (the one alert when there is one).
- A gap alert stays counted after its source's quiet alert is turned off, until the source sends again or someone closes the alert.
- What changes for existing installs: nothing to do; open source gap alerts show on the Dashboard and Health at once.

### AI service alerts name the device and its address (2026-11-06)

- An "AI service not approved" or "not reviewed" alert with no person attached now names each device by its host name and the address it was seen at ("ws-0101 at 10.20.1.5"), or says "no host name seen" when only the address is known. The host name comes from the event itself or from who held the address at the time (DHCP, logons).
- On Alerts, host names open the host page and addresses open the IP page, each on its own row (Devices, Addresses). Before this, an address showed under Devices and opened as a host.
- What changes for existing installs: open AI service alerts pick up the device and address on the next hourly review; closed alerts stay as they were.

### Person page sign-ins in local time (2026-11-06)

- The Sign-ins table on a person's page shows times in your time zone with the UTC time on hover, as Ask results and the rest of the app do, instead of raw UTC stamps.
- What changes for existing installs: nothing to set up; Logs keeps its UTC stamps.

### Plain names for User-ID activities (2026-11-06)

- Palo Alto User-ID lines now read as "User-ID login", "User-ID logout", "User-ID tag registered", or "User-ID tag removed" in messages and on the person page's "How it connects" lanes, instead of the CSV line with its digits masked. The data source name moves to unmapped.
- An activity whose lines carry no message, or a message that is a whole delimited record, is named by its template (or its event class) on the investigator graph, and its card still opens a search for exactly those lines.
- What changes for existing installs: User-ID events ingested from now on get the plain message (template 1.2.0); events already in the lake keep their stored message, and the graph names them by template where that message was the raw record.

### One severity per alert (2026-11-06)

- An alert now has one severity, stored on the alert, and every place reads that one value: Needs attention on the Dashboard, the Alerts list, its detail pane, the "Open by severity" counts, and the messages sent to alert targets. Before, source gap alerts showed High on the Dashboard while the Alerts page showed Medium or no severity and its counts said "High 0".
- Messages to Slack, Teams, email, and webhooks name the severity of a source gap alert; webhooks get a `severity` field when the alert has one.
- What changes for existing installs: on the next start, source gap alerts saved without a severity get Medium, the severity source gaps carry today, and the Dashboard shows source gap alerts as Medium.

### People and devices lists sprayed usernames apart (2026-11-06)

- Users now lists only accounts with a successful sign-in, a Microsoft 365 identity, or an Identities link. Names that were only ever tried in failed sign-ins (root, ubuntu, oracle, and the like) move to a new Targeted usernames tab with the attempts, sources, top attacking countries and networks (when GeoIP enrichment is on), and the hosts they were tried on.
- A targeted name that later signs in successfully moves back to Users.
- What changes for existing installs: brute-force usernames leave the Users tab and appear under Targeted usernames; nothing to set up.

### Recommended rules for your sources (2026-11-06)

- Detection rules has a new Recommended rules for your sources list: imported rules that are off, still compile, and would run on a source you can read, with their level, log source, the sources they would run on, and ATT&CK tags.
- Nothing is turned on for you. An administrator clicks Enable on a rule, or selects several, and the change is audited like any other rule enable. Sources you cannot read never add a recommendation.
- What changes for existing installs: nothing until an administrator enables a recommended rule; rules already enabled are not listed.

### Release notes and decisions: one file per change (2026-11-05)

- Each change now adds its own release note file (`docs/release-notes.d/`) and, for a decision, its own row file (`docs/decisions.d/`). `scripts/docs/assemble.py` writes them into this page and the SPEC decisions log, so changes no longer edit the same lines. The page reads as before.
- What changes for existing installs: nothing to do.

### MCP: saved and library queries run as written (2026-11-04)

- `run_query` on the MCP server fills `{{start}}`, `{{end}}`, `{{org_domains}}`, and `{{person:...}}` the way Logs, saved searches, schedules, and Ask do, so "Who uses Claude Code" gives the same people there. Any other `{{name}}` is refused with a reason.
- `local_only` still applies: with the MCP endpoint not marked local, the Claude Code rows, and so the people and accounts, are withheld.
- What changes for existing installs: nothing to do.

### Logs: the Filters button says Run (2026-11-04)

- The button that runs a search in Logs Filters mode now says **Run**, so "Search" names nothing on that page. The README describes Logs (Filters, SQL) and Ask AI.
- What changes for existing installs: nothing to do.

### Logs and Ask AI: one name per thing (2026-11-04)

- **Search** is now **Logs** in the left nav and the Investigate tabs, at `/investigate/logs`. Its modes are **Filters** (what the Search tab was) and **SQL**.
- **Ask** is now **Ask AI**, its own page at `/ask-ai`, no longer a tab inside Logs. It has its own time range and source filter. The Ctrl+K panel is titled Ask AI too.
- Each answer keeps **How I got this** and now shows **Open in Logs**, which opens the answer's SQL in the Logs SQL mode with the same time range and sources. It replaces Edit as SQL. Saving it there keeps your question as the saved search's origin.
- Buttons and links that said "Open in Search" now say "Open in Logs". In the command palette, "search" and "ask" still find Logs and Ask AI.
- What changes for existing installs: nothing to do. Old addresses (`/search`, `/investigate/search`, `/ask`) and bookmarks open the new pages with the same search, and recent searches still open. A browser that last used the Ask tab opens Logs on Filters.

### Ask: people, not accounts (2026-11-04)

- **Who uses Claude Code** counts people: accounts linked to the same person in **Identities** are one row, with an **accounts** column ("dana@example.com (work), dana@example.org (personal)"), and the answer reads "1 person, 2 accounts".
- A personal account counts as the same person only after an administrator links it in Identities; nothing is linked by a similar name. A session with no account shows "(no account reported)" and is not counted as a person.
- Saved and library searches can use `{{person:actor_user_name}}` and `{{org_domains}}`, filled from Identities each time they run.
- What changes for existing installs: link a person's personal Claude account to them in **Identities** to count it as theirs. A saved search with a parameter named `org_domains` must rename it.

### Ask: times in your time zone (2026-11-04)

- Times in Ask results show in your time zone, as on every other page ("Oct 21, 9:05 AM"), with the UTC time when you hover. The answer's headline uses your time zone too.
- What changes for existing installs: nothing to do.

### Test records are left out of Claude Code counts (2026-11-04)

- The installer's doctor check and **Send a test record** no longer count as a person with a blank name. They are left out of the AI agents library (for example "Who uses Claude Code"), AI usage, Agents, Sessions, and AI watch alerts. Health still shows that they arrived.
- A record counts as a test only when it is marked as one and names no person and no machine, so a real session cannot be hidden by marking it.
- What changes for existing installs: nothing to do; test records already stored drop out of the counts on the next page load.

### AIDE: the check uses the current rules (2026-11-04)

- `update-systemd.sh --aide` writes `/etc/aide/aide.conf.d/90_aide_remnant` before it checks, not after. Rules left by an older update had no spool rule, so the check flagged `/var/lib/remnant/spool/...` and stopped before the new rules could be written; that repeated on every run.
- What changes for existing installs: the update that brings this fix still runs the script already installed, so its check can flag the spool once more. Write the current rules first, then update: `sudo sh -c 'sh /opt/remnant/scripts/update-systemd.sh --print-aide-rules > /etc/aide/aide.conf.d/90_aide_remnant'`, then `sudo sh /opt/remnant/scripts/update-systemd.sh --aide`. If the printed rules have no `spool` line, the install is older than the spool rule: review the check's list, and if it shows only the spool, run `--aide-accept` once.

### Alerts page: summary, filters, and the alert beside the list (2026-11-03)

- **Alerts** uses the full width: a summary of open alerts (by severity, new today, the oldest still open, by category), filters for severity, category, and a person, device, or source, and the list with the open alert beside it.
- The alert shows what fired, why it matters, who and which devices it is about (linked to their pages), its changes today, Show events, next steps for its rule, and Close, Mute similar for 7 or 30 days, or Reopen.
- Select several alerts to close them with one reason.
- What changes for existing installs: nothing to do.

### Plainer close reasons, Approved, and bulk close (2026-11-03)

- Close an alert as **Expected**, **Approved**, **False positive** (with a note), or **Resolved**. Alerts closed before keep their decision and read as the nearest new reason (True positive and Needs follow-up as Resolved, Benign as Expected).
- **Approved** also marks what the alert is about as reviewed: the AI service or MCP server (administrators), or the agent, whose other open alerts close with it.
- Mute similar alerts for 7 or 30 days. Close several alerts at once with one reason; each is audited on its own.
- What changes for existing installs: nothing to do.

### Fewer, grouped alerts for AI agents (2026-11-03)

- One open alert per agent, rule, and day (the install's time zone). Repeats update that alert's count and list of changes instead of adding new alerts, and a message goes out only when the alert is new or gets more severe.
- A source that stops, sends again, and stops again the same day notifies again only if it was back at least 15 minutes, and at most 3 times a day; after that its alert keeps counting and its title says "flapping".
- A new agent is announced once. For its first 14 days its "changed" alerts stay quiet while it learns its usual tools; a new MCP server or MCP tool still alerts.
- Claude Code's own tools (any tool not named `mcp__...`) never raise "changed". New ones arrive with Claude Code updates and show on Agents.
- New: a personal Claude account on a company device (medium, once per account and device) and 10 or more blocked or failed tool calls in an hour for one agent (high).
- What changes for existing installs: on the first start, open duplicate alerts from before are merged into the oldest one of each group; each merge is audited and the others close as Merged. New settings: `agents.learning_days` (14), `agents.blocked_burst` (10), `sources.gap_renotify_min_back` (15 minutes), and `sources.gap_max_notify_per_day` (3).
- What changes for existing installs: on the first start, open duplicate alerts from before are merged into the oldest one of each group; each merge is audited and the others close as Merged. New settings: `agents.learning_days` (14) and `agents.blocked_burst` (10).

### The menu shows where you are (2026-11-03)

- In the left menu, sub-pages hang on a thin line, and the page you are on has a short blue bar beside it and a bolder label, instead of a filled box.
- When you fold a section, the bar moves to the section's own row, so you can still tell where you are.
- What changes for existing installs: nothing to do.

### People and devices lists everyone, with the score explained (2026-11-03)

- **Investigate > People & devices** lists every user, IP address, and host seen in the range, not only those a detection rule matched. Ties go to the busier one, so the list is never empty while there is data.
- The score now also counts failed sign-ins, risky inbox rules and app consents (Microsoft 365), AI watch flags (personal Claude account, unreviewed AI service, new MCP server, blocked tool calls), attack hits from outside, and alerts about them. Each has its own column; hover a score to see its parts.
- What changes for existing installs: nothing to do. Rankings may change order now that more signals count.

### One page per person (2026-11-03)

- A person's page in Investigate has five tabs: **Identity and M365** (summary, connections, and Microsoft 365 sign-ins), **AI use**, **Hosts and devices**, **Alerts**, and **Timeline**. AI usage, Agents, and People and devices all open this page.
- **Hosts and devices** lists the hosts and source addresses on the person's records, with events, failed sign-ins, and last seen. Each opens its own page.
- The separate Sessions and Sign-ins tabs are gone: Claude sessions are under AI use and sign-ins under Identity and M365.
- What changes for existing installs: nothing to do.

### Ask answers questions about AI agents from the library (2026-11-03)

- A new library pack, **AI agents**, answers common questions about Claude Code and Cowork without a model: who uses it and on which machines, the tools, files, commands, web domains, and MCP servers each person's agent used, personal or unconfirmed Claude accounts by machine, tool calls that got no result, and one person's sessions.
- Ask treats Claude Code, Claude, coding agent, AI agent, and Cowork as the same thing, and "what is dana accessing" finds files, commands, and web domains.
- Questions the library cannot answer go to the model, which now knows where the agent's tool, path, command, web host, and account fields are kept.
- What changes for existing installs: nothing to do. The pack's queries appear in the library once the hooks plugin sends data.

### AI activity on each person's page (2026-11-03)

- Investigate's person page has an **AI use** tab: flags first (personal Claude account, blocked or failed tool calls, files written outside the session's folder, shell commands, a new MCP server), then the person's Claude accounts and devices, AI services seen on the network, Claude Code sessions newest first with a one-line summary, and what the agent used in the range: tools, files written or edited, commands, web domains, and MCP servers.
- Any person named on AI usage or Agents opens this tab.
- Metadata only, as before: no prompt text or tool content.
- What changes for existing installs: nothing to do.

### Session rows say what each session did (2026-11-03)

- Each row in **Agents > Sessions** shows how long the session ran, its prompts, tool calls, files touched, web domains, and its three most used tools.
- Badges flag a blocked or failed call, a personal Claude account, and a new MCP server.
- Filter the list by person, machine, tool, or sessions with flags.
- What changes for existing installs: nothing to do.

### AI usage > People says "Not reported" instead of zero (2026-11-03)

- Cost and tokens read "Not reported" for people whose Claude Code sends no telemetry, instead of 0.00 and 0.
- People seen only on the network (DNS, firewall, or proxy) show the Claude services, lookups, devices, and last seen the network gives, instead of empty columns.
- A network name not linked to a person reads "Unmatched", names the person it may be, and has a link that opens Identities with the alias filled in, so one click and a save merges them.
- What changes for existing installs: nothing to do.

### No more pause at the UTC day change (2026-11-03)

- At 00:00 UTC (4 PM Pacific), while the previous day's summaries were built, every page could pause for several seconds. Signing each request in now has its own threads, so it never waits behind slow page queries.
- The server log warns (`pool.wait`) when a request waits more than 2 seconds for a worker, with the request, how long it waited, and the jobs that were keeping the workers busy at the 2-second mark. The rollup log lines now give their start time, duration, and rows read.
- What changes for existing installs: nothing to do.

### Dashboard no longer fails after you have used Search (2026-11-03)

- Opening the Dashboard after Search could show "could not be shown" with an error id, because both pages kept a different list of sources under the same name in the browser. They no longer share it, and Dashboard sections now show what they can even when a response is missing some of its lists.
- What changes for existing installs: nothing to do.

### A failed Ask answer no longer shows unrelated rows (2026-11-03)

- When Ask cannot answer (a model error, its output limit, or a query that does not pass the check), the page now shows only the error and **Try again**. Rows from an earlier search no longer appear under the failed question.
- When the model stops at its output limit while thinking, administrators get **Set Thinking to Off**, which opens that provider's settings.
- What changes for existing installs: nothing to do.

### Ask understands logins, Microsoft, and other usual names (2026-11-03)

- Ask now treats logins, log-ins, sign-ins, and authentications as the same thing, and Microsoft, M365, Office 365, O365, Entra, and Azure AD as Microsoft 365 (also Palo Alto, PAN, and firewall; VPN and GlobalProtect). A question such as "how many failed logins to Microsoft today?" now finds the tested library query instead of going to the model.
- What changes for existing installs: nothing to do.

### Session timelines read by turn (2026-11-03)

- A Claude Code session's timeline now shows each prompt with the tool calls it led to underneath, each with its result, then how the turn ended. A call with no result says "No result (blocked, interrupted, or still running)".
- "Turn end" rows are gone, **Around** shows when you point at or tab to a row, and times are in your time zone with UTC on hover.
- What changes for existing installs: nothing to do.

### Claude Code bookkeeping no longer counts as a tool (2026-11-03)

- Claude Code's own bookkeeping calls (such as a subagent handing back its result) no longer show as a new tool on Agents or in tool counts. They still appear in a session's timeline.
- What changes for existing installs: nothing to do. Tool counts for past days may drop slightly.

### Agents show every machine a person used (2026-11-03)

- On **Agents**, Claude Code for a person now lists every machine it ran on, newest first, each with its own last seen and events. Activity on a second machine no longer shows under the first machine's name.
- What changes for existing installs: nothing to do. Agent alert titles name the person and machines, so an open agent alert may get a new title on its next update.

### AI Watch and Dashboard sections no longer fail during compaction (2026-11-03)

- Compaction, which merges small log files every hour, now keeps the files it replaces for 30 minutes before deleting them. A search or background check that had already started reading them finishes normally instead of failing with "Cannot open file". This was the cause of AI Watch failing every hour on busy sources, and of Dashboard sections such as Attacks and access failing to load.
- A read no longer counts events twice for a moment while a merge is finishing.
- The integrity ledger records each removal when the file is actually deleted.
- What changes for existing installs: nothing to do. Day folders get a small `_retired.json` file while replaced files wait to be deleted.

### AI Watch says "not yet approved" (2026-11-03)

- The Dashboard's AI Watch cards are now **AI services not yet approved** and **People using AI not yet approved**, and each says how many are Not approved and how many are only Unreviewed, for example "0 not approved, 1 unreviewed". Services nobody has reviewed yet are no longer called unapproved.
- **Needs attention** on the Dashboard lists not approved and unreviewed AI services apart, the same way as the AI usage page.
- What changes for existing installs: nothing to do.

### Example questions in Ask (2026-11-03)

- Before your first question, Ask shows up to six example questions that fit the sources this install has data from, such as "Who logged in over SSH?". One click asks it.
- What changes for existing installs: nothing to do.

### Questions in the top bar search go to Ask (2026-11-03)

- Type a question in the top bar search (for example "how many failed logins today?" or "show admin changes this week") and **Ask AI: <your question>** is the first option. Enter asks it beside the page you are on.
- What changes for existing installs: nothing to do.

### Ask is easier to find (2026-11-03)

- **Ask** now has its own row in the left menu under Investigate, right below Search.
- On the Search page, the small **AI** switch is replaced by three tabs: **Search**, **Ask AI**, and **SQL**. Your question and results are kept when you move between them.
- Auditors still do not see Ask.
- What changes for existing installs: nothing to do.

### Faster today-so-far build for quiet sources (2026-11-03)

- The 5-minute build of today's AI use now skips a source whose files have not changed since the last build, and carries its last result over. Busy sources build as before, so the results are the same.
- The server log line `ai_rollup.today` now says how many sources were carried over (`reused`).
- What changes for existing installs: nothing to do. The first build after updating is a full one.

### Clearer comparison line on Dashboard trends (2026-11-03)

- The dashed line on trend charts now says what it is, "Same hour yesterday" or "Same hour last week", instead of "Previous 7 days", and the tooltip shows its date, for example "Same hour last week (Oct 20, 12 AM): 2".
- The line is darker and slightly thicker, so it is easy to see in both themes.
- What changes for existing installs: nothing to do.

### AIDE: the spool folder is skipped, and hashes are no longer read as paths (2026-11-03)

- The AIDE rules the update script writes now skip the data folder's `spool/`, where incoming syslog and OpenTelemetry messages wait to be ingested.
- `update-systemd.sh --aide` no longer mistakes a hash in AIDE's detailed report for a changed file outside the install, which could stop an update for no reason.
- What changes for existing installs: the next update rewrites `/etc/aide/aide.conf.d/90_aide_remnant` with the new rule and says so; re-baseline as usual.

### See whether a local model runs on GPU or CPU (2026-11-03)

- **Settings > AI providers** now shows, for a local Ollama provider, whether its model is loaded on GPU, on CPU only, or split between them, its size, and its context length, as Ollama reports them. Other models the server has loaded are listed too.
- What changes for existing installs: nothing to do. Nothing shows for cloud providers or for servers other than Ollama.

### Failing background checks say why, and show on Health and the Dashboard (2026-11-03)

- When AI Watch, a page refresh, or another background check fails, the server log now names the database's own error and its message (values from your logs are cut out), not only the error class.
- AI Watch runs its three steps separately, so one failing step no longer stops the others.
- **Health** lists checks that are failing, since when, how many runs failed, and why, with **Check AI Watch now** to run every step at once. The Dashboard's **AI Watch** panel says when its checks are failing and that alerts and review items may be behind.
- A page that read files during a rollup update is read again once instead of failing.
- What changes for existing installs: nothing to do. After updating, open Health and choose Check AI Watch now to see why it was failing.

### Show events opens exactly the events a row counts (2026-11-02)

- When a question names a person, an address, or a machine, **Show events** now keeps those filters too, so a row that says 5 opens 5 events.
- Ask can now write a cited summary for **Users consenting to applications** and **Admin role and policy changes**: each row carries an event id.
- What changes for existing installs: nothing to do. The Microsoft 365 library pack is now 1.1.0; copies you saved from it keep their own SQL.

### Show the events behind an Ask row (2026-11-02)

- When **Ask** answers from the query library with counts per person, address, or host, each row now has **Show events**. It opens Search with the events behind that row, on the same time range and filters: the query is built from the library query itself, not by the model, and runs like any search.
- 19 of the 29 library queries support it; the rest show their rows as before.
- What changes for existing installs: nothing to do.

### Ask's routing and answer steps can never be given tools (2026-11-02)

- The AI gate now refuses any tool on Ask's routing and answer calls, whatever the caller passes. Only the step that writes SQL can use Ask's two read-only tools.
- What changes for existing installs: nothing to do.

### Ask answers with a headline and cited statements (2026-11-02)

- After the rows, **Ask** shows a one-line headline written from the result itself, for example "12 accounts with failed sign-ins; most: dana@example.com (40 failures)". It is never written by the model.
- Then, when the rows carry event ids, the model writes up to five statements about them, each with the event ids it is based on. A statement that cites none of the rows is removed, and Ask says how many were removed. If nothing can be cited, there is no summary: the headline and the rows stand alone.
- What the model said about its query moved under **How I got this**, so the space above the rows holds only what the rows support.
- New setting `ask.summarize` (default on; `APP__ASK__SUMMARIZE=false` to turn off): off, Ask makes no model call after the query, which suits slow CPU-only models.
- What changes for existing installs: nothing to do. Results without event ids, which includes most library queries, show the headline and rows without a summary for now.

### Ask on a CPU-only server (2026-11-02)

- A new install page, **Ask on a CPU-only server**, covers running Ollama next to the app on one machine with no GPU: which small model to pull, how to split 8 GB between the model and the app's query memory, and what speed to expect.
- What changes for existing installs: nothing. It is documentation only.

### Why a Claude plugin token was refused (2026-11-02)

- **Settings > Claude plugins** now lists, under each deployment token, every machine that sent with it and when it was last seen, and the last reason the server refused that token: revoked, its source turned off or removed, a bad payload, or too many requests.
- A new **Unknown tokens** section lists tokens the server refused because they match none of its own (usually an old download), by their first 8 characters and the sending address. The full token is never kept.
- What changes for existing installs: nothing to do. The server adds two columns to its token table on the first start. Unknown tokens are kept in memory only, so the list starts empty after a restart.

### Hooks plugin diagnostics (2026-11-02)

- Plugin version 2.2.0 leaves a status file after every run (last run, event, sent or queued or skipped and why, HTTP status, queue depth). It holds no token and no content.
- `install-local.sh --doctor` and `install-local.ps1 -Doctor` check a machine and print a pass or fail list: config, certificate, server, token (with one test record), whether Claude lists the plugin, and the hook's last status.
- The hooks guide now says which install paths are known to fire hooks and which are untested, and has a troubleshooting table for the status file.
- What changes for existing installs: download the plugin again and reinstall it to get 2.2.0.

### Quiet alerts off on existing Claude Code sources (2026-11-02)

- On the first start after this update, the server turns off the 1-hour quiet alert on existing OpenTelemetry sources that still have it exactly as it was set when the source was added (no alert targets, never edited). Quiet alerts you changed are kept. Each change is in the audit log as `source.quiet_alert_change`, with the reason.
- What changes for existing installs: nothing to do. If an OpenTelemetry source receives from collectors that send all the time and you want its quiet alert back, turn it on again on **Sources**.

### Ask answers from the query library first (2026-11-02)

- Ask now reads the time ("today", "yesterday", "this week", "last 6 hours") and the people, addresses, and machines in your question itself, then picks a shipped library query when one fits and runs it with those as filters. The model only decides which library query fits; it writes SQL only when none does. **How I got this** names the library query, the filters, and the time.
- Questions that ask for general advice rather than your data are recognized as such; for now Ask offers **Check your data instead**. General guidance answers come in a later update.
- With no AI provider set up, Ask still suggests up to three library queries that match your words.
- Every library query now carries example questions (`ask:` in the pack files).
- What changes for existing installs: nothing to do.

### Ask answers, from anywhere (2026-11-02)

- **Ask** now runs its query as soon as it passes the safety checks, on your own sources, and shows the rows right under your question. The SQL, where the query came from, the sources read, and the time taken are under **How I got this**; **Edit as SQL** opens it in the SQL tab.
- Each question is a block; follow-ups stack below and refine the last one. People, addresses, and hosts in the rows open their pages.
- Ask from any page: press Ctrl+K and choose **Ask**, or type a sentence and choose **Ask "..."**. It opens beside the page.
- With a cloud model chosen, Ask says "Your question is sent to <provider>" under the question box.
- Ask now keeps each answer's SQL on the server, and `POST /api/ask/{ask_id}/run` runs exactly that SQL for the person who asked, through the same guard and on their own sources, capped at 1,000 rows and 90 days. Each run is in the audit log as a query with purpose `ask`.
- `remnant ask --yes` runs the answer without the prompt when the server allows auto-run and the SQL passed its self-check.
- What changes for existing installs: nothing to do. To keep click-to-run, set `ask.auto_run: false` in config/app.yaml.

### Quieter quiet alerts for Claude Code (2026-11-02)

- "Stopped sending" now fires once per source each time it goes quiet; two checks at the same minute no longer both alert.
- When you add an OpenTelemetry source, you choose who sends to it. For **Claude Code (telemetry or the hooks plugin)** the source-level quiet alert starts off, because Claude Code sends only while people use it and evenings would alert every day. Agents and collectors keep the 1-hour quiet alert.
- **Health > Endpoint agents** no longer flags a hooks plugin machine just for being quiet. It flags a machine whose plugin has records waiting and delivered none for 3 days (`agents.queue_stuck_days`), and raises one alert for it.
- What changes for existing installs: existing quiet alerts stay as they are. To stop the evening alerts on a Claude Code source you already have, turn its quiet alert off on **Sources**.

### Send a test record from Settings (2026-11-02)

- **Settings > Claude plugins** has **Send a test record** next to each deployment token. It sends one synthetic session start through the real receiver with that token and shows the HTTP result, so you can check the server side before installing the plugin anywhere. The record names no person or machine.
- What changes for existing installs: nothing to do.

### Easier to read at a glance (2026-11-02)

- A **Needs attention** strip at the top of the Dashboard and each area overview lists what to act on, with links: unreviewed AI services, MCP servers not approved, risky mail rules, blocked consents, open alerts, and real failed sign-ins when they jump. It says "Nothing needs attention" when there is nothing.
- Zero and benign values are shown in muted gray instead of green; colors are kept for alerts.
- Sections without enough history show one "Comparisons start <date>" line instead of "Not enough history" under every number.
- The Dashboard header no longer shows a time range that could disagree with the panels; each saved-search panel shows its own.
- What changes for existing installs: nothing to do.

### "How this is counted" on every number (2026-11-02)

- Every number on the Dashboard, Microsoft 365, Agents, AI Watch, and Health has an (i) beside it. Hover it to see which events and sources it counts, over what window, what is left out, and the rule used, for example what "external" means for External sign-in failures and how devices map to people for People using unapproved AI.
- What changes for existing installs: nothing to do.

### No more blank pages (2026-11-02)

- If a page fails to show, you now see "Something went wrong on this page" with a **Reload** button and an error id instead of a blank page. One failing Dashboard panel shows an error card and the rest of the page still loads.
- After an update, a tab left open on the old version reloads itself once when it needs a page file the new version no longer has. It never reloads in a loop.
- Page and panel failures are reported to the server: administrators see them on **Health** under "Browser errors, last 24 hours", and they are in the server log as `client.error`. Reports carry the error kind, a short message with values removed, the page path, and the build, never log content.
- What changes for existing installs: nothing to do. Tabs opened before this update may need one manual refresh.

### Hooks plugin users counted everywhere (2026-11-02)

- A person seen only through the Claude hooks plugin (a session start is enough) now appears on **Agents**, on **AI usage > People**, and in the "Claude Code users" count in the page header. Sessions that telemetry also reports are counted once.
- A session with no end record and nothing for 2 hours reads **Ended (no end event)**, with its last-seen time, instead of "still open". Set `agents.session_idle_minutes` in config/app.yaml to change the 2 hours.
- **Sessions** hides sessions with no tool calls or prompts by default; untick **Hide sessions with no tool calls or prompts** to see test and empty sessions.
- **AI usage > People** has a **Seen through** column: Plugin (telemetry or hooks), Network (DNS, firewall, or proxy logs to Claude), or Both. People seen only on the network are listed and counted as "Seen on the network but no plugin", so a Claude Code user missing the plugin stands out from a browser-only user. The Claude row on Services shows the same three counts.
- What changes for existing installs: nothing to do. The counts include hooks records already stored.

### Install the hooks plugin on one machine in one step (2026-11-02)

- Every plugin download now carries **install-local.ps1** (Windows) or **install-local.sh** (macOS and Linux). Run it from the unzipped folder: it builds a local marketplace, installs the plugin for your user with the Claude Code CLI, and lists your plugins. Use it to test on one machine; the desktop app's Code tab cannot run `/plugin`.
- The hooks guide's **Publish** section now has three paths: one machine, fleet (managed bundle plus the plugin), and organization library upload, with what we saw on the Windows desktop app.
- What changes for existing installs: nothing to do. Download the plugin again to get the installer.

### Claude plugin downloads in one place (2026-11-02)

- **Settings > Claude plugins** is the only place to download the hooks plugin and mint its tokens. The OTLP source row now links there instead of downloading (each row download issued a new token and quietly broke earlier copies).
- Revoking the token picked in "Deployment token" switches the picker back to **New token**, so the next download no longer fails with "No such token, or it was revoked".
- **Include this server's self-signed certificate** is now unticked by default when people reach the server through a reverse proxy, or when the address you give is not a name on the server's certificate; a line under the checkbox says why.
- An empty **Pilot users** list now warns: "Everyone who installs this plugin will send records."
- What changes for existing installs: nothing to do. Plugins already downloaded keep sending until their token is revoked.

### Sign-ins by outcome on person, address, and host pages (2026-11-02)

- Person, address, and host pages show the entity's sign-ins by outcome (Real failures, Interrupted, Expired, Other, All) with counts; each opens those sign-ins in Search in one click.
- 50158 (external security challenge not yet satisfied) now counts as Interrupted instead of Other.
- What changes for existing installs: nothing to do. Sign-ins with code 50158 move from Other to Interrupted, on stored events too.

### Failed sign-ins count real failures only (2026-11-02)

- **Failed sign-ins** on the Dashboard, Microsoft 365 > Overview, and person, address, and host pages, and **Top failing users**, now count real failures only: wrong password, locked, MFA denied or failed, expired password, disabled account, user not found, and blocked by Conditional Access. Background token refreshes, expired sessions from sleeping laptops, "stay signed in" prompts, and MFA prompts the person then completed no longer count.
- Under the number, "+ N interrupted or expired (not counted)" opens those sign-ins; codes Remnant does not know are counted as **other**, never hidden. **Blocked by policy** (Conditional Access) has its own card on Microsoft 365 > Overview, and the outcomes chart shows failed, interrupted, expired, and other.
- **Microsoft 365 > Sign-ins** filters by Real failures (the default), Interrupted, Expired, Other, or All, and by Interactive or Non-interactive.
- The (i) beside Failed sign-ins says exactly how it is counted and whether this install changed the classes. To move a code (for example, count MFA interrupts as failures when hunting MFA fatigue), set `m365.signin_classes` in `config/app.yaml` (see `config/app.example.yaml`) and restart.
- New columns `status_code` (Entra's error code) and `is_interactive` from the sign-ins parser 1.2.0.
- What changes for existing installs: Failed sign-ins drops to real failures, on stored events too (they are read from the stored record). The Microsoft 365 rollup rebuilds its days once after the update, so the first Microsoft 365 and Dashboard loads may be slower until it finishes.

### Docs: Microsoft 365 connector on a live tenant (2026-11-02)

- The v0.3.0 notes, CLAUDE.md, and the backlog now say the Microsoft 365 connector runs against a live tenant (on a test install since late October 2026); only the Anthropic connectors are still tested against fakes alone.
- What changes for existing installs: nothing.

<!-- unreleased:end -->

## v0.3.0 (2026-11-02)

### What works today

- **AI usage.** AI services seen in DNS, firewall, and proxy logs, matched by domain against a built-in catalog you can extend; review each as Approved or Not approved; New and No longer seen against the period before.
- **Agents and MCP servers.** Claude Code telemetry (OTLP) and the hooks plugin: sessions step by step, tools, MCP servers (installed and used), people, cost, and what changed; MCP inventory from an endpoint script.
- **AI Watch.** One alert per first sighting of unapproved or unreviewed AI, sensitive data in prompts, agent changes, and app consents; a Dashboard panel with counts against the week before.
- **Microsoft 365.** Audit logs, Entra sign-ins, directory audits, and alerts: sign-ins outside approved countries, risky mail rules, app consents, admin changes with directory sync grouped. Tested against fake endpoints and running against a live tenant on a test install since late October 2026.
- **The log platform.** Files and folders, syslog over UDP, TCP, and TLS, JSON, CSV, EVTX, and Grafana Loki; 39 starter parsers mapped to OCSF; a Parquet lake queried with DuckDB through a read-only SQL guard; Simple search, SQL, and Ask; Sigma rules and scheduled searches with email, Teams, Slack, and webhook alerts; Health for every source, connector, agent, and alert target.
- **Models.** Ollama, LM Studio, llama.cpp, vLLM, any OpenAI-compatible API, or Anthropic, through one gate: sources marked Local only never go to a cloud model, every call is audited, and every Explain claim cites event ids that are checked.
- **Evidence.** Append-only audit log; stored logs, the audit log, and AI call records hash-chained, checked daily, and sealed.
- **Team ready.** Accounts, roles, per-source access, HTTPS by default off loopback, optional single sign-on, online backups.
- **Not yet:** Okta, Google Workspace, and AWS CloudTrail connectors, and an object-storage tier (in `docs/BACKLOG.md`). The Anthropic adapter and the Anthropic connectors are tested against fake servers only.

### Demo install and new screenshots (2026-11-02)

- **`make demo`** starts a throwaway server on http://127.0.0.1:8090 with two weeks of synthetic logs for a fictional company: Microsoft 365 sign-ins and audit, Palo Alto traffic, Linux SSH, DNS, and Claude Code hook and telemetry records. Findings to look for: password spraying from one range ending in a successful sign-in, a mail rule forwarding invoices outside and hiding them, a blocked app consent, an unreviewed AI service, and a not approved MCP server.
- **New README screenshots** taken from the demo by `scripts/screenshots/capture.py`, and a social preview image (`docs/images/social-preview.png`).
- **Explain** shows the last 8 characters of each cited event id (the first ones are the same across a batch), with the full id on hover.
- What changes for existing installs: nothing. The new setting `enrichment.place_documentation_ranges` is off by default and is for the demo only.

### Titles easier to spot (2026-11-01)

- **Section titles** (AI Watch, Identity, Attacks and access, and the same level on Microsoft 365, AI usage, Agents, Health, and settings pages) sit on a soft slate pill, slightly larger and bolder.
- **Panel titles and KPI labels** (Top services, AI use, Failed sign-ins per hour, Top failing users, each KPI's label) are small upper case with wider letter spacing, brighter than the data.
- Neither uses the link blue or reacts to the pointer, so they don't read as links. One shared component per level (`SectionTitle`, `PanelTitle`).
- What changes for existing installs: nothing to do.

### Counts from rollup-only ranges (2026-11-01)

- **Some counts may rise after this update.** Before #339, a Microsoft 365 source with no events in the range except on days already rolled up (no new events today, or a custom range that ends before today) was left out of Microsoft 365 > Overview and the Dashboard's Identity section, so those numbers were too low. They now match a read from events. Attacks and access was checked the same way and was not affected.
- New regression tests compare each page read from the rollups with the same page read from events when no live files are in range.
- What changes for existing installs: nothing to do.

### MCP servers from the hooks plugin, and refresh limits (2026-11-01)

- **MCP servers seen only by the Claude Code hooks plugin** now show in AI usage's MCP list, AI Watch's review, and the first-seen alerts, unreviewed until someone reviews them. A server both telemetry and the hooks plugin report is one row, its calls counted once.
- **AI inventory** reads closed days from the daily AI rollup (2.2 times faster on 450,000 hook records).
- **Background refresh** of the default views stops 10 minutes after the last load and starts again on the next. Health > Speed shows refreshes per hour.
- What changes for existing installs: nothing to do. The next rollup runs add MCP rows to days already built and re-index first-seen once; until a day has them it is read from events.

### Ready for the Claude plugin pilot (2026-11-01)

- Checked that records from the Claude Code hooks plugin feed the daily AI rollup and the 5-minute today build, and timed the AI pages with 30 people's worth of hook records for 30 days (450,000 records): every page under 2 seconds on a 2 vCPU test machine.
- `scripts/bench_hooks.py` repeats the test on your own hardware with synthetic data.

### Health > Speed (2026-11-01)

- A new **Speed** tab on Health (administrators) lists every page that reads data with its typical (p50) and slow (p95) load time over the last 24 hours, time in the database, time waiting for a query slot, and how often the page cache answered.
- Kept in memory only; a restart starts the 24 hours again.
- What changes for existing installs: nothing to do.

### Lighter web UI (2026-11-01)

- The UI loads only the Latin character set of its fonts, loads the SQL editor when you first open the SQL tab, and lets your browser keep built files for a year (a new version still shows at once).
- Log text in other scripts (Cyrillic, Greek, and so on) shows in your browser's fallback font.

### Microsoft 365 > Admin: no duplicate rows, "Synced from AD" (2026-11-01)

- A change reported by both Microsoft Graph and the Management API now shows once, with both events counted, even when the two copies do not share a correlation id.
- Users and changes created by the directory sync service with the on-premises sync properties are marked **Synced from AD**: the real change happened in on-premises Active Directory.
- What changes for existing installs: nothing to do.

### Quieter AIDE checks (2026-11-01)

- `update-systemd.sh --aide` lists changed paths under /etc, /usr, /opt, and /var/lib first, then the rest, then a count per folder, so noise in /run cannot hide them.
- The update only changes permissions that need changing, and the server no longer touches `.key` on every start, so neither shows up as changed in AIDE.
- The install guide shows an optional rules file for /run, /tmp, /var/tmp, and /var/log/aide.
- What changes for existing installs: nothing to do. The next `--aide` run may still list `.key` and install files once (changed by the previous update); after that they stay quiet.

### Faster filters on compacted days (2026-11-01)

- Compaction now groups each file's rows by parser template and time, in smaller row groups, so a search or page that filters on one kind of event skips the rest of the file (about 10 times faster on a synthetic test file).
- What changes for existing installs: nothing to do. Days compacted from now on get the new layout; days already compacted keep theirs.

### Default views load at once (2026-11-01)

- **Dashboard (7 days), Microsoft 365 Overview (7 days), and AI Watch (7 days)** are refreshed in the background every minute while someone is using them, so opening them shows numbers at once. The top bar says how old they are ("Updated 40 s ago").
- Any change you make in the app still shows on the next load. Other time windows work as before.
- What changes for existing installs: nothing to do.

### Reused query instances, opt-in (2026-11-01)

- **New setting `server.query_pool`** (off by default): Dashboard and other page sections reuse a kept DuckDB instance per slot and remember Parquet file details between queries. About 20% faster Dashboard loads on a test machine with local disk; more expected on networked storage.
- Only the app's own page sections use it. Search, saved and scheduled searches, exports, and every Ask query always get a fresh instance limited to the caller's sources. A kept instance may open any of the app's data folders; each user still sees only their own sources (D146).
- What changes for existing installs: nothing unless you set `APP__SERVER__QUERY_POOL=true`.

### Faster today reads, audit writes, and AI Watch (2026-11-01)

- **Today's rows**: pages that take earlier rows from a rollup read only today's newest rows; files written before the cutoff are skipped instead of read and filtered.
- **Settings database**: now uses SQLite's write-ahead log, so recording an audit row no longer waits for the disk. Cached pages answer much faster on networked storage.
- **AI Watch and AI pages**: the AI service catalog and MCP rules are read once every few seconds instead of on every query.
- **New settings to try** (both off by default): `server.page_query_mb` and `server.section_parallel`. `scripts/bench_pages.py` times the Dashboard on a running install so you can compare.
- What changes for existing installs: nothing to do. The first start converts `meta.sqlite` to the write-ahead log (see the install guide's "Power loss and the settings database"); `meta.sqlite-wal` and `meta.sqlite-shm` appear beside it (AIDE already skips them). After a power loss the last few seconds of settings or audit changes can be missing.

### Faster person pages (2026-11-01)

- **Person AI flow graph**: reads closed days from the daily AI rollup like AI usage does (2.3 s to 0.9 s on a synthetic 30-day lake).
- **Person summary and Timeline**: their queries run together instead of one after another, and repeat loads skip re-checking the same SQL (about 0.4 s of server time on the first load of a page, under 50 ms after).
- **Person summary activities** tied on count are listed in a stable order.
- What changes for existing installs: nothing to do.

### Faster pages on real data (2026-11-01)

- **Attacks and access**: about 15 times faster on a busy 30-day window (13.8 s to 0.9 s on a synthetic lake shaped like a small ISP). It now counts every outside address; it used to stop at 5,000.
- **Long lists** of addresses or days are passed to the database in one piece; binding them one by one took most of the time.
- **AI usage and the AI inventory** share their answers for a minute, so opening one after the other reads once.
- **Cached pages** (Dashboard sections, Microsoft 365) answer without reading settings again.
- **Correct counts**: a range starting partway through a day no longer counts that whole day from the AI rollup.
- **Server-Timing** `db` and `wait` are now wall time; `db_sum` and `wait_sum` keep the totals across queries running in parallel.
- **Query traces**: set `server.trace_queries: true` (or `APP__SERVER__TRACE_QUERIES=true`) to log a `query.trace` line per page query with what it read and its slowest steps. Leave it off normally.
- What changes for existing installs: nothing to do.

### AIDE: check before re-baselining (2026-11-01)

- `update-systemd.sh --aide` now runs `aide --check` first, before stopping the service, and prints how many files were added, removed, and changed, with the changed paths outside `/opt/remnant`.
- Changes outside `/opt/remnant`, the script's own AIDE rules file, and the installed-commit record stop the update, including any other change under `/etc/aide`: "AIDE found changes not made by this update. Review them, then re-run with --aide-accept." So does a check AIDE cannot run (for example no baseline yet).
- It re-baselines only after a successful update with a clean (or accepted) check. A run with nothing to update reports the check and does not re-baseline.
- What changes for existing installs: `--aide` runs take longer (a full check before the update). The first time, if AIDE reports changes from before this version, review them and re-run with `--aide-accept`.

### Microsoft 365 > Admin: grouped and cleaner (2026-11-01)

- Changes sit under Roles and apps, Credentials, Policies, Users, and Groups, most important first, newest first within each.
- A deleted user shows by name (without the id Entra adds) and is marked deleted.
- "Included Updated Properties" no longer appears in Changed.
- An app with no name in the window shows its id instead of "(unknown)".
- What changes for existing installs: nothing to do.

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
