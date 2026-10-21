# dns_unbound fixtures

| | |
|---|---|
| Source product | Unbound 1.17+ with `log-queries: yes` and `log-replies: yes` |
| Collector shape | rsyslog 8.2312 from unbound, RFC 3164 with PRI |
| Generator | `scripts/fixtures/starter_pack.py dns_unbound` (seed 29) |
| Values | `example.*` domains, RFC 1918 addresses |

Alternating query and reply lines (NOERROR, NXDOMAIN). One module notice keeps only its envelope. Pathological: a 9 KB name, a 5,000-digit duration, and 9,000 spaces.
