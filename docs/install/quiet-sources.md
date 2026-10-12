# Get an alert when a source goes quiet

A firewall that stops sending logs looks the same as a quiet network until you check. Schedules can already watch for this: a search that counts a source's events, run every hour, flagged when the count drops below 1, with an alert target.

Do this once per source you care about (firewalls, domain controllers, the VPN).

## 1. An alert target (administrators, once)

**Configuration > Alert targets**: add email, Teams, Slack, or a webhook, then **Send test**. See SPEC section 5.5 (Alert routing) for what each kind needs.

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
