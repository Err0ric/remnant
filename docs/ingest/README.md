# Getting logs into Remnant

Remnant reads files from folders, or receives syslog itself. A collector (rsyslog, syslog-ng, Vector) receives syslog from your devices and writes files; or point devices straight at Remnant with a syslog listener source.

| Collector | Guide | Tested |
|---|---|---|
| rsyslog (default on Debian, Ubuntu, RHEL) | [rsyslog.md](rsyslog.md) | 8.2312.0, 2026-10-10 |
| syslog-ng | [syslog-ng.md](syslog-ng.md) | 4.3.1, 2026-10-10 |
| Vector | [vector.md](vector.md) | 0.59.0, 2026-10-17 (CI VM) |

No collector yet? Use rsyslog on the Remnant VM itself: it is already installed on most Linux systems.

Logs already in Grafana Loki? Remnant can read them from Loki directly, with no collector: see [loki.md](loki.md) (tested against a fake Loki in the test suite; first run against a real Loki pending).

No collector at all? Add a **Syslog listener** source and send UDP, TCP, or TLS syslog straight to Remnant: see [../install/syslog-listener.md](../install/syslog-listener.md). A collector is still the better choice when you need buffering while Remnant is down, or one stream fanned out to several tools.
