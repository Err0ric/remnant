# ADR-0045: Proxmox guest inventory, and saying why an address has no events

- Status: accepted by the owner 2026-11-06: A2 PVEAuditor only, A3 lake events, A5 the existing pages, B3 template fields and source health only; with two additions to A3 (rows A3a and A3b). The build starts after the owner's homelab checks (A2, and the cloud-init fields in T68)
- Adds a connector, an asset inventory, and a rule for empty results (top bar, IP and host pages, Ask)

## Context

An external network sensor flagged an internal host, a Proxmox guest, running Nmap scripts against another internal subnet. Remnant had nothing on the source address. The guest made no DNS lookups, its syslog was not forwarded, and the traffic crossed no logged firewall path. Two things were missing:

1. **What the address is.** The hypervisor knows every guest's name, VMID, node, MACs, and often its IPs. Remnant never asked it.
2. **Why the answer is empty.** An empty page reads as "nothing happened". The truth was that no source could have seen it, and the page should say so, source by source, without guessing.

This is a new connector, a new kind of stored data (an inventory, not events from the guest), and a new rule for empty results, so it needs a decision.

## Part A: Proxmox inventory connector

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| A1 | What it reads | One API token per Proxmox cluster or host, PVEAuditor role only. Reads `GET /cluster/resources?type=vm` (name, VMID, type `qemu` or `lxc`, node, status, tags) and, per guest, its config (`netN` MAC and bridge; cloud-init `ipconfigN` or LXC `ip=` when static). For running guests it also reads the addresses the guest reports: `GET .../lxc/{vmid}/interfaces` for containers (`VM.Audit`) and `GET .../qemu/{vmid}/agent/network-get-interfaces` for VMs with the guest agent | The read-only role covers the inventory. The owner's rule is "PVEAuditor only" | A broader role (refused: the token would be able to change guests) |
| A2 | Guest agent addresses on older Proxmox | Proxmox 9 moved the agent's interface list to `VM.GuestAgent.Audit`, in the audit privilege group next to `VM.Audit`. Proxmox 8 needs `VM.Monitor`, which PVEAuditor lacks. On 8 the connector records a VM's MACs and config addresses only, and Sources says "guest agent addresses need Proxmox 9 with a PVEAuditor token" for that cluster. To verify on the homelab before calling it done | The token stays read-only on both versions; the gap is stated, not worked around | Ask for `VM.Monitor` on 8 (refused: beyond PVEAuditor) |
| A3 | Where the inventory lives | In the lake, as events from a `proxmox` source with its own template (`proxmox_inventory`, category `inventory`). The connector polls on a schedule (default every 15 minutes); what it writes is A3a and A3b. Each event maps to OCSF fields (device name, hostname, MACs, IPs, VMID and node in `unmapped`) | The access rules (source groups, `local_only`, audit) and retention already apply to events; first and last seen come from the event times; history comes free | A separate `assets` table in the meta database (needs its own access checks and history) |
| A3a | What `raw` holds (owner, 2026-11-06) | The event's raw line is the connector's own minimal record, built from the A1 fields only (name, VMID, type, node, status, tags, MACs, IPs, and where each IP came from). It is never the API response. Guest descriptions, notes, and cloud-init fields never reach the lake, a log line, or a model. Test: a guest whose description holds a fake secret string; the string appears nowhere in the lake or the logs | The lake keeps what the inventory needs and nothing an admin happened to paste into Proxmox | Store the API response as `raw` (refused) |
| A3b | When it writes (owner, 2026-11-06) | An event only when a guest appears, changes (name, node, status, MAC, IP, or tags), or disappears, plus one heartbeat per guest a day. Test: a poll in which nothing changed writes nothing | First and last seen stay exact without a row per guest per poll | A row per guest per poll |
| A4 | Who sees it | Like any source: only users whose groups include the `proxmox` source. Its classification is `local_only` by default, so it never reaches a cloud model or a cloud MCP client | Guest names and tags can say what a machine is for | Visible to everyone (refused) |
| A5 | Where a match shows | The top-bar search, the IP and host pages, and People and devices. For an IP or MAC that matches a guest, a line reads **Proxmox VM 104 build-runner on pve2**, with first and last seen. The line links to the inventory events (Show events). Only the caller's own view is read | One fact, shown where the address is looked up | A separate Assets page (can follow later) |
| A6 | Matching | An exact IP or MAC match against the guest's recorded addresses during the range. An IP that two guests held at different times shows both, each with its own first and last seen. Nothing is matched by name similarity | No guessing, and DHCP churn shows as it is | Latest owner only (hides a reassigned address) |
| A7 | The token | Stored encrypted like other connector secrets. Sources shows the token's user and realm, never the secret. The connector refuses a token whose permissions (`GET /access/permissions`) include any privilege that changes things | A misconfigured token is caught before it is used | Trust the configuration |
| A8 | TLS | The hypervisor's certificate is verified. A self-signed cluster CA can be pinned by uploading it (Sources). No "skip verification" switch | Consistent with the HTTPS rules | A skip switch (refused) |

