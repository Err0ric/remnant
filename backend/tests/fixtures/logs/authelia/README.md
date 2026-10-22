# authelia fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | Authelia 4.38, `log.format: text` and `json` |
| Collector shape | Docker or systemd to rsyslog 8.2312, RFC 3164 with PRI |
| Generator | `scripts/fixtures/access_pack.py authelia` (seed 41) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | Authelia docs: logging configuration, regulation; message wording from the 1FA and 2FA handlers. |

First-factor and second-factor attempts (1FA, TOTP, WebAuthn, Duo) in both outcomes, regulation bans, access forbidden by a rule, JSON-format lines, and one startup line (a base event). Pathological: 4,000 escaped quotes, a 9 KB user name, 5,000 open braces.
