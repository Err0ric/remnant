# ADR-0021: Native syslog listener

Status: **Accepted** 2026-10-16 (project owner). Recorded as SPEC D55; threats T48 to T50.

## Context

Slice 7 lists a native UDP, TCP, and TLS syslog listener. Until now, network devices reach Remnant through rsyslog, syslog-ng, or Vector writing files under `allowed_roots`. That works but adds a daemon to install and configure for every small site, and a homelab or branch office often has only a firewall, a switch, and a hypervisor to point somewhere. The ingest pipeline (framer, envelope, payload, normalizer, writer) and the OTLP spool (ADR-0015 row 3) already exist.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Shape | A new source kind **Syslog listener** (`kind: syslog`). Each source owns one port and one protocol: UDP, TCP, or TLS over TCP. Ports 1024 to 65535, unique across listener sources, never the web port | One source per port keeps attribution and classification simple: everything on port 5514 is that source, with that parser and that classification | One shared port routed by sender address (later, if asked) |
| 2 | Path into the lake | The listener appends each message to the source's spool (`data/spool/<source>/<hour>.syslog`), and the ingest worker reads the spool like any file, through the source's parser. A spool record is a one-line JSON header (`{"n": <bytes>, "ip": "<sender>", "t": <truncated>}`) and then the message bytes, so a message may contain newlines and `raw` is the message exactly as received | Reuses the deterministic pipeline, checkpoints, and back-pressure of the OTLP receiver; a crash loses at most what was not yet flushed (half a second). A write cut short (disk full) is rolled back; a record that still does not read (a crash mid-write) stops that file, which is renamed `.damaged` and reported, never read past, since what follows is sender-controlled bytes | Writing to the lake from the listener (two writers, no parser reuse) |
| 3 | Framing | UDP: one datagram is one message; one trailing line ending is removed. TCP and TLS: octet counting (RFC 6587, `<len> <msg>`) or newline framing, detected from the first bytes of each connection, as for files. Messages over 64 KB are cut and flagged `truncated`, never dropped | What real senders do; same rules as file ingest | |
| 4 | Who may send | By default only private, loopback, and link-local addresses (RFC 1918, RFC 4193, 127/8, ::1). An admin can list addresses and networks instead (`0.0.0.0/0` to accept anyone, on purpose). Everything else is dropped and counted per address | Syslog has no authentication; a listener reachable from the internet is a log-injection and disk-filling target. The default fits a LAN | Accept all by default |
| 5 | Sender address | The sender's address fills `device_ip` when the message does not set it | The header host name is whatever the device says; the address is what the network saw | A new column (schema is additive only and `device_ip` already means this) |
| 6 | TLS | The server's certificate: the configured one, or the generated self-signed one (also on a loopback bind). No client certificates in this slice | Same trust story as the web UI; senders pin or import the same certificate | Mutual TLS (later) |
| 7 | Limits | Per source: at most 100 open TCP connections, 32 MB of messages held in memory between disk writes, 512 MB waiting in the spool (then messages are dropped and counted), idle connections closed after 10 minutes, TLS handshakes only for allowed senders under the connection limit, 10 s each (revised 2026-10-17 after a security review). Senders, counts, and drops are kept in memory and shown on the source | A noisy or hostile sender cannot exhaust memory or disk | |
| 8 | Containers | Docker publishes nothing new by default. The compose file carries commented port lines (5514/udp, 5514/tcp, 6514/tcp) and the guide says to publish the ports a source uses | No surprise open ports on upgrade | Publishing a range by default |
| 9 | Audit | Creating, changing, and deleting a listener source are audited like any source (`source.*`); dropped senders are counted, not audited per message | Same model as other sources | |

## Consequences

- New: `ingest/listener.py`, `kind: syslog` (migration 35 widens the kind check), a streaming framer for sockets, a listener block on the source status.
- The spool code is shared by OTLP and syslog; spool files carry their kind in the extension.
- ATT&CK: devices that send to Remnant directly can no longer be blinded by stopping a relay daemon (T1562.006 Indicator Blocking is still possible on the device). Spoofed syslog (T1565.001 Stored Data Manipulation) remains possible from an allowed network; row 5 keeps the real sender next to the claimed host. Not AI-facing; no ATLAS mapping beyond the existing rule that log content is untrusted (AML.T0051.001 for any later LLM use of these events).
- Threats: T48 log injection or flooding from outside the LAN (row 4, row 7); T49 a sender claims another host name (row 5); T50 eavesdropping on syslog in transit (row 6: TLS available; UDP and plain TCP stay plain by design, documented).
