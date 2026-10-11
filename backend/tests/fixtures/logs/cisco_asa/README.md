# cisco_asa fixtures

| | |
|---|---|
| Source product | Cisco ASA 9.x (also FTD LINA) |
| Collector shape | Direct from the ASA, with `logging timestamp` (`Oct 09 2026 20:41:12:` form), and through rsyslog with a hostname |
| Generator | `scripts/fixtures/starter_pack.py cisco_asa` (seed 31) |
| Values | RFC 1918 and RFC 5737 addresses, invented users and ACL names |

Covers 302013 built, 302014 teardown, 106023 ACL deny, 113004 and 113005 AAA, 605005 management login, and one id the template does not model. Message shapes follow the Cisco ASA Series Syslog Messages guide. Pathological lines: 4,000 interface separators, an out-of-range port, a 9 KB ACL name, and 4,000 separators after "Rejected".
