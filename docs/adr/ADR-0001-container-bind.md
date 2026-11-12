# ADR-0001: First-run access and bind policy (including Docker)

Status: **Accepted** 2026-10-10 (SPEC D15 to D19). **Amended 2026-11-12 (D245, owner):** item 1 of the decision no longer holds. There is no no-sign-in mode; a loopback bind with no users is setup-only like any other, see "Amendment" below.

## Context

Security rule: anything reachable from the network requires authentication, and there is no insecure-mode flag.

Inside a container the server must listen on `0.0.0.0` for Docker port publishing to work, and the app cannot see how the host publishes the port. More importantly, the primary deployment target is a **team VM** next to the log collector, where analysts always connect over the network. So the real question is not Docker; it is how the first account gets created on a network-facing install.

## Options considered

| Option | Summary | Outcome |
|---|---|---|
| A. Manual token in `.env` | Admin generates and pastes a token before first start | Rejected: friction, tokens end up in files and chat |
| B. One-time setup link | First start with no users prints a single-use link that creates the admin account | **Chosen** |
| C. "Trusted publish" declaration | Config flag allows 0.0.0.0 without auth | Rejected: an insecure flag by another name |
| D. Host networking | App binds 127.0.0.1 on the host network | Rejected: Linux only, does not fit a team VM accessed remotely |

## Decision

1. **Loopback bind, no users:** ~~runs without login (single-user local convenience)~~ setup-only mode, as item 2 (D245). HTTP allowed.
2. **Non-loopback bind, no users:** setup-only mode. Every route except setup returns 403. The server log prints a one-time setup URL.
   - Token: 32 random bytes, stored only as a hash, single use, expires after 30 minutes. A restart issues a fresh link and invalidates the old one.
   - The setup page states: *"You are creating the administrator account for this installation."*
   - Once an admin exists, setup mode is permanently off. Lost-admin recovery is a local CLI command on the server, not a web route.
3. **Users exist:** normal login for everyone, on every bind.
4. **HTTPS** is on by default off loopback, with a self-signed cert generated on first start. Bring-your-own cert and reverse proxy setups are documented.
5. Same behavior with or without Docker. Docker is optional.

## Consequences

- Slice 1 auth work: setup mode, setup link, admin creation, login, TLS bootstrap.
- Landed in Slice 1: the interim bearer token (`APP_API_TOKEN`) and the refuse-to-start rule were removed once setup mode shipped. Recovery: `app-admin reset-password <username>` on the server.
- Not AI-facing. Mitigates T1190, T1078, T1550 (SPEC T9, T16).

## Amendment (D245, 2026-11-12)

Audit 2026-11 finding H1: `docs/install/tls.md` tells admins to bind the app to loopback behind a reverse proxy on the same host. With no accounts yet, item 1 made every request the implicit administrator, and behind the proxy every request comes from 127.0.0.1. A check on the Host or forwarding headers does not close it: nginx with a bare `proxy_pass` sends neither.

- No account, no access, on every bind. The first administrator is always created with the one-time link.
- The link is printed in the server log at every start with no accounts, and `app-admin setup-link` on the server prints a fresh one (needs shell access, like `reset-password`). The hash and expiry are kept in `meta.sqlite` so the command and the running server share them.
- A loopback link (`http://127.0.0.1:<port>/setup#...`) opens on the machine itself. From another computer: an SSH tunnel, or `server.public_url` so the link goes through the proxy.
- Installs that ran without sign-in: what the implicit `local` user owned goes to the first administrator when it is created; schedules run and source tokens deliver in between.
- Not AI-facing. Threat T9 (SPEC 7.1) now reads "no accounts: setup-only on every bind".
