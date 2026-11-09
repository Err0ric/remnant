# ADR-0048: Firewall user-to-IP attribution for AI usage

Status: **Accepted** 2026-11-08 (owner: all eight proposed defaults in the open questions accepted, with two additions, recorded in rows P1 to P3 and U1 to U3 below). Follows D222 (owner, 2026-11-08: in scope as the next slice; ADR first, no code until it is accepted). Builds on ADR-0020 row 1 and ADR-0029 (D107), which it amends where the rows below say so. Threats T71 to T76 are in SPEC 7.1.

## Context

Most AI use a small team can see arrives as firewall, DNS, or proxy traffic, and a traffic row names an address: "10.20.1.5 to chatgpt.com, 412 sessions". A solo security lead at about 200 people needs a person ("alice@example.com, on ws-014.corp.internal"), and needs to trust that name enough to act on it, because acting on the wrong name is worse than having none.

What exists today (`backend/app/search/addresses.py`, ADR-0020 row 1, ADR-0029 part 1):

| Piece | State |
|---|---|
| Spans per address from successful logons (OCSF 3002), Palo Alto User-ID, GlobalProtect tunnel addresses, Palo Alto DHCP leases, with ends (logout, next holder) and caps (12 or 24 hours) | Built |
| Person through a device: a Microsoft 365 sign-in on a DHCP-named machine, only when one person signed in (row 5a) | Built, the only place that says "several" |
| How each match was made (`rwho_how`, `rwho_at`, `rwho_capped`, `rwho_src`) | Computed in `addr`, then dropped: AI usage's `r` CTE keeps only `rwho` and `rhost` |
| The firewall's own user on a traffic row (Palo Alto `source_user`, FortiGate `user`, mapped to `actor_user_name`) | Used first (`who0`) but never labelled as coming from the firewall |
| Corrections by an admin (ADR-0029 C3), View people in AI usage (G1 to G6) | Accepted, not built |
| FortiGate, UniFi, Windows DHCP Server leases | Accepted in ADR-0029 row 1, not built |

Where the current rules guess, which D222 and ADR-0029 C1 ("no guess is shown as fact") do not allow:

1. **One holder per address and hour.** `addr_u` takes the strongest kind, then the newest span, for the whole hour. A handover at 09:30 names the 09:40 holder for an event at 09:10.
2. **Concurrent holders collapse.** Spans are partitioned by kind and address, and the next mapping ends the previous one. On a terminal server, where Palo Alto's Terminal Server agent maps one address to many users by port range, 30 people look like one person who changes every few seconds, and the newest wins.
3. **Kinds that disagree are not shown.** A User-ID login for bob silently outranks a logon for alice on the same address in the same hour.
4. **Ends ignore what the firewall logged.** A User-ID login carries the mapping's timeout (`time_out_threshold`), but the span runs to the fixed 12-hour cap, long after the firewall itself forgot the mapping.
5. **Any successful logon counts.** A network logon (type 3) from a file server's address names whoever connected to it, and a logon from a jump host or terminal server names whoever logged on last.
6. **Address forms.** Public addresses (egress, NAT) and shared internal addresses (a DNS forwarder, a proxy, a NAT gateway for a lab segment) can carry many people. Only Microsoft 365 sign-in addresses are excluded today.

## Decision

### Sources of IP-to-user facts

