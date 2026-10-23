# ADR-0029: Who had an address, from DHCP leases and VPN sessions as intervals

Status: **Accepted** 2026-10-23 by the owner, with the conditions in "Owner conditions" below; where a row above differs, the conditions win. Recorded as SPEC D107.

## Context

The install trial showed raw addresses in the AI usage "Who" column. Most rows that named only an address went unresolved, even with firewall DHCP logs and GlobalProtect logs in the lake.

How resolution works today (`search/addresses.py`, ADR-0020 row 1):

| Source | Gives | How it is used |
|---|---|---|
| Successful logons (OCSF Authentication 3002, Windows 4624) | Address to person and workstation | A point in time |
| Palo Alto User-ID | Address to person | A point in time |
| GlobalProtect login (`paloalto_globalprotect`, `private_ip`) | Tunnel address to person and laptop | A point in time |
| DHCP | Nothing | Not read at all |

For an address and an hour, the newest observation up to the end of that hour wins, and only if it is no older than `MAX_AGE_HOURS` (12).

Why that misses on real data:

1. **No DHCP.** Office machines get addresses from DHCP. No logon or User-ID event may mention the address for hours, so the machine stays an address. DHCP leases carry the hostname the client sent and its MAC.
2. **Long sessions fall off the 12-hour window.** A GlobalProtect session or a DHCP lease can last days. The login event is written once, so 12 hours later the same session no longer resolves, though the person still holds the address.
3. **No end.** A point-in-time rule cannot tell that a session ended or a lease was released, so after a logout the next holder of the address can briefly be named as the previous one (inside the 12 hours).

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | DHCP as a source | Read DHCP lease events (OCSF DHCP Activity, `class_uid` 4004) from any template that maps them. Lease assigned or renewed: address to hostname and MAC. Released or expired: the end of that lease. Ship mappings in the starter templates that already see DHCP: Palo Alto system log (`dhcp` subtype), FortiGate event log, UniFi, Windows DHCP Server audit log (new small template) | The logs are already collected; firewall and Windows DHCP cover most small sites | A live DHCP server query (contacts infrastructure; Remnant only reads logs) |
| 2 | Intervals instead of points | Build `addr_span(ip, start, end, who, host, mac, kind)`. Start: login or lease event. End: the matching logout, release, or expiry (lease time when logged), else the next different holder of the same address, else start + a per-kind cap | Sessions and leases are intervals; ends stop misnaming the next holder | Raising `MAX_AGE_HOURS` (more misnaming, not less) |
| 3 | Caps when no end is seen | VPN session: 24 hours. DHCP lease: the logged lease time, else 24 hours, extended by each renewal. Logon and User-ID: 12 hours, as today | Bounded guesses; renewals keep a long-running machine named | One cap for all (wrong for one kind or the other) |
| 4 | Join | ASOF join on (ip, event time) against `addr_span`, accept only when the event time is before the span's end. Same per-hour bucketing as today for cost | Keeps the current cost profile on large lakes | Per-event join (slower, little gain) |
| 5 | Precedence at the same time | Person: VPN login, then User-ID, then logon. Machine: VPN laptop name, then DHCP hostname, then logon workstation | VPN and User-ID name the person who holds the tunnel; DHCP names the machine, never a person | A single "newest wins" (a DHCP renewal would hide the VPN person) |
| 6 | What is shown | Who: person, else machine, else address. A row resolved from DHCP alone shows the hostname, never a person. MAC is shown in the address lookup panel only, not in tables | DHCP hostnames are client-chosen and can be spoofed; a person must come from an authentication | Showing MAC in every table (noise) |
| 7 | Scope | All of this is SQL over the caller's own `events` view: someone who cannot read the DHCP source does not get its names (rule 13) | Same rule as ADR-0020 | A server-wide address table (would leak across source groups) |
| 8 | Visibility | The address lookup panel lists the spans it used (kind, start, end, source), so an analyst can see why a row was named | Every attribution checkable | Silent resolution |

## Governance: who sees people (owner review, 2026-10-21)

Per-person AI usage is sensitive: it says what a named employee did and when. A source group decides which events someone may read; it is not enough on its own to decide who may see names attached to AI use.

