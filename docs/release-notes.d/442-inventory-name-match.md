### Host pages match Proxmox guests by name only when the name is unique (2026-11-07)

- A host page shows a Proxmox guest by its name only when exactly one guest has that name, and labels it "matched by name". When several guests share the name, they are all listed as possible matches and none is picked.
- Common default names (localhost, debian, ubuntu, pve and similar, also with a number such as debian-12) never match a guest by name alone. IP and MAC matches are unchanged.
- What changes for existing installs: a host whose name several guests share, or a default name, no longer shows a single guest as its match.
