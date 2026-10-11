# Point syslog-ng at Remnant

syslog-ng receives syslog from your devices and writes files; Remnant tails the folder. Any Linux machine with syslog-ng, including the Remnant VM itself, can be the collector.

**Tested** 2026-10-10 with syslog-ng 4.3.1 on Ubuntu 24.04: UDP and TCP, RFC 3164 and RFC 5424 senders, a hostile program name, folder tailed by Remnant, live lines visible within seconds.

## 1. Install

```bash
sudo apt install syslog-ng        # pulls in syslog-ng-scl, which step 2 needs
```

On Debian and Ubuntu this replaces rsyslog. Use one or the other.

## 2. Receive and write one file per sender and program

Create `/etc/syslog-ng/conf.d/remnant.conf`:

```
@include "scl.conf"

# Accepts both RFC 3164 and RFC 5424 senders on UDP and TCP 514.
source s_remnant_net {
  default-network-drivers(udp-port(514) tcp-port(514) rfc5424-tcp-port(601));
};

# One folder per sending IP, one file per program, written as RFC 5424 lines.
destination d_remnant_files {
  file("/var/log/remote/${SOURCEIP}/$(sanitize --invalid-chars '/.' ${PROGRAM}).log"
       template("<${PRI}>1 ${ISODATE} ${HOST} ${PROGRAM:--} ${PID:--} ${MSGID:--} ${SDATA:--} ${MSG}\n")
       create-dirs(yes) dir-perm(0750) perm(0640) group("adm") dir-group("adm"));
};

log { source(s_remnant_net); destination(d_remnant_files); flags(final); };
```

Check and apply:

```bash
sudo syslog-ng --syntax-only        # no output means OK
sudo systemctl restart syslog-ng
```

Why these choices (each was found or confirmed in testing):

| Choice | Reason |
|---|---|
| `default-network-drivers()` | A plain `network()` source assumes RFC 3164. Modern senders using RFC 5424 were mangled in testing: the program name became `1`. This driver detects both formats |
| `${ISODATE}` in an RFC 5424 template | Adds the year and time zone that RFC 3164 devices leave out |
| `${SOURCEIP}` for the folder | The address that actually sent the packet, not a hostname the sender can claim |
| `sanitize --invalid-chars '/.'` | A program name like `../../etc/evil` becomes `______etc_evil.log`. Without the dot, syslog-ng silently dropped those messages in testing, which would let a sender hide lines |
| `group("adm")` | Remnant's container reads logs as group `adm`, the same as rsyslog's files. Without it the files are `root:root` and Remnant cannot read them |

The original program name is kept inside each line, so searches still see `../../etc/evil` exactly as sent. Only the file name is sanitized.

`default-network-drivers()` also opens a TLS listener on 6514 and logs a warning that no certificate is set. It is harmless; nothing can connect without a certificate.

## 3. Send logs to it

Linux senders running syslog-ng, `/etc/syslog-ng/conf.d/forward.conf`:

```
destination d_collector { syslog("COLLECTOR_IP" transport("tcp") port(601)); };
log { source(s_src); destination(d_collector); };
```

Senders running rsyslog: see [rsyslog.md](rsyslog.md), step 2. Network devices: remote syslog to `COLLECTOR_IP`, port 514.

Quick test from any Linux box:

```bash
logger --server COLLECTOR_IP --port 514 --tcp -t sshd "test message from $(hostname)"
ls /var/log/remote/*/
```

## 4. Lock it down

Limit ports 514 and 601 to your senders:

```bash
sudo ufw allow from 192.0.2.0/24 to any port 514
sudo ufw allow from 192.0.2.0/24 to any port 601 proto tcp
```

## 5. Add the folder in Remnant

Same as the rsyslog guide, step 4: `LOGS_DIR=/var/log/remote` in `.env`, then **Configuration > Sources > Add source** with format **Syslog**, path `/logs`, file pattern `**/*.log`.

Rotation: the logrotate example in [rsyslog.md](rsyslog.md) step 5 works here too; replace the `postrotate` command with `syslog-ng-ctl reopen`.
