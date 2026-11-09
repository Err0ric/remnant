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
