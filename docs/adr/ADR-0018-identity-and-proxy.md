# ADR-0018: One person under several names, and an outbound proxy

Status: **Accepted** 2026-10-14 (project owner asked for both). Recorded as SPEC D45 and D46; threats T41 and T42.

## Context

The same person shows up under several names: `alice` (an endpoint's OS user, a Linux login), `CORP\alice` (Windows), `alice@example.com` (Entra, Claude Code telemetry), `ALICE@EXAMPLE.COM`. The investigator's AI flow and the risk list show them as different people, which splits one person's activity and risk across rows.

Separately, some networks only reach the internet through an HTTP proxy, often one that inspects TLS with its own certificate authority. The Microsoft 365 and Anthropic sources and Teams or Slack alerts cannot work there today.

## Decision: identities

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | What is merged without asking | Only rewrites that cannot be wrong: case and surrounding spaces, a `DOMAIN\` prefix, and an email address in an **organization domain** the administrator listed, which becomes its local part (`alice@example.com` and `alice` are one person when `example.com` is listed). Machine accounts (ending `$`) are left alone | Deterministic and explainable; the administrator states which domains are "us" |
| 2 | How a person is shown | The email form in the first organization domain (`alice@example.com`), or the name as it is when no domain is listed | Readable, and matches what Entra and Microsoft 365 show |
| 3 | Anything else | **Aliases**: the administrator maps a name to a person (`jsmith` to `john.smith@example.com`), by hand or by accepting a suggestion | Similar-looking names are not proof |
| 4 | Suggestions | (a) **Organization domain**: an email domain whose local parts also appear as bare names, with examples; (b) **Same machine**: a host where exactly one email-style name and exactly one other name were seen, leaving out root, admin, system, service accounts, and machine accounts. Each shows its evidence; nothing is applied until accepted | Evidence the administrator can check; never applied automatically |
| 5 | Where it applies | Read time only, in the server-built SQL of Investigations (risk, entity lanes, AI flow) and AI usage. Stored events, `raw`, and `actor_user_name` never change; Search shows names as logged | Rule 5 (raw is sacred) and no re-ingest; a mapping change takes effect at once and can be undone |
| 6 | Who | Administrators set domains and aliases and accept suggestions; audited `identity.change`. Everyone's views use the same mapping | One mapping per install |

## Decision: outbound proxy

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Configuration | `network.https_proxy` (`http://` or `https://` host and port, no credentials in the URL), `network.proxy_username` and `network.proxy_password` (environment variables, like other secrets), `network.ca_bundle` (an extra PEM bundle trusted for outbound TLS, for proxies that inspect TLS) | Secrets stay out of YAML; corporate inspection needs its CA |
| 2 | What uses it | The Microsoft 365 and Anthropic sources (fixed host allowlists) and Teams and Slack alert targets (fixed domain suffixes) | Their destinations are fixed public services, so the proxy cannot be used to reach internal addresses |
| 3 | What does not | Loki, generic webhooks, SMTP, and model providers stay direct | They are often internal; through a proxy the server could not enforce its private-address rules (ADR-0007 row 4) |
| 4 | DNS and pinning | Through the proxy, the server does not resolve or pin the address; it sends `CONNECT host:443` and still checks the certificate against the host name, with redirects off and the same size caps | Proxied networks often have no external DNS; the host allowlist is the control |
| 5 | CA bundle | Added to the system trust store for outbound HTTPS from connectors and alerts, proxied or not | Transparent inspection also needs it |

## Consequences

- New tables `identity_domains`, `identity_aliases` (migration 32); API `GET /api/identities`, `PUT /api/identities/domains`, `PUT /api/identities/aliases`; a Settings page **Identities** (Access group).
- New config section `network`; `docs/install/proxy.md`.
- Search and Sigma keep exact names; the merge is a reading aid in Investigations and AI usage, stated on those pages.

## Threats

| ID | Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|---|
| T41 | A crafted name (an attacker logs in as `alice@example.com` on a lab box) is merged into a real person's activity, hiding or framing them | n/a | T1036 Masquerading | Merging only by the listed domains and accepted aliases; suggestions show evidence and are never automatic; Search keeps exact logged names |
| T42 | The proxy, or a wrong CA bundle, intercepts connector credentials or tokens | n/a | T1557 Adversary-in-the-Middle | Proxy and CA are administrator configuration only; certificate names still checked; proxy limited to fixed public hosts; documented that a TLS-inspecting proxy sees connector traffic |
