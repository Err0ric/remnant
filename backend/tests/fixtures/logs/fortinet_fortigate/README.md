# fortinet_fortigate fixtures

| | |
|---|---|
| Source product | FortiOS 7.2 and 7.4 (FortiGate 60F class), syslog format "default" |
| Collector shape | FortiGate sends `<PRI>` followed directly by key=value pairs, with no syslog header |
| Generator | `scripts/fixtures/starter_pack.py fortinet_fortigate` (seed 26) |
| Values | Invented device names and serials, RFC 1918 and RFC 5737 addresses |

Forward traffic (close, accept, timeout), local-in denies, SSL VPN login failures, and user authentication successes. `eventtime` cycles through seconds, milliseconds, and nanoseconds to cover FortiOS releases. Pathological: 3,000 escaped quotes, 2,400 pairs, out-of-range numbers, and an unterminated quote.
