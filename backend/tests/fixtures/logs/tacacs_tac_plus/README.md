# tacacs_tac_plus fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | tac_plus F4.0.4 (shrubbery) with accounting to syslog |
| Collector shape | rsyslog 8.2312 from tac_plus, RFC 3164 with PRI |
| Generator | `scripts/fixtures/access_pack.py tacacs_tac_plus` (seed 42) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | tac_plus man pages and mailing list examples of the accounting record layout. |

Login and enable queries accepted and rejected, accounting start, stop, and command records (tab separated), one `connect from` line, and one config line that keeps only its envelope. Pathological: 9,000 quotes, 5,000 tabs, 3,000 `cmd=` attributes.
