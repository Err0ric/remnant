# m365_signin fixtures

| | |
|---|---|
| Source product | Microsoft Graph v1.0 auditLogs/signIns |
| Collector shape | One Graph resource per line, as the Microsoft 365 connector stores it |
| Generator | `scripts/fixtures/connectors.py` (seed 42) |
| Values | example.com users, invented ids, RFC 5737 and 2001:db8::/32 addresses |

Pathological lines cover empty and truncated JSON, wrong types, a 10 KB value, non-object
JSON, control characters, and a multiline fragment.
