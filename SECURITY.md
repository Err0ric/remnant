# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: on this repository, open **Security > Report a vulnerability**. Do not open a public issue for a security problem.

Include what you found, how to reproduce it, and the version (commit) you tested. You will get an acknowledgement, and a fix or a plan, as soon as practical; this is a personal open-source project, so there is no formal response time.

## Supported versions

The project is in early preview. Only the latest commit on `main` gets fixes.

## Scope

In scope: the server, the web UI, the CLI, the shipped parser templates, and the Docker setup in this repository. Areas of particular interest:

- Ways around sign-in, roles, or per-source access (including through Ask, saved searches, schedules, or the CLI)
- Ways to make the query engine write, read files, or reach the network
- Log content that executes in the browser or terminal, or steers the AI features into acting on its instructions
- Ways to send `local_only` data to a cloud model provider
- Single sign-on flaws (account binding, token checks)

Design notes and the threat model are in `docs/SPEC.md` section 7 and `docs/adr/`.

Out of scope: problems that need an already compromised server or administrator account, and denial of service from log volume alone.
