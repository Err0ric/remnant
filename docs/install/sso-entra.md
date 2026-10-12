# Single sign-on with Microsoft Entra ID

Optional. When it is on, people sign in with their Microsoft work account, so your MFA and conditional access policies apply. When it is off (the default), nothing changes. Design and threat notes: [ADR-0013](../adr/ADR-0013-oidc-sso.md).

How it works once set up:

| Who | How they get in |
|---|---|
| Administrators | Password (break-glass, works even if Entra is down) or Microsoft |
| Analysts and auditors | Microsoft only |
| Someone in your tenant with no invite | Refused, and the attempt is in the audit log |
| An invited person who is not in the Entra group | Refused at every sign-in until they are added |

Roles and source access stay on the **Users and access** page, as before.

Removing someone from the Entra group stops their next sign-in. Sessions and CLI tokens they already have keep working until they expire; to cut access at once, use **Sign out everywhere** or **Disable** on the Users page.

## Before you start

| Need | Notes |
|---|---|
| The server's address | The name analysts type, for example `https://siem.corp.example:8080`. It must not change later without updating Entra |
| An Entra role that can register apps | Application Administrator, Cloud Application Administrator, or Global Administrator |
| A security group for people allowed to use the app | For example `SIEM Users`. You need its **Object ID** |
| Outbound HTTPS from the server to `login.microsoftonline.com` | For sign-in only; nothing else is called |

## 1. Register the app

In the [Microsoft Entra admin center](https://entra.microsoft.com), open **App registrations**, then **New registration**.

| Field | Value |
|---|---|
| Name | Anything recognizable, for example `SIEM` |
| Supported account types | **Accounts in this organizational directory only** (single tenant) |
| Redirect URI | Platform **Web**, URI `https://siem.corp.example:8080/api/auth/sso/callback` (your address plus `/api/auth/sso/callback`) |

After **Register**, copy from the **Overview** page:

- **Application (client) ID**
- **Directory (tenant) ID**

## 2. Create a client secret

**Certificates & secrets**, **Client secrets**, **New client secret**. Pick an expiry (6 or 12 months) and put a reminder in your calendar to rotate it. Copy the **Value** right away; Entra shows it once. (The Secret ID is not what you need.)

## 3. Send group membership in the sign-in token

**Token configuration**, **Add groups claim**:

- Select **Security groups**.
- If you have Entra ID P1 or P2, select **Groups assigned to the application** instead. The token then lists only the groups you assign in step 4, which avoids the "too many groups" refusal for people in hundreds of groups.
- Under **ID**, choose **Group ID**.

## 4. Require assignment and assign the group

Open **Enterprise applications**, find the app by name.

1. **Properties**: set **Assignment required?** to **Yes**, then **Save**. Entra itself now refuses anyone not assigned.
2. **Users and groups**, **Add user/group**: add the `SIEM Users` group. (Assigning a group needs Entra ID P1 or P2; on the free tier, assign the people one by one.)

Permissions: the default delegated **User.Read** is enough. The app requests only `openid profile` and never calls Microsoft Graph.

## 5. Turn it on

### Docker Compose

Add to `.env` next to `docker-compose.yml`, then restrict the file:

```
SSO_ENABLED=true
SSO_ISSUER=https://login.microsoftonline.com/<Directory (tenant) ID>/v2.0
SSO_CLIENT_ID=<Application (client) ID>
SSO_CLIENT_SECRET=<secret Value>
SSO_REQUIRED_GROUPS=<Object ID of SIEM Users>
```

```bash
chmod 600 .env
docker compose up -d --force-recreate app
```

If analysts reach the app on a port other than 8080 or through a reverse proxy, also set `APP_PUBLIC_URL=https://the-address-they-use` so the redirect URI matches what you registered.

### systemd

Add the same settings to `/etc/remnant/remnant.env` with the `APP__SSO__` prefix (`APP__SSO__ENABLED=true`, `APP__SSO__ISSUER=...`, `APP__SSO__CLIENT_ID=...`, `APP__SSO__CLIENT_SECRET=...`, `APP__SSO__REQUIRED_GROUPS=...`), keep the file at mode 0640 owned by `root:remnant`, then `systemctl restart remnant`.

### Check

The sign-in page now shows **Continue with Microsoft** above the password form. The server refuses to start if the issuer names `common` or `organizations` instead of your tenant, or if it cannot tell its own public address.

## 6. Bring people in

1. **Users and access**, **Invite user**, choose the role, send the invite link as before. The username can be anything; their email address is a good choice.
2. They open the link and click **Continue with Microsoft**. That sign-in ties their Microsoft account to this account. From then on they just use **Continue with Microsoft** on the sign-in page.
3. Existing analysts who had passwords: click **Reset link** for each and send it. They finish it the same way. Turning SSO on ends the sessions and CLI tokens they got with a password.

Administrators keep their passwords. A new administrator's invite can be finished either way; one finished with Microsoft has no password until you send a **Reset link** and they choose **Administrator? Set a password instead**.

## The command-line client

`remnant login` takes a password, which SSO accounts do not have. Instead, open your account (your name in the top bar), create a token under **CLI and API tokens**, and give it to the CLI:

```bash
export REMNANT_SERVER=https://siem.corp.example:8080
export REMNANT_TOKEN=<token>     # or store it in your shell's secret manager
remnant tail linux_auth -n 20
```

Tokens are per person, are listed on the same page, and can be revoked there.

## When something goes wrong

The sign-in page shows a plain reason. Details, including Entra's error code, are in the **Audit log** under `auth.sso_refused`.

| Message | Fix |
|---|---|
| "does not have access here yet" | Send an invite (or reset) link and have them finish it with Microsoft |
| "not in the group allowed" | Add them to the group in `SSO_REQUIRED_GROUPS`. Membership is checked at every sign-in |
| "in too many groups to check" | Step 3: choose **Groups assigned to the application** |
| "was cancelled or refused" | Usually Entra refused: not assigned to the app (step 4), conditional access, or consent. Check Entra's **Sign-in logs** for the user |
| "cannot be reached right now" | The server cannot reach `login.microsoftonline.com`, or the issuer is wrong. Check the tenant ID |
| "took too long or was already used" | Start again from the sign-in page; each attempt is valid for 10 minutes in one browser |
| Entra says the redirect URI does not match (AADSTS50011) | The URI in step 1 must equal your public address plus `/api/auth/sso/callback`, including the port |

Locked out of SSO entirely: sign in as an administrator with a password, or on the server run `app-admin reset-password <admin-username>` (Docker: `docker compose exec app app-admin reset-password <admin-username>`).

## Rotating the secret

Create a new secret in Entra (step 2), put its value in `.env` or `remnant.env`, restart, sign in once to check, then delete the old secret in Entra.

## Turning it off

Set `SSO_ENABLED=false` (or remove the lines) and restart. Analysts then need passwords again: send each a **Reset link**.

## Other providers

Authelia has its own guide: [sso-authelia.md](sso-authelia.md).

Any OpenID Connect provider with discovery works the same way: set `SSO_ISSUER` to its issuer URL, register `.../api/auth/sso/callback` as the redirect URI, and set `SSO_LABEL` to the button text (for example `Okta`). `SSO_REQUIRED_GROUPS` needs the provider to put a `groups` claim in the ID token; leave it empty otherwise.
