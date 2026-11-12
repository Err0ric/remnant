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

## Rotating log files

Rotate the files Remnant reads with **create** (rename the old file, start a new one; logrotate's default), not **copytruncate**. The logrotate example is in [rsyslog.md](rsyslog.md) step 5.

- `copytruncate` copies the file and then empties it in place. Lines written between the copy and the truncate are lost by logrotate itself, and Remnant can skip the first lines of the refilled file when it grows past the old read position between two passes.
- With `create` the old file keeps its content under a new name and the new file starts empty, so Remnant reads it from its first line.
- Keep rotated copies out of the source's file pattern. `**/*.log` does not match `fw.log.1`; a pattern such as `fw.log*` does, and a rotated copy the source lists is read again from its start, so its events are stored twice.
- Known gap until ADR-0051 is built: a line written in the last seconds before the rename (after Remnant's last pass, 2 seconds by default) can be missed. A collector that writes dated file names (`fw-2026-11-12.log`) has no rename and no gap.
