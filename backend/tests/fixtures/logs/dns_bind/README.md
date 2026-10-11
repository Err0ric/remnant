# dns_bind fixtures

| | |
|---|---|
| Source product | ISC BIND 9.16 and 9.18, `logging { category queries { ... } }` |
| Collector shape | rsyslog 8.2312 from named, RFC 3164 with PRI |
| Generator | `scripts/fixtures/starter_pack.py dns_bind` (seed 28) |
| Values | `example.*` domains, RFC 1918 addresses |

Queries with and without the `@0x...` client object, and with and without a view. One zone-load line keeps only its envelope. Pathological: 9,000 `@`, an out-of-range port, and 5,000 open parentheses.
