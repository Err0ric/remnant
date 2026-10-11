# ADR-0004: User lifecycle and source access defaults

Status: **Accepted** 2026-10-10 (reviewed by the project owner: every default below accepted as written).

## Context

SPEC 3.6 defines roles (Admin, Analyst, Auditor) and source groups as the access boundary (D17, D22), but leaves several behaviors open. In security tooling the defaults decide what happens when nobody configures anything, so they are written down here.

## Decision

| Question | Default | Reason |
|---|---|---|
| Do admins see every source? | Yes, implicitly | An admin can grant themselves any group, so restricting admins adds friction without protection. Every admin query is still audited with their user id |
| Source in no group | Invisible to Analysts and Auditors | Deny by default. A new source is visible only to admins until granted |
| User with no groups | Sees no events | Deny by default; the UI says why instead of showing an empty table without explanation |
| New user password | Admin issues a one-time invite link (single use, 24 hours, stored hashed); the user sets their own password | Admins never know or transmit passwords |
| Password reset | Admin issues a one-time reset link (single use, 24 hours); using it revokes all of that user's sessions and CLI tokens | Same as invite; a reset also ends any session an attacker may hold |
| Removing a user | Disable only, never delete; disabling revokes sessions and tokens immediately | Audit rows must always resolve to a person (T18) |
| Last active admin | Cannot be disabled or demoted, including by themselves | Prevents locking everyone out of administration |
| First user on a loopback install with no accounts | Must be an Admin | Creating any account ends open local mode; a non-admin first account would leave nobody able to administer |
| Role or group change | Takes effect on the next request; no re-login | Access removal must not wait for a session to expire |

## Consequences

- Admin is a trusted role. Installations that need data separation from the administrator (for example HR logs) need a separate installation; field-level masking and admin restriction are out of scope for v1 (SPEC 3.6).
- Invite and reset links are shown once to the admin, who passes them to the user out of band. Email delivery arrives with alert routing (Slice 4).
- The CLI keeps working with per-user, revocable tokens (SPEC 5.6); disabling a user revokes them.

## ATT&CK

| Threat | ATT&CK | Control |
|---|---|---|
| Orphaned or shared accounts (T18) | T1078 Valid Accounts | Per-user accounts, disable revokes sessions and tokens, no delete |
| Analyst reads sources they are not cleared for (T15) | T1213 Data from Information Repositories | Deny-by-default groups enforced server-side in the per-session events view |
| Intercepted invite or reset link | T1550 Use Alternate Authentication Material | Single use, 24 hour expiry, stored hashed, token in URL fragment |

## Review outcome

| Default | Answer |
|---|---|
| Admins see every source | Yes |
| Source in no group visible only to admins | Yes |
| User with no groups sees no events, and the UI says why | Yes |
| One-time invite link; users set their own password | Yes |
| Disable, never delete | Yes |
| Last admin cannot be disabled or demoted | Yes |
