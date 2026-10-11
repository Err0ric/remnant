# Getting logs into Remnant

Remnant reads files from folders. A collector receives syslog from your devices and writes those files.

| Collector | Guide | Tested |
|---|---|---|
| rsyslog (default on Debian, Ubuntu, RHEL) | [rsyslog.md](rsyslog.md) | 8.2312.0, 2026-10-10 |
| syslog-ng | [syslog-ng.md](syslog-ng.md) | 4.3.1, 2026-10-10 |
| Vector | [vector.md](vector.md) | Config checked against 0.60 docs; run pending |

No collector yet? Use rsyslog on the Remnant VM itself: it is already installed on most Linux systems.

Logs already in Grafana Loki? Remnant can read them from Loki directly, with no collector: see [loki.md](loki.md) (tested against a fake Loki in the test suite; first run against a real Loki pending).

A native syslog listener inside Remnant is planned (Slice 7).
