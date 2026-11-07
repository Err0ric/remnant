### Proxmox guest inventory source (2026-11-06)

- New source kind **Proxmox VE**: reads which VMs and containers exist, their node, status, tags, MACs, and IP addresses, with a read-only PVEAuditor API token. Setup: `docs/install/proxmox.md`. Verified on Proxmox 8 and 9: pending.
- A token that can do more than read (for example `Sys.Modify` or `VM.Allocate`) is refused when the source is saved, when its token is replaced, and on every poll. The certificate is always checked; a self-signed cluster CA can be pinned.
- Each event is the connector's own short record, never Proxmox's response: guest descriptions, notes, and cloud-init settings (user, password, SSH keys) are never stored or logged.
- Events are written only when a guest appears, changes, or disappears, plus one heartbeat per guest a day. On Proxmox 8, VM addresses come from the config only and Sources says "Agent IPs not available with this token".
- New starter template `proxmox_inventory`, category Inventory.
- What changes for existing installs: nothing until a Proxmox source is added; the database gains the `proxmox` source kind on upgrade.
