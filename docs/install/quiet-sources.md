# Get an alert when a source goes quiet

A firewall that stops sending logs looks the same as a quiet network until you check. The app watches for this itself (ADR-0014).

## Built in (recommended)

1. **Settings > Alert targets**: add email, Teams, Slack, or a webhook, then **Send test**.
2. **Settings > Sources and connectors**: on the source's row, **Alert if quiet**. Pick how long without events counts as quiet (15 minutes to 7 days) and the targets, then **Save**.

| What happens | Detail |
|---|---|
| Goes quiet | One alert, "No events received for 4 h", and the row shows **Quiet** in Sources and Overview |
| Events resume | One alert, "Events arriving again after ..."; no repeats in between |
| Measured on | When events were *received*, so a source sending old timestamps still counts as alive |
| Restarts | The last received time is kept, so a restart neither resets nor fakes the clock |
| Turning it on | The clock starts at save, so it never alerts the moment you save |
| Who | Administrators only; every change, quiet, and resume is in the audit log (`source.quiet_alert_change`, `source.quiet`, `source.resumed`) |
| Content | Source name, times, and counts only; never event content |

Pick a period longer than the source's normal quiet stretch: a domain controller is never silent for an hour, but a VPN concentrator may be overnight.

## With a schedule (older approach)

Use this when you need a different test than "nothing at all", for example "fewer than 100 events an hour". Do it once per source.

## 1. An alert target (administrators, once)

**Settings > Alert targets**: add email, Teams, Slack, or a webhook, then **Send test**. See SPEC section 5.5 (Alert routing) for what each kind needs.

## 2. A saved search for the source

1. **Search**, SQL tab:

   ```sql
   SELECT event_id FROM events WHERE source_id = 'fw01'
   ```

   Use the source id from the **Sources** page.
2. **Save search**, name it `fw01 is sending`, and share it if others should see the schedule.

## 3. A schedule

On **Saved searches**, click **Schedule** next to it.

| Field | Value |
|---|---|
| When | **Hourly** (or a custom cron such as `*/15 * * * *` for every 15 minutes) |
| Time range of each run | **Last hour** (match it to how often the source normally sends; a quiet overnight source may need **Last 24 hours** and **Daily**) |
| Flag a run when the count is | **Below** `1` |
| Send alerts to | the target from step 1 |

The alert reads "0 is below 1" with the search name and a link back. A schedule that cannot run (for example, the owner lost access to the source) pauses itself and sends an alert saying why, so the watch never stops silently.

## Notes

- Each run ends two minutes before its time (`schedules.lag_seconds`) so slightly late events still count.
- The **Ingest health** card on **Overview** shows each source's last event time too; this schedule is what tells you without looking.
- Watching many sources at once from one schedule would need one alert per source; that is planned as a built-in check (see `docs/BACKLOG.md`).
