# server_events fixtures

| | |
|---|---|
| Source product | This server's own refusal events (ADR-0040), `app/ingest/server_events.py` |
| Collector shape | Spooled JSON lines in the OTLP spool's record shape, written by the server itself |
| Generator | `scripts/fixtures/server_events.py` (seed 40) |
| Values | RFC 5737 and documentation IPv6 addresses, invented user names, token ids, and prefixes |

Sixty refusals: ingest tokens (unknown and revoked), sign-ins (some rate limited), single sign-on, and API tokens. Pathological lines cover a very long address and user name, a bad time, a null attr, binary garbage, and broken JSON.
