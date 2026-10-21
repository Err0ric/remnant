# Single sign-on with Authelia

Optional, like every sign-in provider: with SSO off, nothing changes. How accounts work (invite first, roles in the app, administrators keep a password) is the same as with Entra ID; see [sso-entra.md](sso-entra.md) for that part and [ADR-0013](../adr/ADR-0013-oidc-sso.md) for the design.

Written against Authelia 4.38 and later. Check key names against the docs for your version.

## What is different from Entra ID

| | Authelia | What the app does |
|---|---|---|
| Client secret | Sent as HTTP Basic by default | Uses Basic unless the provider only offers `client_secret_post` (`SSO_TOKEN_AUTH_METHOD` overrides) |
| Groups | Only with the `groups` scope, and returned by UserInfo rather than in the ID token | Requests `groups` when `SSO_EXTRA_SCOPES=groups`; reads groups from UserInfo when the ID token has none and `SSO_REQUIRED_GROUPS` is set; refuses a UserInfo answer for a different `sub` |
| Who may sign in | Authelia's authorization policy for the client | Invite first; optional `SSO_REQUIRED_GROUPS` checked at every sign-in |
| MFA | Authelia's `two_factor` policy | Nothing extra |

## 1. Authelia: register the client

Generate a client secret and its hash (keep the plain one for step 2):

```bash
docker run --rm authelia/authelia:latest authelia crypto hash generate pbkdf2 \
  --variant sha512 --random --random.length 72 --random.charset rfc3986
```

Add to Authelia's `configuration.yml`:

```yaml
identity_providers:
  oidc:
    authorization_policies:
      siem:
        default_policy: deny          # nobody unless a rule says so
        rules:
          - policy: two_factor
            subject: 'group:siem-users'
    clients:
      - client_id: 'siem'
        client_name: 'SIEM'
        client_secret: '$pbkdf2-sha512$...'          # the Digest from the command above
        public: false
        authorization_policy: 'siem'
        require_pkce: true
        pkce_challenge_method: 'S256'
        redirect_uris:
          - 'https://siem.example.internal:8080/api/auth/sso/callback'
        scopes: ['openid', 'profile', 'groups']
        response_types: ['code']
        grant_types: ['authorization_code']
        token_endpoint_auth_method: 'client_secret_basic'
        userinfo_signed_response_alg: 'none'         # plain JSON UserInfo
        consent_mode: 'implicit'                     # optional: skip the consent screen
```

Restart Authelia. The redirect URI must match the app's public address exactly, port included.

## 2. The app: turn it on

Docker Compose, in `.env` next to `docker-compose.yml` (then `chmod 600 .env`):

```
SSO_ENABLED=true
SSO_ISSUER=https://auth.example.internal
SSO_CLIENT_ID=siem
SSO_CLIENT_SECRET=<the plain secret from step 1>
SSO_LABEL=Authelia
SSO_EXTRA_SCOPES=groups
SSO_REQUIRED_GROUPS=siem-users
```

```bash
docker compose up -d --force-recreate app
```

systemd installs use the same settings with the `APP__SSO__` prefix in `/etc/remnant/remnant.env` (`APP__SSO__EXTRA_SCOPES=groups`, and so on).

`SSO_ISSUER` is Authelia's own address, exactly as its discovery document states it (`https://auth.example.internal/.well-known/openid-configuration` shows it as `issuer`). Authelia's address must be `https` and reachable from the app's server.

`SSO_REQUIRED_GROUPS` is optional when Authelia's policy already limits the client to the group, as above. Setting both means both must agree, and removing someone from the group in Authelia stops their next sign-in either way.

## 3. Check

- The sign-in page shows **Continue with Authelia**.
- Invite someone, have them open the link and click **Continue with Authelia**: they sign in through Authelia (with 2FA under `two_factor`) and land in the app.
- Someone outside `siem-users`: Authelia refuses them, or, if Authelia lets them through, the app shows "not in the group allowed to use this app".

## When something goes wrong

The app's sign-in page shows a plain reason; details are in the **Audit log** under `auth.sso_refused`. Authelia's own log has its side.

| Symptom | Likely cause |
|---|---|
| Authelia: "invalid_client" | The secret or `token_endpoint_auth_method` does not match. Set `SSO_TOKEN_AUTH_METHOD=client_secret_post` if the client uses `client_secret_post` |
| Authelia: redirect URI mismatch | `redirect_uris` must equal the app's public address plus `/api/auth/sso/callback` |
| App: "not in the group allowed" for a member | `groups` missing from the client's `scopes`, or `SSO_EXTRA_SCOPES=groups` not set |
| App: "cannot be reached right now" | The app's server cannot resolve or reach Authelia, or `SSO_ISSUER` differs from Authelia's `issuer` |
| App: "cannot be reached right now", audit detail "userinfo did not return JSON" | `userinfo_signed_response_alg` is not `none` (signed UserInfo is not supported) |
