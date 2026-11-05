### Why a Claude plugin token was refused (2026-11-02)

- **Settings > Claude plugins** now lists, under each deployment token, every machine that sent with it and when it was last seen, and the last reason the server refused that token: revoked, its source turned off or removed, a bad payload, or too many requests.
- A new **Unknown tokens** section lists tokens the server refused because they match none of its own (usually an old download), by their first 8 characters and the sending address. The full token is never kept.
- What changes for existing installs: nothing to do. The server adds two columns to its token table on the first start. Unknown tokens are kept in memory only, so the list starts empty after a restart.
