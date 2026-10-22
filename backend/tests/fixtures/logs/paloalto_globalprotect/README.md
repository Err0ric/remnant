# paloalto_globalprotect fixtures

| | |
|---|---|
| Source product | Palo Alto Networks PAN-OS 10.2 and 11.x, GLOBALPROTECT log |
| Collector shape | Syslog server profile, BSD and IETF formats |
| Generator | `scripts/fixtures/starter_pack.py paloalto_globalprotect` (seed per template) |
| Field order | PAN-OS syslog field descriptions (docs.paloaltonetworks.com, PAN-OS 11.0, and 10.2 for traffic) |
| Values | Serial 012345678901, device pa-fw01, RFC 1918 and RFC 5737 addresses, invented users |

Lines carry 0, 20, or 40 extra trailing columns, as newer releases add them. The template keeps those in `_extra` without marking the line partial. Quoted cells with embedded commas are included. Pathological lines: 9,000 commas, an unterminated quote, impossible dates and ports, and a truncated line.

Firewalls in three zones: every third line is from a UTC firewall with no high-resolution timestamp, the others from Pacific (America/Los_Angeles) and India (Asia/Kolkata, +05:30) firewalls whose Generated Time is local and whose high-resolution timestamp carries the offset. expected.jsonl holds the true UTC time for each (D85).
