# server_events fixtures

| | |
|---|---|
| Source product | This server's own sign-ins, changes, and refusals (ADR-0040, handoff item 9), `app/ingest/server_events.py` |
| Collector shape | Spooled JSON lines in the OTLP spool's record shape, written by the server itself |
| Generator | `scripts/fixtures/server_events.py` (seed 40) |
| Values | RFC 5737 and documentation IPv6 addresses, invented user names, user ids, token ids, and prefixes |

Sixty events: successful sign-ins (password and single sign-on), API requests that change something or export (method, route template, status, duration), and refusals of ingest tokens (unknown and revoked), sign-ins (some rate limited), single sign-on, and API tokens. Pathological lines cover a very long address and user name, a huge method with a non-numeric status, a list where an outcome belongs, a bad time, a null attr, binary garbage, and broken JSON.
