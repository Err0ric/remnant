# leef_generic fixtures

| | |
|---|---|
| Source product | LEEF 1.0 and 2.0 (IBM QRadar LEEF specification) |
| Collector shape | rsyslog 8.2312, RFC 3164 (where `LEEF:` reads as the tag) |
| Generator | `scripts/fixtures/starter_pack.py leef_generic` (seed 24) |
| Values | Invented vendors, RFC 1918 and RFC 5737 addresses |

LEEF 1.0 with tabs, LEEF 2.0 with a caret delimiter and with a hex `x09` delimiter. Pathological: 9,000 delimiters, 2,500 attributes, and an unknown LEEF version.
