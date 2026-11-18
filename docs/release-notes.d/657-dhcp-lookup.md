### Who had this address: the interface, lease ended lines, one row per lease (2026-11-17)

- The library query "Who had this address" (`who_had_ip`) now fills its interface column whether the firewall writes the interface quoted (`interface "vlan20"`) or not (`interface ae0.120`).
- It finds leases and VPN tunnels with a start or end line in the time range: it reads "lease ended" lines as well as "lease started" lines, so a lease that started before the range shows from its end line. A lease with neither line in the range is not found.
- It gives one row per DHCP lease or VPN tunnel, newest first, with the first and last time it was seen in the range (`first_seen`, `last_seen`), in place of one row per log line. A row ends at the next holder's start, even when its end line is logged later.
- Its description now says it reads the time range only; it said it looked back 7 days before the range, which it never could.
- What you will notice: "Who had this address" shows the interface and each lease's first and last time seen, and finds leases with a start or end line in the range.
- What changes for existing installs: lines already stored show the interface and their end times too, since the query reads the stored description; no reparse is needed. A copy saved with Save as my own keeps the old query until you use Replace my copy.
