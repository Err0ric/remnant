# ADR-0017: Optional endpoint agent, built on the OpenTelemetry Collector

Status: **Accepted** 2026-10-14 (project owner asked for an optional agent; the recommendation below was sent to him and stands unless he asks for a custom agent). Recorded as SPEC D43; threats T39 and T40.

## Context

Remnant reads what collectors write (files, syslog relays, Loki, NXLog, Winlogbeat). Teams without a collector, or who want endpoint telemetry beyond what their servers forward, asked for an agent they can deploy. An endpoint agent runs with high privilege on every machine, so a homegrown one is a large attack surface (updates, signing, crash handling, resource limits). The OpenTelemetry Collector (CNCF) already ships signed builds for Windows, Linux, and macOS, reads Windows Event Log, journald, files, and host metrics, and speaks OTLP, which Remnant now receives (ADR-0015).

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | What the agent is | The official OpenTelemetry Collector (contrib or a build with the needed receivers) plus a configuration Remnant generates. Remnant ships no agent binary of its own | Signed, maintained, widely deployed; Remnant's job is the config and the receiving end | A custom agent (rejected: attack surface and upkeep) |
| 2 | Enrollment | An admin creates an OTLP source per agent group (for example "workstations", "servers"), gets the ingest token once, and downloads a config for Windows or Linux from the source (`GET /api/sources/{id}/agent-config?os=windows|linux`, admin, audited `source.agent_config`). The config reads the token from a file (`${file:...}`), never inline | One token per group, revocable by rotating; the config itself holds no secret and can sit in a software deployment tool | One token per host (management overhead with no extra safety at this stage) |
| 3 | What it collects (defaults) | Windows: Security, System, Application, Sysmon, PowerShell Operational, Windows Defender channels as event XML. Linux: journald, plus `/var/log/auth.log`, `/var/log/secure`, `/var/log/syslog` if present. Both: host metrics every 60 s (CPU, memory, disk, network) when enabled. Optional extra file paths | The events the starter templates and Sigma rules use | Everything by default (noise and cost) |
| 4 | How it lands | OTLP/HTTP JSON to the receiver, gzip, batched, with a retry queue. The receiver turns agent records into the shapes the existing templates read: Windows event XML into the `evtx` JSON shape (`windows_evtx` template); journald entries into RFC 5424 syslog lines (Linux templates); file lines spooled as written. Everything else stays an OTLP JSON record | Reuses the tested Windows and Linux mappings instead of new, untested ones | New templates for the collector's own map shapes |
| 5 | `raw` for agent records | For converted records, `raw` is the receiver's rendering (event XML as JSON; journald as a 5424 line), stated in the guide. File lines are byte-for-byte | Honest about what was kept; the Windows XML and journald fields that matter are all in the rendering | |
| 6 | MCP inventory | The agent runs the inventory script (ADR-0015 row 6) on a schedule where the deployment tool allows; otherwise the tool runs it directly | Same names-only data, no extra moving part | |
| 7 | Health | Agent groups are OTLP sources: last received time on Sources and Overview, and the quiet-source alert (ADR-0014) when a group stops sending. Per-host check-in is a query on `device_hostname` (a saved search ships in the guide) | Reuses what exists | A per-host agent registry (later, if needed) |
| 8 | Deployment | Documented for RMM tools, Intune, GPO, and systemd: install the collector package, drop the config and token file (readable by the service account only), start the service | Fits what teams already use | |

## Consequences

- The receiver grows two small converters (Windows XML, journald). The config generator is a template filled from server settings (`server.public_url`).
- Agent groups need the Remnant certificate trusted on endpoints (the same note as Claude Code telemetry).
- Built and tested against documented shapes and fixtures; the first live run on real endpoints is pending.

## Threats

| ID | Threat | ATT&CK | Control |
|---|---|---|---|
| T39 | An endpoint is compromised and sends forged or flooding records under the group token | T1565.001, T1499 | Records land only in that group's source; caps and rate limits (ADR-0015 row 3); rotate the token; records are marked with the reporting host |
| T40 | The agent config or token file leaks from the deployment tool | T1552.001 | The config holds no secret; the token file is separate, readable by the service account only, write-only to one source, revocable |
