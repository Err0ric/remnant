### Claude plugin downloads in one place (2026-11-02)

- **Settings > Claude plugins** is the only place to download the hooks plugin and mint its tokens. The OTLP source row now links there instead of downloading (each row download issued a new token and quietly broke earlier copies).
- Revoking the token picked in "Deployment token" switches the picker back to **New token**, so the next download no longer fails with "No such token, or it was revoked".
- **Include this server's self-signed certificate** is now unticked by default when people reach the server through a reverse proxy, or when the address you give is not a name on the server's certificate; a line under the checkbox says why.
- An empty **Pilot users** list now warns: "Everyone who installs this plugin will send records."
- What changes for existing installs: nothing to do. Plugins already downloaded keep sending until their token is revoked.
