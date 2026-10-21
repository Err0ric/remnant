# cef_generic fixtures

| | |
|---|---|
| Source product | CEF 0 as emitted by firewalls, IDS sensors, and proxies (ArcSight CEF Implementation Standard) |
| Collector shape | rsyslog 8.2312 (RFC 3164, where `CEF:` reads as the tag) and RFC 5424 |
| Generator | `scripts/fixtures/starter_pack.py cef_generic` (seed 23) |
| Values | Invented vendors (ExampleCorp, ExampleSec), RFC 1918 and RFC 5737 addresses |

Escaped pipes in the header, an escaped `=` in an extension value, numeric severities 0 to 10. Pathological: 4,000 escaped pipes, 4,000 bare `a=` keys, an out-of-range port, and a truncated header.
