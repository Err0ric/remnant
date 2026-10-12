# ADR-0014: Built-in alerts when a source goes quiet

Status: **Proposed** 2026-10-12 (waiting for the project owner's review).

## Context

A source that stops sending is a detection gap that looks like a quiet network (ATT&CK T1562.006 Indicator Blocking, T1070). Today the answer is a schedule per source: a saved search on the source, run hourly, flagged when the count is below 1 ([docs/install/quiet-sources.md](../install/quiet-sources.md)). It works, and a test proves it, but:

- It is one saved search and one schedule per source; nobody will keep 40 of them in step with the Sources list.
- It runs as one person; if they leave, their schedules pause.
- The Overview's Ingest health card already knows each source's last event time; it just cannot tell anyone.

## Decision (proposed)

| # | Question | Recommendation | Why | Alternative |
|---|---|---|---|---|
| 1 | Where it is set | On each source (Sources page, admins): **Alert if no events for** Off / 15 min / 1 h / 4 h / 24 h / custom, and **Send alerts to** (alert targets from ADR-0007) | One setting next to the thing it watches; new sources can be watched as they are added | A global default for all sources (noisy for sources that are quiet at night) |
| 2 | What "quiet" means | No event *received* (`time_observed`, not the event's own `time`) for the set period, checked every minute from the ingest status the server already keeps | Received time is what proves the pipe works; a device with a wrong clock still counts as sending | Event time (a skewed clock would raise false alarms) |
| 3 | Alerts | One alert when a source goes quiet, one "sending again" when events resume; no repeats in between. Summary only, same format and delivery rules as ADR-0007 (retries, delivery log, signing) | One open problem, one message; matches how people treat an outage | Repeat every period (alert fatigue) |
| 4 | Who it runs as | The system, not a person; it reads only ingest status (counts and times), never event content, so no source permissions are involved | Survives people leaving; no data exposure | Run as the admin who set it (pauses when they leave) |
| 5 | Visible in the UI | Sources page: a "Quiet for 2 h" badge in `--warn`; Overview Ingest health uses the same state; the delivery log per source | Same signal on screen and in the alert | |
| 6 | Audit | Setting changes `source.quiet_alert_change`; state changes `source.quiet` and `source.resumed` | Who turned the watch off is the first question after a gap | |
| 7 | Server down | Alerts cannot be sent by a server that is down. The guide recommends an outside uptime check of `/api/health` for that case | Honest limit | A heartbeat to an outside service (later, if asked) |

## Consequences

- Additive: two nullable columns on sources (`quiet_after_s`, `quiet_target_ids`) and a small state table; no change for sources left Off.
- The quiet-sources guide stays for people who want a custom condition (for example, "fewer than 100 events an hour").
- Not AI-facing; no ATLAS mapping.

## Threats

| Threat | ATT&CK | Control |
|---|---|---|
| An attacker stops a log source to hide activity | T1562.006 Indicator Blocking | This ADR: alert after the set period; state shown on Sources and Overview |
| Someone turns the watch off first | T1562.001 Impair Defenses | Admin only, audited with old and new values |
