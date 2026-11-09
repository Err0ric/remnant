### AI service alerts name who used the device, and say why by the service's status (2026-11-08)

- An AI service or MCP server alert that named only a device now shows a Person on device line when the Claude hooks plugin has records from that host in the alert's time range: "erin@example.com, seen on this host in the hooks plugin". Two names that Identities links into one person are shown once, with "(names linked in Identities)".
- When several people used the host in that range, the line says "Possible: erin@example.com or frank@example.com, 2 people seen on this host in the hooks plugin" and picks nobody. These names are not added to the alert's people or counts.
- The names come only from hooks sources you can read; without them you see the device as before.
- "Why it matters" and the next steps now follow the service's status in the AI service catalog today: Not approved, Unreviewed, a service not in the catalog, and Approved (after the alert was raised) each have their own wording. GET /api/alerts adds `review_status` and `device_people` to each alert.
- What you will notice: on an alert such as one for Gemini, the person who used the device when the hooks plugin saw them, and wording that says the service is Not approved.
- What changes for existing installs: nothing to do. No data, settings, or update steps change. To go back, roll back the update (`docs/install/`, `update-systemd.sh --rollback`).
