# openvpn_server fixtures

**Built from vendor docs, verify on real data.** Line shapes come from public vendor documentation and published examples, not from captured logs.

| | |
|---|---|
| Source product | OpenVPN Access Server 2.13 (`[OVPN n] OUT:` wrapper) and OpenVPN 2.6 community server |
| Collector shape | rsyslog 8.2312, tags `openvpnas` and `openvpn` |
| Generator | `scripts/fixtures/access_pack.py openvpn_server` (seed 45) |
| Values | Synthetic users and hosts, RFC 1918 internal and RFC 5737 external addresses |
| Based on | OpenVPN Access Server and OpenVPN 2.6 docs and forum examples of server log lines. |

Connections established (Access Server wrapped and community), tunnel addresses handed out, client disconnects, username/password verification failures, and one startup line that keeps only its envelope. Pathological: 9,000 quotes, 4,000 `a/` prefixes, an out-of-range port.
