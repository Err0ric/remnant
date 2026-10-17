# Syslog listener: send syslog straight to Remnant

A **Syslog listener** source opens a port on the Remnant server and stores every message it receives, then parses it like a log file. No rsyslog, syslog-ng, or Vector needed. Design: [ADR-0021](../adr/ADR-0021-syslog-listener.md).

| Choose | When |
|---|---|
| UDP | Most network gear (firewalls, switches, access points) only sends UDP. Messages can be lost on a busy network, with no error anywhere |
| TCP | The sender supports it (rsyslog, syslog-ng, Proxmox, most Linux). Nothing lost while Remnant is up |
| TLS | Logs cross a network you do not control. Encrypted with Remnant's certificate |

Keep a collector instead when you need buffering while Remnant is down for an upgrade, or one stream sent to several tools.

## 1. Add the source

**Settings > Sources and connectors > Add source**, **Reads from: Syslog sent over the network**.

| Field | Value |
|---|---|
| Source ID | For example `firewall` or `homelab_syslog` |
| Listen on | Protocol and port. Defaults: UDP and TCP 5514, TLS 6514. Ports 1024 to 65535 (the server does not run as root, so 514 is not available; map it in Docker if a device cannot change port, see below) |
| Parser (optional) | **Automatic** picks a template per line, which covers mixed devices on one port |
| Allowed senders (optional) | Addresses or networks, one per line. Empty accepts private networks only (10/8, 172.16/12, 192.168/16, 100.64/10, loopback, link-local, IPv6 ULA). Everything else is dropped and counted |
| Time zone (optional) | For devices that send RFC 3164 timestamps without a zone |

One port carries one source. Give each kind of device its own port when you want different parsers, classifications, or retention; otherwise one port for everything with the Automatic parser is fine.

The listener starts within a few seconds. The source row shows the protocol and port, messages received and refused, and (for administrators) the senders seen.

## 2. Docker: publish the port

Nothing is published by default. In `docker-compose.yml`, uncomment or add the port lines under `ports:`, then `docker compose up -d`:

```yaml
    ports:
      - "${APP_BIND:-127.0.0.1}:${APP_PORT:-8080}:8080"
      - "0.0.0.0:5514:5514/udp"
      - "0.0.0.0:5514:5514/tcp"
      - "0.0.0.0:6514:6514/tcp"
```

A device that can only send to port 514: publish `"0.0.0.0:514:5514/udp"`. Docker maps it; the server still listens on 5514.

Check the sender addresses on the source row after the first messages. If every sender shows as the Docker gateway (for example `172.17.0.1`) instead of the real device, Docker is rewriting addresses on this host; the allowed-senders list cannot tell devices apart then. Run the container with `network_mode: host`, or put the allowed senders rule on the host firewall.

Without Docker (systemd install): the server listens on `server.host`, so the port is reachable as soon as the source exists. Open it in the host firewall for the sending networks only.

## 3. Point devices at it

| Device | Setting |
|---|---|
| rsyslog (Linux, Proxmox) | `*.* @remnant.example.internal:5514` (UDP) or `*.* @@remnant.example.internal:5514` (TCP). For octet counting add `;RSYSLOG_SyslogProtocol23Format` and `TCP_Framing="octet-counted"` with an `omfwd` action |
| syslog-ng | `destination d_remnant { network("remnant.example.internal" port(5514) transport("tcp")); };` |
| UniFi | Settings > CyberSecure or System > Remote syslog: server and port 5514 |
| pfSense / OPNsense | Status > System Logs > Settings > Remote logging: `remnant.example.internal:5514` |
| Palo Alto | Device > Server Profiles > Syslog: UDP or TCP 5514, or SSL 6514 with Remnant's certificate imported as a CA |
| FortiGate | `config log syslogd setting`, `set server`, `set port 5514`, `set mode reliable` for TCP |

For TLS, the sender must trust Remnant's certificate: the one you configured, or the generated self-signed `data/tls/server.crt` (its SHA-256 fingerprint is printed at start-up).

## 4. Check it

1. Send a test line from a Linux machine on an allowed network:
   ```
   logger -n remnant.example.internal -P 5514 -d "remnant listener test"      # UDP
   logger -n remnant.example.internal -P 5514 -T "remnant listener test"      # TCP
   ```
2. Within a minute, **Search** `source:firewall "listener test"`. `raw` is the message exactly as sent; `device_ip` is the sender's address when the message did not carry one.

## What the counts mean

| Shown | Meaning |
|---|---|
| received | Messages stored for parsing |
| refused | Messages (UDP) or connections (TCP, TLS) from addresses outside the allowed senders |
| dropped (spool full) | Remnant fell behind by more than 512 MB, or more than 100 connections were open. Check the Health page |

## Limits and security notes

- If the server crashes or the disk fills in the middle of writing a message to its spool, the rest of that hour's spool file is set aside as `data/spool/<source>/<hour>.syslog.damaged` and the source shows an error once. Delete the file when you have looked at it.

- UDP and TCP syslog are plain text and unauthenticated: anyone on an allowed network can send messages that claim any host name. `device_ip` records the address the message really came from. Use TLS and a tight allowed-senders list for anything that matters.
- Messages over 64 KB are cut and marked truncated.
- Idle TCP connections close after 10 minutes; senders reconnect on their own.
- Mutual TLS (client certificates) is not supported yet.
