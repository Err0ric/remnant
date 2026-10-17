# ADR-0019: Health page and watched devices

Status: **Accepted** 2026-10-15 (project owner). Recorded as SPEC D49; threats T43 and T44.

## Context

Whether the pipeline works is spread over several screens: Ingest health on the Overview, connector warnings on Sources, quiet-source alerts (ADR-0014), failing alert targets, paused schedules. There is no single "is everything healthy?" view, no way to see that one machine's endpoint agent or Claude Code telemetry went silent, and nothing for security devices that do not send logs to Remnant themselves (network sensors, collectors of other security products) but appear in logs it already has.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Where | A **Health** page under General: four count tiles (Unhealthy, Needs attention, Paused, Healthy) and tabs **Sources**, **Connectors**, **Agents**, **Watched devices**, **Alerts and schedules**. Each row has a state and a one-line reason | One answer to "is anything broken?", in the same words everywhere | More Overview cards (the Overview is about data and detections) |
| 2 | Sources and connectors | From what the server already keeps: source status, connector feed warnings, quiet-source state. Error or quiet = Unhealthy; a failing feed, skipped records, or files waiting = Needs attention; disabled = Paused | No new collection; the same states as Sources and the Overview | |
| 3 | Agents | Per machine for OpenTelemetry sources (Claude Code, endpoint agents) and the MCP inventory: last event received and events in 24 h. Silent over 24 h (inventory: 48 h, it runs daily) = Needs attention; over 7 days = Unhealthy | A source can be healthy while one laptop stopped reporting | Per-machine settings (later, if asked) |
| 4 | Watched devices | An admin lists a device by IP address or host name, with a name and an allowed silence (5 min to 24 h). It is **Healthy** while it appears in any event in the lake (source or destination address, device, source, or destination host name), **Unhealthy** when silent longer than allowed, and **Needs attention** when its last two hours run under a quarter of its usual hourly volume. Times are the event's own, capped at when it was received | Proves the device is doing its job (a sensor that calls home shows in firewall logs) with no new credentials, ports, or firewall rules | Active checks, row 6 |
| 5 | Alerts | Optional alert targets per device. One alert when it goes silent, one when it is seen again, as the system, like ADR-0014 rows 3 and 4. Summary only (name and times, never event content). Changes audited `device_watch.change`; transitions `device.quiet` and `device.resumed` | Same behavior people already know from quiet sources | |
| 6 | Active checks (ping, TCP port) | **Not built.** Remnant does not connect to watched devices. Uptime is a different tool's job (an uptime monitor or a Grafana synthetic check); its alerts can be ingested as a source | A SIEM that probes hosts is a new outbound behavior that needs network paths, a container capability for ICMP, and guardrails against use as a scanner, for a question other tools already answer | Ping or TCP checks with an admin-only allowlist |
| 7 | Who sees what | Everyone signed in sees the page; each tab reads only sources the viewer may read (a device seen only in a source you cannot read shows "Not seen in sources you can read"). Adding, changing, and removing watched devices is admin-only. The background check runs over every source, like the quiet-source watch, and reads only times and counts | Same access model as the rest of the app | |

## Consequences

- One additive table (`device_watches`, migration 33) and two alert kinds (`device_quiet`, `device_resumed`).
- The background check reads at most the last 25 hours once a minute, matching on a handful of address and host columns.
- ATT&CK: a device that goes silent can be indicator blocking (T1562.006) or impaired defenses (T1562.001); the page and alerts make that visible. Not AI-facing; no ATLAS mapping.
- Threats: T43, a watched device's name or address shown to people who cannot read the sources it appears in (row 7: states computed per viewer, alert targets for administrators only); T44, a sensor or collector silenced on purpose goes unnoticed (rows 4 and 5).
