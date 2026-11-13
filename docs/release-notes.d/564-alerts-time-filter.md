### Design: a Time filter on closed and muted alerts (2026-11-13)

- Console redesign, build row 7, time controls, first part (ADR-0052 section 3.7; owner, 2026-11-13). The filter bar's Time control has five choices: 1 hour, 24 hours, 7 days, 30 days, and Custom. Custom is a start and an end, as a date and time in your own time zone (hover for UTC); leaving one empty leaves that side open, so Custom with no dates is everything kept.
- Alerts: open alerts are never filtered by time, so an old open alert cannot drop out of the queue, and Open shows no Time control. Closed lists what was closed in the window, newest closed first, 7 days unless you choose another; the server picks them, so an alert raised long ago and closed yesterday is there. Muted always lists the mutes in force, and adds the ones that ended in the window, marked "ended".
- An alert opened from a link is shown whatever the window.
- API: `GET /api/alerts` takes `closed_from` and `closed_to` with `state=closed`; `GET /api/alerts/mutes` takes `ended`, `from` and `to`. A Closed list that holds only the newest of a long window says so.
- What you will notice: Closed shows the last 7 days by default; choose 30 days or Custom to see older ones.
- What changes for existing installs: nothing to do. Bookmarks to Closed open on the last 7 days.
