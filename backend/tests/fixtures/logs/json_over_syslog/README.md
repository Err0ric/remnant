# json_over_syslog fixtures

| | |
|---|---|
| Source product | Applications logging one JSON object per message (structlog, logrus, and similar), some with the `@cee:` cookie |
| Collector shape | rsyslog 8.2312, RFC 3164 and RFC 5424 |
| Generator | `scripts/fixtures/starter_pack.py json_over_syslog` (seed 25) |
| Values | Synthetic users, RFC 1918 addresses |

Nested request objects are kept in `unmapped`. One plain-text line keeps only its envelope. Pathological: 9,000 open braces, a lone surrogate escape with NaN and 1e999, a huge port string, and a `@cee:` cookie without JSON.