### Threat model (SPEC 7.1, new T68)

| Threat | ATLAS / ATT&CK | Control |
|---|---|---|
| The token leaks or the server is taken over, and the token is used against the cluster | T1078 Valid Accounts, T1552 Unsecured Credentials | PVEAuditor only, checked at save time (A7); the secret follows the existing secrets rule (encrypted at rest with the install key, never logged, never in YAML or a prompt); revocable in Proxmox |
| What the read-only token can see | T1580 Cloud Infrastructure Discovery (the inventory is a map of the estate) | **Recorded here, as the owner asked:** guest names, VMIDs, types, nodes, status, tags, MACs, IP addresses, network config (bridges, VLAN tags, cloud-init IP settings), and the cluster's node and storage list. With PVEAuditor it can also read each guest's full config (disks, CPU, memory, boot order, description and notes, and the cloud-init settings stored there, such as the user name and SSH public keys); anything an admin pasted into a description or note is readable too. Exactly which cloud-init fields come back, and whether the password field is masked, is to be confirmed against the homelab before step 1 is called done. The connector stores only the fields in A1, not the whole config (A3a). It cannot start, stop, change, or open a console to anything, and cannot read guest disks or memory. The inventory is `local_only` and source-scoped (A4) |
| Guest names, tags, or agent-reported data carry text aimed at a model (a guest named "ignore previous instructions") | AML.T0051.001 Indirect Prompt Injection | Inventory events are log content: untrusted, shown as text, sent to a model only under `data` and only if the source is cloud-allowed |
| A cloud model or MCP client learns the estate map | AML.T0057 LLM Data Leakage | `local_only` by default (A4); every MCP and model call audited |

## Part B: empty results say why

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| B1 | When it shows | The top bar, an IP page, or an Ask answer finds no events for an address in the range | The case from the context | Always (noise when there are events) |
| B2 | What it says | "No events for 10.20.30.40 in the last 24 hours." Then one line per source the caller can read, grouped by category, stating only what was checked and found: "**DNS** (2 sources): no lookups by this address", "**Firewall** (1 source): no traffic logged to or from this address", "**Syslog**: nothing received from this host", "**Identity**: no sign-ins from this address". Then the inventory line (A5) if there is one, or "Not in the Proxmox inventory" if the source exists. Then **Add a source** | Facts the queries establish; nothing about why | A model-written explanation (refused: guessing) |
| B3 | "Could have seen it" | Stated only from facts Remnant holds: was the source receiving during the range (its last event and any gap alert), and does its template record the field searched (a DNS source records the client address; a syslog source records the sending host). A source that was not receiving says "(not receiving since Nov 5, 14:02)". A category with no source says "**No firewall source**" | What a source could see is decided by its template's fields and its health, both known; network paths are not, so they are never claimed | Infer reachability from subnets (refused: guessing) |
| B4 | Sources the caller cannot read | One line: "Sources you don't have access to were not searched." No names or counts | Does not reveal what exists | List them (leaks the source list) |
| B5 | Ask | When an Ask answer has no rows and its question names an address, the same lines follow the answer. Written by code, never by the model | Same rule, same words | Let the model explain (refused) |

## Consequences

- One new connector, template, and source kind; a lookup used by four surfaces; and an empty-result block used by three.
- The inventory is only as good as Proxmox's view: a guest with no agent and a DHCP address has MACs only. MAC-only matches still help, through DHCP or ARP sources that record MACs.
- Empty-result lines depend on template categories and fields. A template with a wrong category gives a wrong line, so the starter templates' categories get a test.

## Rollout (after review)

1. Connector, template with fixtures, Sources setup (token, CA, schedule, permission check), with tests against a fake Proxmox API: both PVE versions, a mutating token refused, LXC interfaces, an agent-less VM, DHCP churn. Guide `docs/install/proxmox.md` with the exact role and token steps.
2. The match line on the top bar, IP and host pages, and People and devices, and its tests.
3. The empty-result block (B), with the category test and tests for each line, the not-receiving case, and the no-access line.
4. SPEC: T68, a D-row (as a `docs/decisions.d` file), and a release note per PR.
