### AI service alerts name the device and its address (2026-11-06)

- An "AI service not approved" or "not reviewed" alert with no person attached now names each device by its host name and the address it was seen at ("ws-0101 at 10.20.1.5"), or says "no host name seen" when only the address is known. The host name comes from the event itself or from who held the address at the time (DHCP, logons).
- On Alerts, host names open the host page and addresses open the IP page, each on its own row (Devices, Addresses). Before this, an address showed under Devices and opened as a host.
- What changes for existing installs: open AI service alerts pick up the device and address on the next hourly review; closed alerts stay as they were.
