# anthropic_reports fixtures

| | |
|---|---|
| Source product | Anthropic Admin API usage and cost reports, Claude Code analytics, Enterprise analytics, Compliance activities |
| Collector shape | One {"feed": "anthropic.<feed>", ...} JSON line per record, made by the connector record function |
| Generator | `scripts/fixtures/connectors.py` (seed 42) |
| Values | example.com users, invented ids, RFC 5737 and 2001:db8::/32 addresses |

Pathological lines cover empty and truncated JSON, wrong types, a 10 KB value, non-object
JSON, control characters, and a multiline fragment.
