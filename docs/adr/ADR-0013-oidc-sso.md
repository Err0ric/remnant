# ADR-0013: Optional single sign-on with OpenID Connect (Microsoft Entra ID first)

Status: **Accepted** 2026-10-11 (decisions 4, 5, and 7 answered by the project owner; see Review outcome).

## Context

D20 put SSO after v1: local accounts with Argon2 passwords, invite and reset links (ADR-0004), roles, and source groups. Two things move it forward:

- A team trial is planned in a Microsoft 365 shop. Its analysts already sign in with Entra ID and its policy expects MFA and conditional access on every web app. A second set of passwords for a security tool is the thing auditors flag.
- Other teams running the product in an enterprise will ask for the same, with Entra ID, Okta, or Google Workspace.

It has to stay optional. A homelab or a single analyst on a laptop must keep working with no identity provider, and SSO must never become the only way in.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Protocol | OpenID Connect, authorization code flow with PKCE (S256), `state`, and `nonce`. Confidential client (client secret). Generic OIDC with discovery, so Okta, Google, and Keycloak work; Entra ID is the documented and tested provider | One standard covers every major provider; the flow is the current best practice for server-side web apps | SAML 2.0: XML signature handling is a large, error-prone attack surface, and Entra supports OIDC for the same app |
| 2 | Turning it on | Server config only, off by default: `APP__SSO__ENABLED`, `ISSUER`, `CLIENT_ID`, `CLIENT_SECRET`, `LABEL`, `REQUIRED_GROUPS`, `PASSWORD_LOGIN`. The secret comes from the environment, is never logged, and is never shown by any API. The redirect URI is derived from the server's public URL | One place, reviewed with the rest of the install; nothing to misconfigure from a browser | A settings page (later, if asked for) |
| 3 | Which tenant | The configured issuer must be one tenant (`https://login.microsoftonline.com/<tenant-id>/v2.0` for Entra). The ID token's `iss` must equal it exactly. Multi-tenant issuers (`common`, `organizations`, `consumers`) are refused at start-up | Anyone with any Microsoft account could otherwise reach the callback with a valid token | |
| 4 | Who gets an account | **Invite first.** An administrator invites the person as today. The invite link offers "Continue with Microsoft"; that sign-in binds the Entra identity (`iss` + `sub`) to the invited account. After that, the account is found by `iss` + `sub` only, never by name or email. A sign-in from an identity that is not bound to an account is refused and audited | Being in the tenant is not enough; access stays a deliberate admin act. `sub` is stable and unique per app; UPNs and emails can change or be reused | Auto-create on first sign-in (rejected by the owner) |
| 5 | Group gate | Optional `REQUIRED_GROUPS` (Entra group object ids). When set, the ID token's `groups` claim must contain one of them on every sign-in, so removing someone from the Entra group locks them out at their next sign-in even though the account still exists here. Too many groups (the claim is replaced by an overage pointer) is refused with a message that points to the setup guide. The guide also sets "Assignment required" on the Entra enterprise app, so Entra itself refuses unassigned users | Both checks the owner asked for: an invite here and membership in Entra | Rely on "Assignment required" alone |
| 6 | Roles and source access | Stay in the app: Users page and source groups, as today. Nothing in the token changes a role | Works the same for every provider and keeps one place to answer "who can see what" | Entra app roles (rejected by the owner; can be added later) |
| 7 | Passwords when SSO is on | `PASSWORD_LOGIN=admins` (default when SSO is on): only administrators can sign in with a password, as a break-glass path if the identity provider is down or misconfigured. Analysts and auditors must use SSO, in the browser and for `remnant login`. `everyone` keeps both for all. Invite and reset links for non-admins finish with SSO only | Most accounts get the identity provider's MFA and conditional access; recovery never depends on it | Disable passwords entirely (no way back in if Entra breaks) |
| 8 | Sessions | A successful SSO sign-in creates the same server-side browser session as a password sign-in (same lifetime, cookie, CSRF). Refresh tokens are not requested or stored; access to the provider's APIs is not requested (`openid profile` scopes only, plus the groups claim) | Nothing long-lived from the provider is kept; the app only needs to know who you are | Keep refresh tokens and re-check groups mid-session (later, if needed) |
| 9 | The CLI | SSO users create a token on the **API tokens** page and give it to the CLI through `REMNANT_TOKEN`. Tokens stay per user, listed, and revocable. A device-code login for the CLI is in the backlog | Works today with no new protocol surface | Device authorization grant now |
| 10 | Flow binding | The start call is a POST (no tokens in URLs); it returns the provider URL and sets a short-lived, HttpOnly, `SameSite=Lax` cookie scoped to the callback path. The callback requires that cookie to match the stored flow (constant-time compare), and each flow is single use and expires in 10 minutes | Stops login CSRF and a stolen callback URL from signing a different browser in | State in the URL only |
| 11 | Token checks | ID token signature against the provider's published keys (RS256 or ES256 only, `kid` required, keys re-fetched at most once a minute on an unknown `kid`), `iss`, `aud` equals the client id, `exp`/`nbf`/`iat` with 2 minutes of clock skew, `nonce`, and `azp` when present. The token request goes to the discovered endpoint over HTTPS only | The standard checks; nothing from the token is trusted before they pass | |
| 12 | Errors shown | The callback redirects to the sign-in page with a fixed error code; the page maps codes to plain messages. Provider error text is audited, never shown or reflected | No reflected content from outside |

