# Point rsyslog at Remnant

Remnant reads log files from folders. rsyslog receives syslog from your devices and writes those files. This guide turns any Linux machine with rsyslog (including the Remnant VM itself) into that collector.

**Tested** 2026-10-10 with rsyslog 8.2312.0 on Ubuntu 24.04: UDP, TCP, and legacy RFC 3164 senders, folder tailed by Remnant, live lines visible within seconds.

## 1. Receive and write one file per sender and program

Create `/etc/rsyslog.d/10-remnant.conf`:

```
module(load="imudp")
module(load="imtcp")

# One folder per sending IP, one file per program: /var/log/remote/192.0.2.10/sshd.log
template(name="RemnantPath" type="string"
         string="/var/log/remote/%FROMHOST-IP%/%PROGRAMNAME:::secpath-replace%.log")

ruleset(name="remnant_remote") {
  action(type="omfile" dynaFile="RemnantPath"
         template="RSYSLOG_SyslogProtocol23Format"
         dirCreateMode="0750" fileCreateMode="0640")
}

input(type="imudp" port="514" ruleset="remnant_remote")
input(type="imtcp" port="514" ruleset="remnant_remote")
```

Check and apply:

```bash
sudo mkdir -p /var/log/remote
sudo rsyslogd -N1                 # config check, expect "End of config validation run"
sudo systemctl restart rsyslog
```

Why these choices:

| Choice | Reason |
|---|---|
| `RSYSLOG_SyslogProtocol23Format` (RFC 5424 output) | rsyslog adds the year and time zone that old RFC 3164 devices leave out, so timestamps are never guessed |
| `%FROMHOST-IP%` for the folder | The address that actually sent the packet. The hostname inside a message can be anything the sender claims |
| `secpath-replace` | A program name like `../../etc` cannot escape the folder |
| A separate ruleset | Remote logs stay out of the machine's own `/var/log/syslog` |

## 2. Send logs to it

On each Linux sender, `/etc/rsyslog.d/90-forward.conf`:

```
*.* action(type="omfwd" target="COLLECTOR_IP" port="514" protocol="tcp"
           action.resumeRetryCount="-1" queue.type="LinkedList" queue.size="10000")
```

Then `sudo systemctl restart rsyslog`. TCP with a queue survives collector restarts; use `protocol="udp"` only for devices that cannot do TCP.

Network devices (firewalls, switches, access points, Proxmox): set the remote syslog server to `COLLECTOR_IP`, port 514.

Quick test from any Linux box:

```bash
logger --server COLLECTOR_IP --port 514 --tcp -t sshd "test message from $(hostname)"
ls /var/log/remote/*/
```

## 3. Lock it down

Anyone who can reach port 514 can write log lines. Limit it to your senders:

```bash
sudo ufw allow from 192.0.2.0/24 to any port 514 proto tcp
sudo ufw allow from 192.0.2.0/24 to any port 514 proto udp
```

Remnant treats every line as untrusted input, but a flood of fake lines still costs disk and attention.

## 4. Add the folder in Remnant

1. Give Remnant read access:
   - Docker: set `LOGS_DIR=/var/log/remote` in `.env`. It is mounted read-only at `/logs`, and the container joins group `adm` (`LOGS_GID=4`) because rsyslog on Debian and Ubuntu writes files as `syslog:adm`, mode 0640. On other distributions check with `stat -c %g /var/log/remote/*/*.log` and set `LOGS_GID` to match.
   - Without Docker: set `APP__PATHS__ALLOWED_ROOTS=/var/log/remote` and add the service account to the group: `sudo usermod -aG adm <user>`.
2. **Settings > Sources and connectors > Add source**: format **Syslog**, path `/logs` (Docker) or `/var/log/remote`, file pattern `**/*.log`.
3. Status shows **Reading** within a few seconds; new lines are picked up as rsyslog writes them.

## 5. Rotation

Remnant handles both logrotate styles (rename and `copytruncate`). A typical `/etc/logrotate.d/remote`:

```
/var/log/remote/*/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
```

Keep `delaycompress` so the most recent rotated file stays readable while Remnant finishes it. Retention inside Remnant is set per source and is independent of how long rsyslog keeps the files.
