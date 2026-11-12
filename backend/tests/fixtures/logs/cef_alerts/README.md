# cef_alerts fixtures

| | |
|---|---|
| Source product | Security alerts in CEF 0 from invented products (ExampleCorp EdgeSensor, ExampleSec NetWatch) |
| Collector shape | rsyslog 8.2312 (RFC 3164, where `CEF:` follows the host) and RFC 5424 |
| Generator | `scripts/fixtures/starter_pack.py cef_alerts` (seed 31) |
| Values | Invented products and hosts, people alice to dave, RFC 1918 and RFC 5737 addresses |

Every line carries `externalId`; every sixth is a resend of an earlier alert ID, sometimes at a higher severity (the 0c linked-item case). Pathological: 4,000 escaped pipes, a 10 KB alert ID, a text severity the map does not know, an alert with no entity, and a truncated header.
