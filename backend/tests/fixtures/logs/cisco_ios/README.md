# cisco_ios fixtures

| | |
|---|---|
| Source product | Cisco IOS 15.x and IOS XE 17.x with `service timestamps log datetime msec` |
| Collector shape | Direct (`<PRI>seq: host: *Mmm dd hh:mm:ss.mmm: %...`) and through rsyslog |
| Generator | `scripts/fixtures/starter_pack.py cisco_ios` (seed 32) |
| Values | RFC 1918 and RFC 5737 addresses, invented users |

Covers SEC_LOGIN success and failure, SSH2_USERAUTH, SEC IPACCESSLOGP, SYS CONFIG_I, and LINK UPDOWN. Pathological lines: a 9 KB facility, an out-of-range port, 3,000 sequence numbers, and an impossible date.
