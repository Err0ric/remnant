# vault_server fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | HashiCorp Vault 1.17 operational log, default text format |
| Collector shape | journald to rsyslog 8.2312, tag `vault` |
| Generator | `scripts/fixtures/access_pack.py vault_server` (seed 44) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | Vault docs: server log format and log levels. |

INFO, WARN, and ERROR lines from core, expiration, identity, and storage.raft, and one banner line that keeps only its envelope. Pathological: a 9 KB component, an impossible timestamp, 5,000 brackets.
