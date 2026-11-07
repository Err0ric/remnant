# proxmox_inventory fixtures

| | |
|---|---|
| Source product | Proxmox VE 8 and 9 (`/cluster/resources`, guest config, LXC interfaces, guest agent) |
| Collector shape | The Proxmox connector's own minimal record, one `{"feed": "proxmox.guest", ...}` JSON line per appear, change, disappear, or daily heartbeat |
| Generator | `scripts/fixtures/proxmox.py` (seed 42) |
| Values | Invented guest names, `pveN` nodes, RFC 1918 and 2001:db8::/32 addresses, 52:54:00 MACs |

Pathological lines cover empty and truncated JSON, wrong types, a 10 KB name, a guest name
written as an instruction, non-object JSON, control characters, and a multiline fragment.
