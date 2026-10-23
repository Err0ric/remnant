# ADR-0006: Where Sigma rules come from, what they run against, and how matches are shown

Status: **Accepted** 2026-10-10 (reviewed by the project owner: every recommendation in the table accepted).

## Context

D7 and D13 already decide the engine: pySigma with our own DuckDB backend (a subclass of pySigma's text query backend) and a compatibility field pipeline first. Checked on 2026-10-10:

- There is no DuckDB backend for pySigma. The nearest is the SQLite backend (LGPL-3.0, v2.0.0), which is SQLite specific (`REGEXP` needs a registered function, `COLLATE NOCASE`, `GLOB`). It is a reference, not a dependency.
- SigmaHQ rules are under the Detection Rule License 1.1: free to use, change, and redistribute, including commercially, but the rule author must be named wherever the rules are reproduced **and in views that show matches**.

What is still open is everything around the engine. Each row has a recommendation; the questions at the end are the ones that need the owner.

## Decision (proposed)

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. Where rules come from | No rules bundled in the image. An admin points the server at a folder of `.yml` rules under `allowed_roots` (for example a `git clone` of SigmaHQ, or their own rules) and imports it. Each import is a pinned, audited snapshot (file sha256, rule id, author, title). Updating means importing again | Local-first: no outbound call to fetch rules. Pinned snapshots mean a rule cannot change under a schedule without an admin action. Keeps DRL attribution with the rule | Bundle a tested SigmaHQ release in the image (works offline out of the box, but ages with the image and every release carries their license notice) |
| 2. What a rule runs against | Each template declares the Sigma `logsource` values it produces (`product`, `service`, `category`); a rule runs only on sources whose template matches its logsource, and always inside the caller's permitted sources. Rules with no matching source are listed as "no data" rather than run on everything | Running every rule on every source wastes time and invites false positives (a Windows rule matching a firewall `message`). Ties into the Slice 3 item "templates declare `category`" | Let the admin map logsources to sources by hand per rule set |
| 3. Fields the schema does not have | Map known Sigma fields to OCSF columns (the compatibility pipeline). Any other field reads `unmapped` (`json_extract_string(unmapped, '$.Field')`). A rule whose fields are mapped neither way does not compile and is listed with the reason | Most Windows Sigma fields (`TargetUserName`, `LogonType`, `IpAddress`) already sit in `unmapped` from the Windows templates, so rules work before every field gets a column | Refuse any rule using an unmapped field (higher precision, much lower coverage) |
| 4. Case | Case-insensitive by default, as the Sigma spec requires (`ILIKE`, `lower()`); `|cased` honoured | Sigma rules are written assuming it; case-sensitive matching silently misses events | Case-sensitive for speed (wrong results) |
| 5. Who does what | Admin imports, enables, and disables rules. Analyst runs them on demand and sees matches. Auditor sees matches. Every run is audited; scheduled runs act as the schedule owner with permissions re-checked each run (already in the Slice 4 DoD) | Matches SPEC 3.6 roles | Analysts manage their own rules |
| 6. Matches | Stored with rule id, rule version (snapshot sha256), event ids, and run id. **Every view of a match shows the rule's author and title**, as DRL 1.1 requires. A rule that lists no author is shown as "author not stated" | License compliance and traceability | |
| 7. Rule content is untrusted | Rule YAML loads through `core/safeyaml.py`. Compiled SQL still goes through the guard (SELECT only, `events` view only); values are escaped by the backend and the guard rejects anything else. Regexes compile with the `regex` module and a time limit at load. A rule that fails any of this is refused at import with its reason | A shared rule set is input from the internet, like log lines | |
| 8. Out of scope for Slice 4 | Correlation rules (`event_count`, `temporal`), the OCSF-native pipeline (D13), rule editing in the UI | Thin slice; coverage of single-event rules first | |

## Questions for the owner

1. **Rule source (row 1):** admin-imported folders with no bundled rules, or bundle a SigmaHQ release in the image?
2. **Rule scope (row 2):** templates declare Sigma logsources and rules run only on matching sources (recommended), or should every rule run on all permitted sources?
3. **Unmapped fields (row 3):** read fields from `unmapped` when there is no column (recommended, more coverage), or refuse those rules (more precise, far fewer rules)?
4. **Anything in rows 4 to 8 you disagree with?**

## Consequences

- Template schema gains an optional `sigma.logsource` list (additive). Starter templates get it filled in.
- New meta tables (additive): rule snapshots, rules, rule runs, matches.
- The compile rate against the SigmaHQ core `linux` and `windows` rules is measured in CI from a pinned release and recorded in SPEC, per the Slice 4 DoD.
- UI: a Detection rules page (import, enable, run, last result) and a matches view with author and title on every row.

## ATT&CK

| Threat | ATT&CK | Control |
|---|---|---|
| Hostile rule set (catastrophic regex, huge rules) stalls detection | T1499 Endpoint Denial of Service | `regex` timeouts at load, size and count limits on import, per-run time limit |
| A rule crafted to read data the runner should not see | T1213 Data from Information Repositories | Runs only on the caller's `events` view; compiled SQL passes the guard |
| A rule silently changed to stop matching | T1562.001 Impair Defenses | Pinned snapshots with sha256; enable, disable, and import are audited |

Not AI-facing, so no ATLAS mapping. If Ask or explain later reads matches, that is covered by the gate as today.

## Review outcome

| Question | Answer |
|---|---|
| 1. Rule source | Admin-imported folders, pinned snapshots; no rules bundled, nothing fetched |
| 2. Rule scope | Templates declare Sigma logsources; a rule runs only on matching sources, inside the caller's permitted sources |
| 3. Unmapped fields | Read from `unmapped` when there is no column |
| 4. Rows 4 to 8 | Accepted: case-insensitive, admin manages rules, author and title shown on every match, rule content untrusted, correlation rules out of scope for Slice 4 |
