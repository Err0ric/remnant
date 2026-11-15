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

How Remnant follows a rotation (ADR-0051): it keeps a read position per file, not per name, and keeps each file it read from in the last 5 minutes open.

- With `create` the old file keeps its content under a new name. Remnant reads it to its end through the file it still has open, keeps it open 30 seconds more for a program that is still writing to it, and reads the new file from its first line. Nothing is lost and nothing is read twice.
- A rotated file that the source's pattern also matches (`fw.log.1` under `fw.log*`) is recognized as the same file and is not read again. A pattern that matches rotated files that are not compressed is safe with `create`, and it lets Remnant pick up the last lines of a file that was rotated while the server was not running. Choose the pattern when the source is added: a source's path and pattern cannot be edited, and a source that is deleted and added again reads all its files from the start, so its events would be stored twice. Keep compressed copies (`.gz`) out of the pattern: they are not text. Keep `delaycompress`, so the newest rotated file stays readable.
- `copytruncate` copies the file and then empties it in place. Lines written between the copy and the truncate are lost by logrotate itself, before anything can read them. Remnant notices the emptied file, reads it again from its start, and shows a warning on the source (Health and Sources) for a day. With `copytruncate`, keep the copies out of the source's pattern: a copy is a different file with the same content, and it would be read again and stored twice.
- A last line that has no line ending yet is held until it is finished. If the file is rotated first (the line is then stored when Remnant closes the rotated file, 30 seconds later), or does not grow for 5 minutes, the line is stored as it is, marked `partial`.

What can still be missed:

- A file rotated while the server was not running, or after 5 minutes without new lines, is no longer open. Lines written to it between Remnant's last read and the rename are read only if the source's pattern also matches the rotated file. After a restart, the source shows a warning for a day when a file was rotated while the server was down and the pattern does not match the rotated file.
- A program that keeps writing to the old file for more than 30 seconds after the rotation (until it is told to reopen its log, logrotate's `postrotate`) can lose the later lines when the source watches a single file: Remnant keeps the renamed file open for 30 seconds after it has read it to its end. Tell the program to reopen right away.
- A collector that writes dated file names (`fw-2026-11-12.log`) has no rename at all.
