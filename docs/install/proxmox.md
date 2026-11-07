# Proxmox VE: guest inventory

**Verified on Proxmox 8 and 9: pending.** The connector is tested against a fake Proxmox API shaped like versions 8 and 9; it has not yet been run against a real cluster. This line changes when it has.

The Proxmox source reads which VMs and containers exist, where they run, and which MACs and IP addresses they have, so an address seen in other logs can be named: "Proxmox VM 104 build-runner on pve2". It uses one read-only API token per cluster or standalone host. Design: [ADR-0045](../adr/ADR-0045-proxmox-inventory-and-empty-results.md) Part A, D210.

## What it reads, and what it keeps

| Read | From | Kept |
|---|---|---|
| Guests | `GET /cluster/resources?type=vm` | Name, VMID, type (`qemu` or `lxc`), node, status, tags. Templates are skipped |
| Each guest's config | `GET /nodes/{node}/{type}/{vmid}/config` | MACs from `netN`; the address only from `ip=` in a VM's `ipconfigN` or a container's `netN` (not `dhcp`). Nothing else |
| Container addresses | `GET /nodes/{node}/lxc/{vmid}/interfaces`, running containers | Addresses |
| VM addresses | `GET /nodes/{node}/qemu/{vmid}/agent/network-get-interfaces`, running VMs with the guest agent on | Addresses |
| The token's permissions | `GET /access/permissions`, at save and every poll | Nothing |

The config response holds more than this: the description and notes, the cloud-init user, password, SSH keys, name servers, and search domain. The connector reads the response in memory and builds its own record from the fields above, so those values never reach the lake, a log line, the audit log, or a model. Loopback and link-local addresses are dropped.

Each event's `raw` is that record, one JSON line, for example:

```json
{"feed":"proxmox.guest","event":"changed","time":"2026-11-06T12:15:00Z","vmid":104,"type":"qemu","name":"build-runner","node":"pve2","status":"running","tags":["ci"],"macs":["52:54:00:12:34:56"],"ips":[{"ip":"10.20.30.40","from":"config"},{"ip":"10.20.30.41","from":"agent"}],"changed":["ip"]}
```

An event is written only when a guest **appears**, **changes** (name, node, status, MAC, IP, or tags), or **disappears**, plus one **heartbeat** per guest a day. A poll in which nothing changed writes nothing. The template is `proxmox_inventory` (category Inventory): the guest name is `device_hostname`, its first address `device_ip`, the event `message`; VMID, node, MACs, every address, and tags are in `unmapped`.

The source is **local only** when added, like every source: guest names and tags can say what a machine is for, so they never go to a cloud model or a cloud MCP client unless an administrator allows it.

## Guest agent addresses on Proxmox 8

Proxmox 9 lets PVEAuditor read the guest agent's interface list (`VM.GuestAgent.Audit`). Proxmox 8 asks for `VM.Monitor`, which PVEAuditor lacks. The connector never asks for more: when the agent request is refused, it records MACs and config addresses only, and Sources shows **Agent IPs not available with this token**. Container addresses and config addresses are recorded on both versions.

## 1. Create a read-only token

On any node of the cluster, as root. Replace `remnant` and `inventory` if you like; keep the role.

```
pveum user add remnant@pve --comment "Remnant inventory, read only"
pveum acl modify / --users remnant@pve --roles PVEAuditor
pveum user token add remnant@pve inventory --privsep 1
pveum acl modify / --tokens 'remnant@pve!inventory' --roles PVEAuditor
pveum user token permissions remnant@pve inventory
```

`token add` prints the secret once (a value like `0b5e7c1a-...`). Copy it now. The last command lists what the token can do: it should show only `*.Audit` privileges. With `--privsep 1` the token holds only what is granted to the token itself, so it cannot inherit more from the user later.

To revoke: `pveum user token remove remnant@pve inventory`.

## 2. The certificate

The certificate is always checked; there is no switch to skip it. Either:

- the node's certificate is signed by a CA this server already trusts (for example ACME), or
- the cluster uses its own CA: copy `/etc/pve/pve-root-ca.pem` from a node and paste it in **Cluster CA** below. Only that CA is then trusted for this source.

Use a host name that is in the certificate, for example `pve1.example.internal`.

## 3. Add the source

**Sources > Add source**, then **Reads from: Proxmox VE**.

| Field | Value |
|---|---|
| Source ID | For example `pve` |
| Proxmox host | A node or cluster host name, for example `pve1.example.internal` |
| Port | `8006` |
| API token ID | `remnant@pve!inventory` |
| Token secret | From step 1 |
| Cluster CA | Optional, from step 2 |
| Read every | Minutes between polls, default 15 |

Select **Test connection**: it shows the permission check, the Proxmox version, and how many guests it can see. A token that holds any privilege beyond PVEAuditor's (for example `Sys.Modify`, `VM.Allocate`, `VM.PowerMgmt`, or `VM.Monitor`) is refused, here and on every poll, with the privileges named.

The server needs HTTPS to the node on port 8006.

## On the Sources page

The row shows the host, the token's user and realm (never the secret), and "Verified on Proxmox 8 and 9: pending". **Edit settings** changes the schedule and the CA; **Replace credentials** changes the token secret. To use a different host or token ID, add a new source. The source starts with no quiet alert, because it writes only on a change and once a day.

## Where the inventory shows

For an exact IP or MAC match, the top bar search, IP pages, and People and devices show a line such as **Proxmox VM 104 build-runner on pve2**, with first and last seen and **Show events** (that guest's inventory events). Host pages show it when the host is the guest's name exactly. An address that two guests held at different times shows both. Nothing is matched by similarity. Only users whose groups include the Proxmox source see these lines.

When an address has no events, the same places (and an empty Ask answer that names the address) say what was searched, one line per kind of source, and "Not in the Proxmox inventory" when the address is not in it.

## Threats

T68 in [SPEC](../SPEC.md) section 7.1: what a leaked token could read, what the connector keeps, and why guest names are treated as untrusted text.
