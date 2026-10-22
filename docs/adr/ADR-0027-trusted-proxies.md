# ADR-0027: Trusted proxies for the client address

Status: **Accepted** 2026-10-21 (project owner: default empty; the peer must be listed before `X-Forwarded-For` is read; walk from the right and take the first untrusted address; IPs and CIDRs, because the proxy is an HA pair whose traffic comes from the node addresses, not the VIP; log the effective list at startup). Recorded as SPEC D77; threats T58 and T59 added.

## Context

A first install on a real host put the server behind a reverse proxy on another machine, the normal shape for a team install (TLS on the proxy, often with forward-auth in front). The server runs uvicorn with `proxy_headers=False`, and every place that needs the client address reads the TCP peer (`request.client.host` in `api/access.py` and `api/middleware.py`, 78 `client_ip(...)` call sites in all). Behind a proxy that peer is always the proxy, so:

| Effect | Why it matters |
|---|---|
| The failed-login limiter keys `ip:<addr>` and `user-ip:<name>\|<addr>` collapse into one shared key | A few failed logins from anyone (a typo, a stale saved password, an attacker) lock **every** user who signs in through that proxy out for the window (300 s by default). The setup, invite, and reset link limiter has the same problem. The limiter was designed so one address cannot lock out others; a proxy defeats that |
| Audit rows and request logs record the proxy's address for every login and action | Attribution by user id still holds, but address-based investigation (where did this login come from) is lost |

Trusting `X-Forwarded-For` from anyone is not an option: a direct client could set it to any value, rotate it per attempt to dodge the limiter, and write false addresses into the audit log.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Setting | `server.trusted_proxies` (`APP__SERVER__TRUSTED_PROXIES`, `TRUSTED_PROXIES` in the Compose `.env`): a list of IP addresses or CIDRs, comma separated in the environment. **Default empty**. For an HA proxy pair, list both node addresses (or their subnet) and the VIP: requests arrive from a node | Nothing changes for installs without a proxy; trust is a deliberate admin act | Auto-detect (cannot be done safely) |
| 2 | Empty list | Today's behavior: forwarded headers are ignored, the client address is the TCP peer | Safe default | |
| 3 | Which header | `X-Forwarded-For` only. `Forwarded` (RFC 7239), `X-Real-IP`, `X-Forwarded-Proto`, and `X-Forwarded-Host` are ignored | One header every common proxy sets, one parser to test. Scheme and host already come from `server.public_url`, so trusting proto and host headers would add risk for nothing | Accept every variant (more parsing, more ways to get it wrong) |
| 4 | How the address is chosen | Only when the TCP peer is in the list. Read every `X-Forwarded-For` header in order, split on commas, and walk from the **right**: skip entries that are themselves trusted proxies, take the first one that is not. If every entry is trusted, use the leftmost. A malformed entry stops the walk and the peer address is used | Each proxy appends the address it saw on the right, so the rightmost untrusted entry is the first one a trusted proxy vouched for. Entries further left were written by the client and can be anything | Leftmost entry (the classic spoofing bug) |
| 5 | Where it applies | One small ASGI middleware, outermost, that rewrites only `scope["client"]`. Every existing reader of `request.client` (limiter keys, audit rows, request log, setup and SSO flows) then gets the resolved address with no other code change | One place to review and test; future code cannot forget to call a helper | uvicorn `ProxyHeadersMiddleware` (also rewrites the scheme from `X-Forwarded-Proto`, which this ADR does not want); a helper at 78 call sites |
| 6 | Validation | Each entry must parse as `ipaddress.ip_network(..., strict=False)`. An invalid entry refuses to start with the bad value named. `0.0.0.0/0` and `::/0` are refused (that is "trust everyone") | A typo fails loudly instead of silently trusting nothing or everything | Warn and continue |
| 7 | Visibility | Startup logs one line: `Trusted proxies: 192.0.2.10, 192.0.2.11` or `Trusted proxies: none (forwarded headers ignored)`. The request log keeps both values when they differ: `client` (resolved) and `peer` (TCP) | An admin can see at a glance whether the setting took effect, and an investigator can see which proxy carried a request | |
| 8 | Docs | `tls.md` proxy examples add `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` and the setting; `team-vm.md` adds a commented line. The guide says to list the proxy nodes only, never a whole client subnet | | |

## Consequences

- Behind a correctly configured proxy, failed logins from one person no longer lock out everyone else, and audit rows show the real client address.
- Misconfiguration risk: listing a client subnet as trusted lets clients in it spoof their address. The guide says to list proxy nodes only, the catch-all ranges are refused, and the startup line shows exactly what is trusted.
- The setting does not authenticate anything. A trusted proxy only vouches for an address; sign-in, roles, and source access are unchanged.
- No schema change, no new dependency.

## Threat model (SPEC section 7)

| Id | Threat | ATT&CK | Mitigation |
|---|---|---|---|
| T58 | Reverse proxy collapses every client into one address: one person's failed logins lock everyone out, and audit rows lose the client address | T1110 Brute Force, T1078 Valid Accounts | `server.trusted_proxies`; address resolved from `X-Forwarded-For` only when the peer is trusted, walked from the right |
| T59 | Client forges `X-Forwarded-For` to dodge the login limiter or plant a false address in the audit log | T1110, T1070 Indicator Removal | Header ignored unless the TCP peer is a listed proxy; rightmost untrusted entry only; catch-all ranges refused; request log keeps the TCP peer too |

Extends T9 (exposed web UI) and T18 (attribution).

## Tests

Unit, table-driven, for the resolver: empty list; untrusted peer with a spoofed header; trusted peer with one entry; two chained trusted proxies; every entry trusted; malformed entry; multiple header lines; IPv6 and IPv4-mapped IPv6; invalid CIDR and catch-all refused at config load. Integration: through a trusted peer, five failed logins from client A do not block client B, and an audit row records A's address; from an untrusted peer, the header changes nothing.

