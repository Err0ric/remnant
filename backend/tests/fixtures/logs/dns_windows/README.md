# dns_windows fixtures

| | |
|---|---|
| Source product | Windows Server 2022 DNS Server |
| Collector shape | The debug log file (`dns.log`) with packet logging on, read directly from disk; no syslog header |
| Generator | `scripts/fixtures/starter_pack.py dns_windows` (seed 44) |
| Values | Synthetic names under example.com, example.org, and example.net; RFC 1918 clients |

Alternating received queries and sent responses, including NXDOMAIN answers for a random-looking name. One in five lines uses a 24-hour ISO-style date instead of the US 12-hour form. Pathological: the file header block, a non-PACKET EVENT line, an impossible date, a 9 KB question name, and a truncated PACKET line.
