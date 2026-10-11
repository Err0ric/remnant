# unifi fixtures

| | |
|---|---|
| Source product | UniFi Security Gateway (USG-Pro, kernel iptables log) and UniFi OS gateways (UDM-SE, Network 8.x) |
| Collector shape | Remote syslog from the gateway, RFC 3164 with PRI |
| Generator | `scripts/fixtures/starter_pack.py unifi` (seed 27) |
| Values | Documentation MAC addresses (00:00:5e:00:53:xx), RFC 1918 and RFC 5737 addresses |

WAN_IN and WAN_LOCAL drops (USG format, tag `kernel:`), LAN_IN accepts with `DESCR` (UniFi OS format, no tag), and ICMP with no ports. Pathological: a 9 KB rule name, 2,400 extra fields, and an out-of-range port.
