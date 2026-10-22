# vault_audit fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | HashiCorp Vault 1.17, file audit device with `log_raw=false`, and the syslog audit device |
| Collector shape | rsyslog 8.2312, tag `vault`, RFC 3164 with PRI |
| Generator | `scripts/fixtures/access_pack.py vault_audit` (seed 43) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | Vault docs: audit log entry schema. |

Request and response entries (read, list, update, delete), permission-denied errors on `sys/` paths. Pathological: 3,000 nested arrays, a 9 KB display name, a bad time and a numeric operation.
