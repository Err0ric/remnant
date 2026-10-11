# ADR-0010: Redaction for cloud models

Status: **Accepted with changes** 2026-10-11 (reviewed by the project owner; see Review outcome).

## Context

Slice 5 asks for redaction with tokens that are stable per install and a reverse map applied to responses. SPEC 6.3 gives the token shapes (`IP_a3f9`, `USER_7c2e`, `HOST_11d0`) and says free text is not redacted, with a warning. It leaves open:

- **When it applies.** SPEC 6.2 runs redaction "if `redaction.enabled`" for cloud providers, but there is no setting yet, and no default.
- **What counts as free text.** Event data reaches a model as structured columns (`src_endpoint_ip`, `actor_user_name`, `device_hostname`) and as text (`raw`, `message`, `unmapped` values, Ask sample values). An IP or user name in `raw` is the same secret as the one in its column. Leaving `raw` alone would make column redaction pointless for Explain, which sends the raw line.
- **Token size.** Four hex characters (`a3f9`) give 65,536 values; a few hundred distinct IPs make collisions likely, and a collision would merge two hosts in the model's answer.
- **The reverse map.** Where it lives, how long, and what it applies to (Ask SQL, explanations, claims).

`local_only` sources never reach a cloud model at all (D30); redaction is for `cloud_allowed` data going to a cloud provider. Local providers are never redacted.

## Decision

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. When | On by default for every cloud provider. An admin can turn it off per provider (audited `provider.update`), with a warning in the form. Never applied to local providers | Safe default; some teams will accept a provider's terms and want real values | One install-wide switch, off by default |
| 2. Columns | Tokenized by value: IP columns (`src_endpoint_ip`, `dst_endpoint_ip`, `device_ip`) as `IP_`; `actor_user_name` as `USER_`; hostname columns (`device_hostname`, `src_endpoint_hostname`, `dst_endpoint_hostname`) as `HOST_` | The columns that identify people and machines | |
| 3. Text (`raw`, `message`, `unmapped`, Ask sample values, preview rows) | IPv4 and IPv6 addresses found by pattern become `IP_` tokens; email addresses become `USER_` tokens; and every user name and host name taken from columns in the same payload is replaced wherever it appears in the text (whole word, ignoring case). Anything else stays, and the UI says so where data is sent | Covers the same secret in the raw line; no guessing at names that never appeared in a column | Columns only, text untouched (SPEC 6.3 as written) |
| 4. Tokens | `<KIND>_` plus 8 hex characters of HMAC-SHA256 over the kind and the normalized value (IPs in canonical form, names lower-cased), keyed with a redaction key derived from the install key. Stable across calls and restarts | Grouping and correlation still work; 8 hex characters make collisions very unlikely at log scale; a token cannot be reversed without the key | 4 hex characters as in the SPEC 6.3 example |
| 5. Reverse map | Built per call from the values actually replaced, kept in memory for that call only, never stored or logged. Applied to everything shown from the response: Ask SQL (so `WHERE src_endpoint_ip = 'IP_1a2b3c4d'` shows and runs with the real address), explanations, assumptions, and claims. Tokens the model makes up that are not in the map are left as they are | Nothing new to protect at rest; the SQL the analyst reviews is the SQL that runs | Persist the map for later review |
| 6. Not redacted | `event_id`, times, ports, numeric ids, `source_id`, column names, and the prompt itself | Citations need event ids; the rest identifies no one on its own | |
| 7. Audit | `llm_calls.redaction_applied` as now, plus counts per kind (`{"IP": 12, "USER": 3, "HOST": 5}`) in the row; never the values or the map | Shows what left the box without leaking it | |

## Questions for the owner

1. **Default (row 1):** on for cloud providers with a per-provider off switch (recommended), or one install-wide switch?
2. **Raw text (row 3):** redact IPs, emails, and known names inside `raw` and `message` too (recommended), or columns only?
3. **Token length (row 4):** 8 hex characters (recommended), or the 4 shown in SPEC 6.3?

## Consequences

- `llm/redact.py` (planned in CLAUDE.md layout) holds the tokenizer and reverse map; `llm/gate.py` calls it for cloud providers before the audit row is completed and applies the reverse map to the validated response.
- Provider settings gain `redact` (default true for cloud). Additive meta migration for the counts column.
- SPEC 6.3 rewritten to match; a gate unit test per row.

## ATLAS and ATT&CK

| Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|
| Identifying data from `cloud_allowed` logs reaches a cloud model | AML.T0057 LLM Data Leakage | T1567 Exfiltration Over Web Service | Rows 1 to 3; local-only sources stay blocked (D30) |
| A prompt-injected log line asks the model to repeat real values | AML.T0051.001 Indirect Prompt Injection | | The model only ever saw tokens; the map is not in the prompt |
| Residual: names or secrets in free text that no column holds | AML.T0057 | | Stated in the UI where data is sent; documented |

## Review outcome

The owner's position: logs are not sent to cloud models at all unless someone explicitly says so, and once they have, the model sees the real log, users and hosts included. Sending is already opt-in twice: every source starts `local_only` and only an admin can mark it `cloud_allowed` (audited), and every cloud provider needs its own acknowledgment.

| Question | Answer |
|---|---|
| 1. Default | **Off.** Marking a source `cloud_allowed` is the consent, so a cloud model sees real values. Redaction stays available as an opt-in per provider (admin, audited) for teams that want it |
| 2. Raw text | When a provider opts in, rows 2 and 3 apply as written (columns and raw text), so an opted-in provider never sees a value in the raw line that its column hid. Stored logs are never changed either way |
| 3. Token length | 8 hex characters |

Rows 4 to 7 stand. The SPEC 6.2 line "if `redaction.enabled`" now means the provider's own `redact` setting, default false.
