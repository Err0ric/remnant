# ADR-0005: Template drafts, approval, and the LLM parser draft flow

Status: **Accepted** 2026-10-10 (reviewed by the project owner: admin-only drafting, both sample sources, pasted samples local-only).

## Context

SPEC 4.5 describes the parser draft flow: deterministic envelope and format sniff, an optional LLM draft of the payload block only, a preview, tests, and approval that moves the file from `drafts/` to `data/templates/`. The threat model covers the main risk (T5: a drafted parser is malicious or broken). Several behaviors are still open, and in this tool a template decides what every future event from a source looks like, so they are written down before any code.

What already exists:

- `templates/matcher.py` runs the deterministic sniff and ranks templates (built for discovery, #47). Step 4 of 4.5 reuses it unchanged.
- The loader already reads `data/templates/*.yaml`, never `drafts/`, and validates and tests every template at load.
- The gate already has a `parser_draft` purpose that allows zero tools.

## Decision (proposed defaults)

| Question | Proposed default | Reason |
|---|---|---|
| Who can create, edit, test, and approve drafts | Admin only | A template changes how a source is parsed for everyone. Analysts can still preview a draft against a sample through the same endpoint, but cannot save it |
| Where the sample comes from | A file already under `allowed_roots` (path plus optional glob, as discovery uses) or a pasted sample of up to 200 lines and 256 KiB | Uploading arbitrary files would add a new write path to the server. Pasted samples are kept with the draft and deleted with it |
| Where drafts live | `data/templates/drafts/<id>.yaml`, plus a `template_drafts` meta table (author, created and updated times, sample reference, last test result, LLM call id if any) | Files keep the YAML editable and diffable; the table gives the UI a list without parsing files |
| What approval records | A `template_approvals` meta table row (template id, version, sha256 of the approved YAML, approved_by, approved_at, the LLM call id if any part was drafted by a model) and an audit row | SPEC 4.5 step 7 asks for approved_by, approved_at, and the LLM audit link. A hash pins exactly what was approved |
| What approval requires | Schema valid, every inline test passing (minimum 3), and the pathological check (10 KB garbage line and the sample's own lines) raising nothing | Same bar as starter templates, so a draft cannot be weaker than what ships |
| Replacing an approved user template | Allowed only with a higher `version`; the UI shows a diff against the current file; sources using it switch on the next ingest pass | Silent replacement would change parsing without a trace |
| Same id as a starter template | Refused. A customized copy takes a new id (for example `fortinet_fortigate_hq`) | Starter templates are updated with releases; shadowing them would hide fixes |
| Deleting an approved user template | Refused while any source uses it; otherwise allowed and audited | A source must never fall back to a parser silently (already the rule for missing templates) |
| What the LLM sees | The envelope result, the format sniff, up to 20 payload samples after envelope stripping (redacted when the provider is cloud and redaction is on), the template schema, and the OCSF column list. Samples go under the `data` key | SPEC 4.5 step 5 and security rule 2 |
| What the LLM returns | Only `payload`, `transforms`, `mapping`, and `tests`, validated against the schema; envelope, match, and id come from the deterministic side and the user | The model cannot change identity, envelope handling, or classification defaults |
| Classification of the sample for the gate | The sample takes the classification of the source it came from. A pasted sample is `local_only`, so with a cloud provider configured the draft step is blocked | Same scope rule as Ask; pasted logs are treated as the most sensitive case |
| Manual path | Every step except the LLM draft works with no provider: sniff, start from the closest matching template or a blank skeleton, edit, preview, test, approve | DoD item "Manual path works with no provider configured" |

## Consequences

- One new admin page (draft list, YAML editor, preview table, test results, approve) plus an "Edit as draft" action from discovery candidates that no template fits.
- Two additive migrations (`template_drafts`, `template_approvals`).
- The registry reloads after an approval; problems are reported as today.
- Drafts never reach ingest. A source cannot reference a draft id.

## ATLAS and ATT&CK

| Threat | ATLAS | ATT&CK | Control |
|---|---|---|---|
| Sample log lines carry instructions that steer the drafted parser (T1, T5) | AML.T0051.001 LLM Prompt Injection: Indirect | T1562.001 Impair Defenses | Samples only under `data`; zero tools; output schema-validated and limited to four blocks; inert until an admin approves; tests must pass |
| Drafted regex causes catastrophic backtracking (T5) | AML.T0043 Craft Adversarial Data | T1499 Endpoint Denial of Service | `regex` module with a timeout at compile and run time; pathological test before approval |
| Drafted mapping hides events (wrong class, dropped fields) (T5) | AML.T0043 | T1562.001 | Preview table and parse rate on the sample before approval; `raw` is always kept, so nothing is lost from the lake |
| Samples sent to a cloud provider leak data (T2) | AML.T0057 LLM Data Leakage | T1567 Exfiltration Over Web Service | Gate classification block (pasted samples are `local_only`), redaction for cloud, every call audited |

## Review outcome

| Question | Answer |
|---|---|
| Admin-only drafting, or Analysts save drafts for approval? | Admin only |
| Pasted samples, files under `allowed_roots`, or both? | Both |
| Cloud provider for pasted samples? | No: pasted samples are `local_only` |
