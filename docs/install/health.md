# Health page

**General > Health** answers one question: is anything broken? Four counts at the top (Unhealthy, Needs attention, Paused, Healthy) cover every tab; select one to show only rows in that state.

| Tab | What it checks | Unhealthy | Needs attention |
|---|---|---|---|
| Sources | File, folder, and OpenTelemetry sources | Read error, or quiet longer than its quiet-source alert allows ([quiet-sources.md](quiet-sources.md)) | Not read yet, unreadable records, files still being written |
| Connectors | Microsoft 365, the Anthropic admin API, Grafana Loki | Error (for example expired credentials) | A feed failing while the others work, retrying after errors, more than an hour behind |
| Agents | One row per machine for Claude Code telemetry, endpoint agents, and the MCP inventory | Silent more than 7 days | Silent more than 24 hours (MCP inventory: 48 hours, it runs daily) |
| Watched devices | Devices you list, see below | Silent longer than you allow | Last two hours under a quarter of its usual volume |
| Alerts and schedules | Alert targets (administrators) and schedules | A target whose deliveries keep failing | |

Paused means turned off on purpose: a disabled source, or a paused schedule.

Everyone signed in can open the page; each tab only reads the sources you may read.

## Watched devices

Use this for security devices that do not send logs to this server themselves but show up in logs it already has: a network sensor that calls home through the firewall, a collector for another security product, the firewall itself.

1. **Health > Watched devices > Watch a device** (administrators).
2. **Name**: what people should see, for example `Site A network sensor`.
3. **IP address or host name**: matched in the source and destination address columns and the device, source, and destination host name columns. A short name like `sensor-a` also matches `sensor-a.corp.example`.
4. **Unhealthy after silent for**: 5 minutes to 24 hours. Pick something longer than the device's quietest normal gap.
5. Optional alert targets: one alert when it goes silent, one when it is seen again.

The server never connects to a watched device: no ping, no port check, no credentials. If you also want to know whether a box is powered on, use an uptime monitor and, if it can send syslog or a webhook, add its alerts as a source.

Times are the event's own, never later than when the event was received, so a device whose clock runs ahead cannot look alive while silent.
