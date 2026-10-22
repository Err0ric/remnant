# dns_powerdns fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | PowerDNS Authoritative 4.8 (`log-dns-queries=yes`) and Recursor 4.9 and 5.x (`quiet=no`, text and structured logging) |
| Collector shape | rsyslog 8.2312, tags `pdns_server`, `pdns_recursor`, `pdns-recursor` |
| Generator | `scripts/fixtures/access_pack.py dns_powerdns` (seed 46) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | PowerDNS docs: log-dns-queries, Recursor logging and structured logging. |

Authoritative queries with cache hit or miss, recursor questions in the text and structured forms, including AI service names, and one startup line that keeps only its envelope. Pathological: 9,000 pipes, 3,000 `qname="`, an out-of-range port.
