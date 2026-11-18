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
- One file is read by one source. When two sources reach the same file (a folder source and a file source inside it, a symlink, or a hard link), the most specific source reads it: a source whose path names the file before a folder source, a folder source before a recursive pattern, and between two equally specific sources the one added first, and the other says so: "Read by" and the reading source's name when that is every file it lists (not counted as a problem, no quiet alert), and under its path on Settings > Sources a line naming the file and what to do. Whichever source reads a file, it starts where any source last stopped in it, so no line is stored twice: when the reading source is turned off or deleted, or no longer lists the file, the other carries on from there. A source added after a deletion reads from their start the files no other source lists. Windows event log (.evtx) files are not covered yet: two sources over one .evtx folder each store every record. Two different files with the same lines are both read: a syslog daemon that writes each line to two files (an rsyslog rule for `named` without `stop` after it, or a BIND query log written to two channels) stores every line twice when a source reads both files. Keep one of the two out of the sources.
- A last line that has no line ending yet is held until it is finished. If the file is rotated first (the line is then stored when Remnant closes the rotated file, 30 seconds later), or does not grow for 5 minutes, the line is stored as it is, marked `partial`.

What can still be missed:

- A file rotated while the server was not running, or after 5 minutes without new lines, is no longer open. Lines written to it between Remnant's last read and the rename are read only if the source's pattern also matches the rotated file. After a restart, the source shows a warning for a day when a file was rotated while the server was down and the pattern does not match the rotated file.
- A program that keeps writing to the old file for more than 30 seconds after the rotation (until it is told to reopen its log, logrotate's `postrotate`) can lose the later lines when the source watches a single file: Remnant keeps the renamed file open for 30 seconds after it has read it to its end. Tell the program to reopen right away.
- A collector that writes dated file names (`fw-2026-11-12.log`) has no rename at all.

## Lines stored twice

To find where doubled lines come from, run this in Logs, SQL mode (read-only). It groups the copies of each line from the last day:

```sql
SELECT source_id_list, copies, same_event_id, observed_apart_s, count(*) AS lines
FROM (
  SELECT
    string_agg(DISTINCT source_id, ', ' ORDER BY source_id) AS source_id_list,
    count(*) AS copies,
    count(DISTINCT event_id) = 1 AS same_event_id,
    round(date_diff('millisecond', min(time_observed), max(time_observed)) / 1000.0)
      AS observed_apart_s
  FROM events
  WHERE time >= now() - INTERVAL 1 DAY
  GROUP BY raw, time
  HAVING count(*) > 1
)
GROUP BY ALL
ORDER BY lines DESC
LIMIT 50
```

- Two sources in `source_id_list`: both read the line, from one file (before this was fixed) or from two files with the same lines. Compare the two sources' paths on Sources.
- One source, `same_event_id` false, `observed_apart_s` near 0: the source lists two files with the same lines, stored in the same pass (a syslog daemon writing each line to two files). Narrow the source's pattern.
- One source, `observed_apart_s` large: the same lines were read again later (a copy under the pattern, or a source deleted and added again).
- `same_event_id` true: one stored event is counted twice by the lake, not by ingest. Report it.

The lake does not store which file a line came from, only the source, so the source's path and pattern on Sources tell which files it covers.
