# Point Vector at Remnant

Vector receives syslog and writes files; Remnant tails the folder.

**Status: config checked against the Vector 0.60 reference docs and vector.dev (2026-10-10), not yet run.** Vector releases could not be downloaded in the build environment. Run it once on the homelab VM ([homelab test plan](../install/homelab-test.md), part 4) and update this line with the version and date.

## 1. Receive and write one file per sender

`/etc/vector/vector.yaml`:

```yaml
sources:
  syslog_udp:
    type: socket
    mode: udp
    address: 0.0.0.0:514
    framing:
      method: bytes               # one event per datagram
  syslog_tcp:
    type: socket
    mode: tcp
    address: 0.0.0.0:514
    framing:
      method: newline_delimited   # use octet_counting for RFC 6587 senders

transforms:
  sender:
    type: remap
    inputs: [syslog_udp, syslog_tcp]
    source: |
      # Vector's docs describe host both as the IP and as ip:port. Strip a port only
      # when one is present, so each sender gets one folder, never one per connection.
      h = string!(.host)
      if match(h, r'^[^:]+:\d+$') { h = replace(h, r':\d+$', "") }                        # 192.0.2.10:51515
      if match(h, r'^\[.+\]:\d+$') { h = replace(replace(h, r'\]:\d+$', ""), r'^\[', "") }  # [2001:db8::5]:51515
      .sender = h

sinks:
  remnant_files:
    type: file
    inputs: [sender]
    base_dir: /var/log/remote
    path: "/var/log/remote/{{ sender }}/syslog.log"
    encoding:
      codec: text      # writes the line exactly as received
```

```bash
sudo vector validate /etc/vector/vector.yaml
sudo systemctl restart vector
```

Why these choices:

| Choice | Reason |
|---|---|
| `socket` source, `text` output | The exact received line is written. Remnant parses the envelope itself and keeps the line as `raw`. Vector's `syslog` source would parse and re-shape it first |
| Strip the port from `host` only when present | Vector's docs describe `host` both as the IP and as `address:port`. Stripping blindly would cut the last group off a bare IPv6 address; not stripping would create a folder per TCP connection |
| `base_dir` | Vector refuses to write outside this folder, whatever the event fields contain |
| One file per sender | There is no program name to split on without parsing. Remnant still extracts it per line |

Old RFC 3164 devices send no year or time zone. Set the source's **Time zone** in Remnant to the devices' zone; the year is filled in safely across New Year.

## 2. Permissions

Vector runs as user `vector`. Let Remnant read the files:

```bash
sudo mkdir -p /var/log/remote && sudo chown vector:adm /var/log/remote && sudo chmod 2750 /var/log/remote
```

The setgid bit (`2750`) makes new folders and files inherit group `adm`, which Remnant's container joins (`LOGS_GID=4`).

## 3. Send, lock down, and add in Remnant

Senders, firewall rules, the Remnant source, and rotation are the same as in [rsyslog.md](rsyslog.md), steps 2 to 5. Use **File pattern** `**/*.log`.