## Consequences

- New columns `users.sso_issuer` and `users.sso_subject` (additive migration, unique together when set). The Users page shows which accounts sign in with SSO.
- New endpoints: `POST /api/auth/sso/start`, `GET /api/auth/sso/callback`. `GET /api/auth/state` gains the SSO button label and whether passwords are limited to administrators.
- New audit actions: `auth.login` with `method: sso`, `auth.sso_refused` (reason: not invited, disabled, not in required group, token invalid), `user.sso_linked`.
- One new runtime dependency for JWT signature checks (PyJWT, which uses the `cryptography` package already installed), resolved under the 14-day rule.
- The server needs outbound HTTPS to the identity provider (discovery, keys, token endpoint). Installs with SSO off make no such calls.
- A setup guide, `docs/install/sso-entra.md`, lists the app registration steps, the redirect URI, the groups claim setting, and "Assignment required".
- D20 (SSO later) is superseded for OIDC; SAML stays out of scope.

## Threats

| ID | Threat | ATT&CK | Control |
|---|---|---|---|
| T24 | Someone in the tenant, or with any Microsoft account, signs in without being invited | T1078.004 Valid Accounts: Cloud Accounts | Single-tenant issuer checked exactly; accounts found by `iss` + `sub` bound through an admin's invite; optional required group checked every sign-in; refusals audited |
| T25 | Login CSRF or a stolen callback URL signs a victim's browser into another account, or replays a code | T1550.001 Application Access Token, T1557 Adversary-in-the-Middle | PKCE, `state`, `nonce`, flow cookie bound to the browser, single-use flows that expire in 10 minutes, code exchanged server-side with the client secret |
| T26 | Forged or substituted ID token | T1606 Forge Web Credentials | Signature against the provider's keys with an algorithm allowlist, `iss`, `aud`, `azp`, time, and `nonce` checks |
| T27 | Identity provider outage or misconfiguration locks everyone out | T1499 (impact analogous) | Administrators keep password sign-in by default; `app-admin reset-password` on the host still works |
| T28 | Client secret leaks | T1552.001 Credentials In Files | Environment only, never logged or returned by an API, rotation steps in the guide; the secret alone cannot sign anyone in without a matching invite and, if set, group membership |

Not AI-facing; no ATLAS mapping needed.

## Review outcome

Asked of the owner on 2026-10-11 and answered:

- New users: invite first, and the person must also be in the Entra group before SSO works (rows 4 and 5).
- Roles: set in the app (row 6).
- Passwords when SSO is on: administrators only (row 7).

## Security review, 2026-10-12

An independent review of the implementation (#135 to #138) found no critical or high issues. Fixed in the follow-up PR:

| Finding | Fix |
|---|---|
| Anyone could fill the in-memory flow store and push out real sign-ins in progress | `POST /api/auth/sso/start` limited to 60 per address per 5 minutes; a full store refuses new flows instead of dropping old ones |
| Unauthenticated callbacks and bad link tokens each wrote an audit row, and the audit table can never be trimmed | Refusal rows capped at 30 per address per 5 minutes |
| Two callbacks racing on one invite link could both sign in | The link is checked and deleted in the same transaction as the bind; the loser gets "expired" |
| With SSO on, a non-admin's correct password got a different answer from a wrong one (a password oracle) | Both now get the same 401 and the attempt stays counted |
| Sessions and CLI tokens that analysts got with a password before SSO was turned on kept working | At start-up with passwords limited, those sessions and tokens are ended and the count audited |
| A down provider tied up a worker for 10 seconds per sign-in attempt | A failed discovery is not retried for 30 seconds |
| Providers whose issuer ends in a slash always failed; a malformed `_claim_names` caused a 500 | The issuer from discovery is used as written; `_claim_names` type checked |
| SSO-only accounts showed as "Invite pending" | Pending means no password and no SSO identity |

Accepted as is: removing someone from the required group stops their next sign-in, but sessions (up to `session_hours`) and CLI tokens they already hold keep working until they expire. To cut access at once, use **Sign out everywhere** or disable the account. The setup guide says so.

## Addendum, 2026-10-12: providers like Authelia

Asked for by an early user running Authelia. Same design, three provider differences handled; no change to accounts, roles, or password rules.

| Change | Why | Control |
|---|---|---|
| Client secret sent as HTTP Basic by default (`client_secret_basic`, the OIDC default), or in the form body when discovery offers only `client_secret_post`; `SSO_TOKEN_AUTH_METHOD` overrides | Authelia's clients expect Basic; Entra accepts both | Secret still only to the discovered https token endpoint; never in URLs or logs |
| `SSO_EXTRA_SCOPES` (for example `groups`) | Authelia, Keycloak, and Authentik release groups only for a `groups` scope | Scope names validated; `openid profile` always sent |
| Groups and display name read from UserInfo when the ID token lacks them, only when needed (`SSO_REQUIRED_GROUPS` set, or no name) | Authelia keeps `groups` and `preferred_username` out of the ID token by default | UserInfo called with the access token over https; its `sub` must equal the ID token's (OIDC Core 5.3.2) or the sign-in is refused; JSON only; the access token is used once and not stored |

Guide: `docs/install/sso-authelia.md`. Tests: an Authelia-shaped fake provider (Basic only, groups only in UserInfo, a UserInfo for another subject).
