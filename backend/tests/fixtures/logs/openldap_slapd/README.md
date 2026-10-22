# openldap_slapd fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | OpenLDAP slapd 2.5 and 2.6, `olcLogLevel: stats` |
| Collector shape | rsyslog 8.2312, facility local4, tag `slapd` |
| Generator | `scripts/fixtures/access_pack.py openldap_slapd` (seed 47) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | OpenLDAP admin guide (logging, stats level) and published examples of failed binds (err=49). |

Connection sequences: ACCEPT, BIND request, BIND mech line on success, RESULT tag=97 with err=0 or err=49, a search, and closed; one startup line keeps only its envelope. Pathological: 9,000 quotes in a DN, an oversized conn number, 5,000 colons.