| # | Rule |
|---|---|
| G1 | A new permission, **View people in AI usage**. Admins have it. Analysts and Auditors do not by default; an admin grants it per user (Users page), audited `admin.change` |
| G2 | Without it, every person-level field on AI surfaces (AI usage Who column, the People tab, the investigator's AI flow person cards, AI watch alert text, possible personal-account rows from ADR-0030) shows the machine or address instead, or "Hidden" where there is none. Counts stay (for example "3 people"), names do not. Enforced in the API responses, never only in the UI |
| G3 | Every response that includes person-level AI data writes an audit row `ai.view_people` with the user, the surface, the time range, and `sources_in_scope`. The existing `ai.view` row stays for views without names |
| G4 | Exports and report drafts that include names from AI surfaces are audited `ai.export_people`, with the row count. Without the permission, exports carry the same masking as the screen |
| G5 | Alerts: AI watch alerts name a person only when every target is marked as going to people with the permission (an admin checkbox on the alert target); otherwise the alert names the machine and links to the page |
| G6 | The address lookup panel (row 8) follows the same rule: spans show the hostname and source, and the person only with the permission |

## Since this was written (2026-10-22)

| Change | What it gives | Should this ADR use it |
|---|---|---|
| Example saved searches `who_had_ip` and `ai_services_by_device` | Palo Alto DHCP lease lines (`paloalto_system`, subtype `dhcp`) parsed for address, hostname, and MAC, and an ASOF join from DNS queries to the newest lease at or before each query, 7 days back | Yes. Row 1's Palo Alto mapping and row 4's join are these, done once in `search/addresses.py` with ends (row 2) and caps (row 3). The example search becomes the reference test: on the same data, built-in resolution names at least what it names |
| Microsoft 365 sign-ins (`m365_signin`) map the user (UPN), `src_endpoint_ip`, and `device_hostname` (`deviceDetail.displayName`) | An authenticated person on a named device at a time | Yes, as **device to person**, not address to person: the sign-in address is usually the office's public egress address, which no internal log uses. A machine named by DHCP (row 1) is linked to the person who signed in from it in the span. Proposed row 5a: person through device only for successful interactive sign-ins, only when one person signed in from that device in the span (otherwise "several people"), shown as "via sign-in on WS-0042 at 09:12". Same precedence as row 5: VPN and User-ID still win |
| Loki stream labels as the envelope (`envelope.loki_labels`, label map) | Lines pulled from Loki carry host and job from labels, with the raw line unchanged | Yes, for tests: on the owner's install the DHCP and GlobalProtect lines arrive through Loki, so the span tests run the new DHCP mappings on Loki-shaped input (labels plus line) as well as syslog files. No design change: the Palo Alto templates read the raw CSV line either way |

## Owner conditions (2026-10-23)

| # | Condition | What it changes above |
|---|---|---|
| C1 | Every person shown says how it was matched (sign-in, DHCP lease, GlobalProtect, User-ID, logon, manual) and is a link to that evidence. No guess is shown as fact | Row 8's lookup panel is the link target from every person, everywhere. A span that ended by a cap (row 3) says so: "GlobalProtect login 9:02 AM, no logout seen (assumed until 9:02 PM)" |
| C2 | Matches chain, and the chain is shown: DHCP gives the device, a successful sign-in on that device gives the person (row 5a) | "DHCP lease WS-0042 8:55 AM, then company sign-in on WS-0042 9:02 AM". DHCP alone still never names a person (row 6) |
| C3 | An admin can correct a wrong match (assign a person to a device or an address over a time range, or clear one). Audited `identity.match_correct`; the correction wins over every automatic match and sticks | New: a small corrections table, shown as "manual (by admin, date)" in the match. It stays until an admin removes it; it is admin data, not derived from events |
| C4 | Names show only to people who can read the source the match came from, with the same retention as that source | Rows 7 and 8 already compute matches per query from the caller's events, so retention follows the source. Governance G1 stays: without **View people in AI usage**, analysts see devices (owner: least privilege by default) |
| C5 | Devices with no match stay "devices not matched to a person" (D115) | Row 6's fallback, worded per D115 |
| C6 | Stored alert text never carries a name | AI Watch items store references (subject, device, match ids); names are filled in for each viewer when the item is read, under C4 and G2. Messages to targets follow G5 |
| C7 | After it lands, AI Watch, Alerts, AI usage, and Investigations use people wherever a match exists | Same resolution function everywhere |

## Implementation notes

- 2026-10-23, part 1: `search/addresses.py` builds `addr_span` from logon, User-ID, GlobalProtect (logout ends), and Palo Alto DHCP leases (rows 1 to 3), with `capped` when the end was assumed; the person and machine per address and hour follow row 5's precedence, and a machine's person comes from a successful `m365_signin` on it in the 24 hours before when only one person signed in (row 5a, C2). `addr` carries how each was matched (`rwho_how`, `rwho_at`, `rwho_capped`, `rwho_src`, `rwho_dev`, and the same for the machine) for C1. Microsoft 365 sign-ins are left out of address logons (their address is public egress). FortiGate, UniFi, and Windows DHCP Server mappings, corrections (C3), G1 to G6, and people-with-evidence in every surface follow.

## Consequences

- Office machines on DHCP and remote users on GlobalProtect resolve across long sessions.
- Wrong names after a logout or release become rarer, since spans end.
- New template mappings for DHCP (Palo Alto system, FortiGate, UniFi; Windows DHCP Server new), each with fixtures per section 6.
- DHCP hostnames are client-supplied: a machine can claim any name. They are labelled as machine names, never people.
- A new per-user permission and two audit actions; existing installs get it for Admins only, so analysts who see names today will see machines after upgrade until granted (release note).

## Threat model (SPEC section 7)

- New threat: a spoofed DHCP hostname makes another machine's AI use appear under a chosen name (ATT&CK T1036 Masquerading). Mitigation: DHCP names machines only; people come from authentications; the lookup panel shows the source of each name.
- ATLAS: improves attribution for AML.T0057 (LLM data leakage) investigations; no new model input.
- New risk: per-person AI usage used for surveillance beyond its purpose, or seen by more people than need it. Mitigation: governance G1 to G6 (permission, masking in the API, audit of every named view and export).

## Tests

- Table-driven span tests: login then logout; lease, renewals, release; no end (each cap); two holders of one address in a day; precedence at the same time.
- Integration: DHCP and GlobalProtect fixtures plus DNS queries; AI usage "Who" shows the person or hostname at each time; a user without the DHCP source sees addresses only.
- Template fixtures per section 6 for each new DHCP mapping.
- Governance: an analyst without the permission gets machines or "Hidden" from every AI endpoint (API test, not UI); with it, names plus an `ai.view_people` audit row; a CSV export with names writes `ai.export_people`; an alert to an unmarked target names no person.

## Out of scope

- MAC vendor lookup, 802.1X, switch port, and Wi-Fi association logs (later sources for the same spans).