| # | Source | Gives | Kind and precedence | Change from today |
|---|---|---|---|---|
| S1 | The firewall's user on the traffic row itself (Palo Alto `source_user` in `paloalto_traffic` and `paloalto_threat`, FortiGate `user` on traffic logs) | Person for that session, decided by the firewall at session time, per port on a terminal server | `firewall`, above every span | Labelled (row L1); trusted on shared addresses because it is per session |
| S2 | Palo Alto User-ID login and logout (`paloalto_userid`) | Person for an address, with the firewall's data source (`data_source_name`, `data_source_type`), timeout, and port range | `userid` | Ends at the logged timeout (row T2); a mapping with a port range marks the address shared (row C3) and never names a person by address |
| S3 | GlobalProtect login and logout (`private_ip`) | Person and laptop for a tunnel address | `vpn`, first among spans | None |
| S4 | FortiGate FSSO logon and logoff (`subtype=user`, `srcip`, `user`) and SSL VPN tunnel address (`tunnelip`) | Person for an address; person and tunnel address | `userid` and `vpn` | New template mappings with fixtures; today FortiGate user events become generic logons |
| S5 | Windows 4624 (and the same in NXLog, Snare, Winlogbeat, EVTX) with `IpAddress` | Person and workstation | `logon`, last among spans | Only logon types 2 (interactive), 10 (remote interactive), 7 (unlock), and 11 (cached) name a person; type 3 and others never do (open question Q3) |
| S6 | DHCP leases (Palo Alto now; FortiGate, UniFi, Windows DHCP Server per ADR-0029 row 1) | Machine and MAC, never a person | `dhcp`, machine only | None in rules; the pending templates land in slice 4 |
| S7 | Proxmox inventory (ADR-0045) | Machine for an address the guest reports or is configured with, never a person | `inventory`, machine only, below DHCP | New; exact IP match only (ADR-0045 A6), first and last seen as the span |
| S8 | Identities (ADR-0018) | Which logged names are one person | Not a source of addresses | Used to decide whether two holders are the same person (row C2), bound only in the caller's scope (D219) |
| S9 | Admin corrections (ADR-0029 C3) | A person or machine for an address or device over a range | `manual`, above every derived kind | Built in slice 5 if the owner keeps it in this slice (Q6) |

A person is only ever named from an authentication (S1 to S5, S9). DHCP and the inventory name machines (ADR-0029 row 6).

### Source strength order (owner, 2026-11-08, Q2)

When kinds disagree, the stronger kind in this table names the person and the weaker ones show as evidence (C5). This table is the only ranking: the code holds it as one ordered constant with these kinds in this order, a test asserts the constant equals this table, and no other code compares kinds (no implicit ranking by event time, source order, or count).

| # | Kind | Sources | Names |
|---|---|---|---|
| P1 | `manual` | S9 | Person or machine |
| P2 | `firewall` | S1 | Person, on that row only |
| P3 | `vpn` | S3, S4 SSL VPN tunnel address | Person |
| P4 | `userid` | S2, S4 FSSO, only from a trusted sender (U1) | Person |
| P5 | `logon` | S5, logon types 2, 7, 10, 11 only (Q3) | Person |
| P6 | `dhcp` | S6 | Machine only |
| P7 | `inventory` | S7 | Machine only |

Two holders at the same kind are **possible** (C1), never ranked against each other.

### User-ID senders (owner, 2026-11-08, Q5)

