### Which Proxmox guest an address is, and why an address has no events (2026-11-07)

- The top bar search, IP and host pages, and People and devices name the Proxmox guest behind an exact IP, MAC, or host name: "Proxmox VM 104 build-runner on pve2", with first and last seen and Show events. An address two guests held at different times shows both.
- When an address has no events, the top bar, its IP page, and an empty Ask answer that names it say what was searched, category by category: "DNS (2 sources): no lookups by this address", which sources were not receiving or are turned off, which kinds of source you have none of, whether it is in the Proxmox inventory, and Add a source for administrators. Written by the app from your sources' settings and health, never by the AI model.
- Only sources you may read are searched or named; others get one line, "Sources you don't have access to were not searched."
- What changes for existing installs: nothing to do; the lines appear where they apply, and the inventory line needs a Proxmox source.