| # | Rule |
|---|---|
| U1 | A User-ID or FSSO line names a person only when it reached the server from a sender address listed for that source (Settings > Sources, the source's syslog senders) or over the TLS syslog listener (ADR-0021). UDP or plain TCP syslog from any other address is easy to forge: the line is stored as usual (raw is sacred) but its span names nobody and the lookup panel shows "User-ID from an unlisted sender, not used" |
| U2 | The label names how the line arrived and what the firewall learned it from: "attributed by User-ID at 9:12 AM (fw01 over TLS, from dc01.corp.internal)" or "(fw01 at 10.0.0.1, listed sender, learned from syslog)" |
| U3 | Mappings the firewall itself learned from its syslog parser or the XML API (`data_source_type`) name people under U1, with that source type in the label; an admin switch, off by default, ignores them. Changing the sender list or the switch is audited `admin.change` |

### Time-bounded mapping

| # | Rule |
|---|---|
| T1 | Every observation is a span `[start, end)` on one address. The event's own time (`time`, else `time_observed`) decides which spans cover it; nothing is matched to a span that starts after the event |
| T2 | Ends, first that applies: the matching logout, release, or FSSO logoff; the logged timeout (User-ID `time_out_threshold`, DHCP lease time) after the latest refresh by the same person; the next different holder on that address of the same kind; the per-kind cap (ADR-0029 row 3, unchanged) |
| T3 | A span that ended by its cap is **assumed** and labelled so ("GlobalProtect login 9:02 AM, no logout seen, assumed until 9:02 PM"), as today |
| T4 | Staleness: the label always carries the span's start, so the age is visible. A User-ID span with no logged timeout older than 1 hour at the event time is labelled "older mapping" (Q4) |
| T5 | Within an hour (AI usage rows are reduced to one per service, person, machine, address, and hour for memory), a row is attributed to one span only when its `first_t` and `last_t` both fall inside that span. If they straddle a handover, the row is **possible** (row C1) with both people, never the later one |

### Conflicts and confidence

| # | Rule |
|---|---|
| C1 | Three levels, never more: **attributed** (one person, from the strongest kind covering the time), **possible** (two or more people cover the time at the strongest kind, or the row straddles a handover), **not matched** (no span). "Possible" lists up to 3 names and a count ("Possible: alice or bob, 2 people on 10.20.1.5 at the time"). Nothing picks one of them: no "most events", no "newest" |
| C2 | Two names are one person when the Identities key (ADR-0018 rows 1 and 3) says so in the caller's scope (D219). `EXAMPLE\alice` from User-ID and `alice@example.com` from GlobalProtect are not a conflict when `example.com` is an organization domain |
| C3 | A **shared address** never names a person by address, only by S1: (a) any User-ID mapping on it carries a port range (terminal server agent); (b) two or more people's spans of any person-naming kind overlapped on it in the last 7 days; (c) an admin lists it, or its range, under Settings > Internal networks as shared (terminal servers, jump hosts, NAT gateways, proxies, DNS forwarders), audited `admin.change`. Rows on a shared address show "Shared address (terminal server)" or the reason, and the S1 user where the row has one |
| C4 | Only addresses inside Internal networks are attributed by span. A public address (egress, NAT, cloud) is never matched to a person, except a VPN tunnel address, which is internal by definition |
| C5 | A lower kind that disagrees with the winning kind does not demote it; the evidence panel shows it as "also seen: logon by bob at 9:14 AM" (Q2, accepted: the order is the P table) |
| C6 | Counts follow D115: possible and shared rows are not counted as people. They add a separate line ("4 rows possible, 2 on shared addresses"), linked to the list |

### How attributed rows are shown

| # | Case | Label (times in the app's local format, UTC on hover, as Ask does) |
|---|---|---|
| L1 | S1 | "alice: named by the firewall on the traffic log" |
| L2 | Span | "alice: attributed by User-ID at 9:12 AM (fw01, from dc01.corp.internal)", "by GlobalProtect login at 8:58 AM", "by Windows logon at 8:40 AM on ws-014.corp.internal", "by FortiGate FSSO at 9:01 AM" |
| L3 | Chain | "alice: DHCP lease ws-014.corp.internal at 8:55 AM, then sign-in on ws-014.corp.internal at 9:02 AM" (ADR-0029 C2, unchanged) |
| L4 | Assumed or older | The L2 text plus "no logout seen, assumed until 9:12 PM" or "older mapping" |
| L5 | Possible | "Possible: alice or bob" with the reason |
| L6 | Manual | "alice: set by an admin on Nov 8" |

Every label is a link to the address lookup panel (ADR-0029 row 8) at that time, which lists the spans used, the ones that disagreed, and their sources, with **Show events** for each. Surfaces: AI usage (Services, People, the drill-throughs), the AI flow People lane, AI watch item pages (names filled at read time, ADR-0029 C6), and Search's event detail line. Plain labels only (CLAUDE.md rule 12); no flavor names.

### Query time, not ingest time

| # | Rule |
|---|---|
| R1 | Attribution is computed per query in server-built SQL over the caller's `events` view, as ADR-0020 and ADR-0029 do. No event is rewritten, no column is filled at ingest, `raw` and `actor_user_name` keep what the log said (CLAUDE.md rules 5 and 9) |
| R2 | Closed days keep using the AI rollup's observations (`ai_ident`, ADR-0035 row 8), which store observations per source and day, not results, so scope still applies. Its columns gain `kind` values `userid` with timeout and port-range flags and `inventory`; additive only. No new event columns are proposed. Observations that need new parsed fields (logon type, User-ID timeout and port range, FortiGate `tunnelip`) read them from `unmapped` |
| R3 | No SQL function, placeholder, or table exposes attribution to SQL a person or a model writes, and MCP is unchanged, consistent with D219. The library's `who_had_ip` search stays as it is and is the reference test (ADR-0029, "since this was written") |

### Scope and access control

- Spans, conflicts, shared-address detection, and Identities keys are computed only from sources the caller can read. A caller who cannot read the User-ID source does not get its names, its "possible", or its shared flag; they see what their own sources say (D107 C4, D219).
- One consequence, accepted: two viewers can see different levels for the same row (an admin sees "possible" because the logon source disagrees; an analyst without the logon source sees "attributed by User-ID"). Each label names the source it came from, so neither is wrong about what it read.
- Names on AI surfaces follow ADR-0029 G1 to G6 (View people in AI usage, masking in the API, `ai.view_people` and `ai.export_people` audit rows). They are accepted but not built; this ADR adds names to more rows, so the owner decides whether they land first (Q1).
- The admin shared-address list is admin config, shown only to admins, like the alert targets (T43).
- Lookups stay audited `address.lookup`; corrections `identity.match_correct`; every view that names a person on an AI surface `ai.view_people` once G3 is built.

### Performance at about 200 users

| Item | Estimate or budget |
|---|---|
| Observations a day at 200 users, 250 devices | User-ID 10k to 50k (refreshes), logons of the four kept types 2k to 10k (type 3 dropped is most of 4624 volume), DHCP 1k to 3k, GlobalProtect hundreds, FSSO similar to User-ID |
| Span build | Window functions per (kind, address) over the query range plus 24 hours; already measured at 5 s to 7 s for AI usage on 14 million events (ADR-0020) |
| Added work | One `count(DISTINCT key)` per address and hour for C1, a 7-day overlap check per address for C3(b) (cached per closed day in the rollup), and the `first_t` and `last_t` test (T5): small next to the span build |
| Budget | AI usage over 7 days stays under the 20 s page limit and adds at most 25% to today's time on the bench; the lookup panel answers in under 1 s. Measured with a new generator `scripts/fixtures/attribution_200.py` (synthetic 200 users, 30 days) on the 2 vCPU and 4 vCPU bench hardware in the README |

## Alternatives considered

| Alternative | Why not |
|---|---|
| Stamp the person on events at ingest | Breaks rule 5 in spirit (a derived claim stored as if logged), freezes a wrong answer, mixes sources across scopes (a firewall row would carry a name from a domain controller source the reader cannot see), and a late logout could never correct it |
| A server-wide IP-to-user table refreshed on a schedule | Same scope leak, stale after access changes; rejected in ADR-0020 and ADR-0029 row 7 |
| Ask the firewall live (PAN-OS XML API `show user ip-user-mapping`, FortiGate FSSO list) | Contacts infrastructure with a privileged credential, answers only "now" not "at 9:10 yesterday", and Remnant reads logs |
| In a conflict, pick the most likely person (most events, newest, longest span) | A guess shown as fact (ADR-0029 C1, D222) |
| Exact per-event join instead of hourly rows | Precise, but AI usage reduces to hourly rows to fit memory (F46); T5 gets the same safety (no wrong name) at hourly cost, at the price of more "possible" rows around handovers |
| Port-aware join of traffic rows to terminal server port ranges | Would name people on terminal servers, but S1 already gives the firewall's per-port answer on those rows; later, if installs show S1 empty on terminal server traffic |
| Kerberos 4768 (TGT with client address) as a source | Good signal, more volume; deferred to the backlog, revisit after slice 3's measurements |

## Consequences

- Fewer names, more right: rows that today show a single name on a terminal server, a shared address, or across a handover will show "possible" or "shared address". The release note says so, with the reason.
- AI usage and the AI flow carry how each person was matched (L1 to L6), so every name is checkable in one click.
- Template changes: `paloalto_userid` keeps `time_out_threshold` and the port range as named fields; `fortinet_fortigate` maps FSSO logon and logoff and `tunnelip`; the four Windows templates keep the logon type. Each with fixtures per CLAUDE.md section 6 and template version bumps. Earlier events still parse; fields absent on old events fall back to today's caps.
- One admin setting (shared addresses) on the existing Internal networks page.
- No new model input, no new tool, no change to the LLM gate.

## Thin-slice plan

| Slice | End to end | Done when |
|---|---|---|
| 0 | Governance first (Q1): ADR-0029 G1 to G3, the View people in AI usage permission and masking of names for everyone without it, on every AI usage endpoint and page | API test: no name reaches a caller without the permission from any AI endpoint; masked labels in the UI; granting it audited |
| 1 | Never guess, and say how: C1 (possible), C2 (Identities keys in scope), C6 (counts), T5 (handover), and labels L1, L2, L4, L5 on AI usage People and Services, with the link to the lookup panel. Existing sources only | Table-driven tests below for C1, C2, T5; AI usage API returns `how`, `at`, `source`, `level`; frontend shows the labels; the reference test still passes |
| 2 | Ends and shared addresses: T2 with User-ID timeout, C3 (port ranges, overlap, admin list), C4 (internal only), C5 evidence | Template fixtures for User-ID timeout and port ranges; shared-address tests; admin list audited |
| 3 | More sources: S4 FortiGate FSSO and SSL VPN, S5 logon types | Fixtures per section 6, parse rate at least 95%; bench with `attribution_200.py` recorded in the PR |
| 4 | Machines: S6 pending DHCP templates, S7 inventory | Fixtures; host label chains (L3) from the new machines |
| 5 | Corrections (S9, L6), if kept in this slice (Q6) | `identity.match_correct` audited; a correction wins and sticks |

Each slice is its own PR under about 400 lines of non-fixture diff, the AI flow and AI watch adopting the same function (ADR-0029 C7) in the slice that changes what it returns.

## Tests

- Strength order: the code's one ordered kind constant equals the P1 to P7 table (test reads the table from this ADR); a disagreement at every pair of kinds is won by the higher row with the lower shown as evidence; two holders at the same kind are possible.
- Senders: a User-ID line over UDP from an unlisted address names nobody and shows the unlisted-sender note; the same line from a listed sender, or over TLS, names the person with the U2 label; the admin switch ignores firewall-learned syslog and XML API mappings; changes audited.
- Spans (`test_address_spans.py`, table-driven): handover inside an hour (09:10 and 09:50 rows split or possible, never the later holder for both); two people overlapping on one address at the same kind (possible); terminal server port-range mappings (shared, no person by address; S1 user kept); User-ID timeout ends the span; refresh by the same person extends it; cap reached (assumed label); older mapping label; public address never matched; admin shared list; lower kind disagreeing (attributed, with the evidence row).
- Identities: `EXAMPLE\alice` and `alice@example.com` with `example.com` listed is one person; with the alias's account outside the caller's scope it stays two (D219).
- Scope (integration): a user without the User-ID source sees addresses only; a user without the logon source sees "attributed by User-ID" where an admin sees "possible"; nothing from an unreadable source appears in any label, count, or shared flag.
- Counts: possible and shared rows are not counted as people (D115).
- Reference: on the same data, built-in attribution names at least what `who_had_ip` names, and never a different person.
- Templates: fixtures for the User-ID timeout and port-range lines, FortiGate FSSO and `tunnelip` lines, and logon types 2, 3, 7, 10, 11 in each Windows template; synthetic values only (10.x addresses, `alice@example.com`, `ws-014.corp.internal`).
- Governance, once G1 to G6 are built: no names without View people in AI usage, from every AI endpoint (API test).
- Performance: the bench numbers above, in the PR for slice 3.

## Threats (rows T71 to T76 in SPEC 7.1)

| ID | Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|---|
| T71 | A shared address (terminal server, jump host, NAT gateway, DNS forwarder) makes one person's AI use appear under another's name, by accident or on purpose | n/a (no model input); it decides who is named in AML.T0057 data-leakage investigations | T1036 Masquerading | C1 possible, C3 shared addresses name nobody by address, C4 internal only, S1 per-session user only |
| T72 | A forged User-ID feed: syslog sent to the firewall's User-ID syslog parser, a forged XML API call, or forged USERID lines sent to Remnant's syslog listener, so a chosen person is named | n/a | T1565.001 Stored Data Manipulation, T1036 | The label names the User-ID data source and type; User-ID names a person only from a listed sender address or the TLS listener, never from UDP or TCP syslog from any other address (U1), and the label says how it arrived (U2); the sender address is kept in `device_ip` (ADR-0021 row 5); firewall-learned syslog and XML API mappings carry their source type and an admin switch ignores them (U3); GlobalProtect and logon disagreements show in the evidence (C5) |
| T73 | A dropped or blocked logout (UDP loss, a collector stopped) keeps the previous holder named for the next one | n/a | T1562.006 Indicator Blocking | Logged timeouts end spans (T2); assumed and older labels (T3, T4); quiet-source and watched-device alerts (T29, T44) |
| T74 | Attribution reveals names, conflicts, or a shared flag from sources the viewer cannot read, or reaches a cloud model or MCP client | AML.T0057 LLM Data Leakage | T1213 Data from Information Repositories | Everything over the caller's view; Identities keys bound per D219; no attribution in caller SQL, Ask, Explain, or MCP (R3); shared-address list admin-only |
| T75 | Flooding User-ID or logon events slows AI pages or exhausts memory | n/a | T1499 Endpoint Denial of Service | Observations reduced per hour and cached per closed day; existing memory limits (T51); listener caps (T48) |
| T76 | A crafted user name in a User-ID or FSSO line carries text aimed at a model, or markup | AML.T0051.001 LLM Prompt Injection: Indirect | T1189 (analogous) | Names rendered as text nodes; not sent to a model by this feature; if a later feature sends them, only through the gate under `data` |

Existing rows that still apply and are not renumbered: T45 (wrong mapping), T46 (scope), T47 (stolen credentials shown under the victim's name), T41 (crafted name merged into a person), T36 (usage data about named people).

## Open questions for the owner (all answered 2026-11-08: proposed defaults accepted)

| # | Question | Proposed default |
|---|---|---|
| Q1 | Do ADR-0029 G1 to G6 (View people in AI usage, masking, audit) land before slice 1, since this adds names to more rows? | Yes: G1, G2, G3 as slice 0 |
| Q2 | When kinds disagree (User-ID says bob, a logon says alice), attributed to the stronger kind with the disagreement in the evidence (C5), or always "possible" (strict)? | Stronger kind, disagreement shown. **Accepted**, with the order written as a table (P1 to P7) and tested |
| Q3 | Which Windows logon types name a person: 2, 7, 10, 11 only, or also 3 (network) from workstations? | 2, 7, 10, 11 |
| Q4 | The "older mapping" age for User-ID spans with no logged timeout, and the overlap window for automatic shared detection | 1 hour; 7 days |
| Q5 | Do User-ID mappings learned from syslog parsing or the XML API name people, or only those from domain controller monitoring, GlobalProtect, and captive portal? | All, with the data source type in the label; an admin switch to ignore syslog and XML API. **Accepted**, and User-ID counts only from listed senders or the TLS listener (U1 to U3) |
| Q6 | Are admin corrections (ADR-0029 C3) part of this slice (slice 5) or a later one? | This slice, last |
| Q7 | Is the shared-address list a setting on Internal networks, or a tag on a watched device (ADR-0019)? | Internal networks |
| Q8 | Should "possible" rows raise AI watch alerts (naming no one, the address and the possible count), or wait until attributed? | Alert on the address, as for unmatched devices today |
