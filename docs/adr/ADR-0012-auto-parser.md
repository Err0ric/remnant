# ADR-0012: Automatic parser per line, and changing a source's parser

Status: **Accepted** 2026-10-11 (reviewed by the project owner; see Review outcome).

## Context

A source has one parser today: a template id, or the generic parser for its format (`SourceConfig.template_id`, SPEC 4). That fits a file written by one product (`/var/log/remote/fw01/traffic.log`). It does not fit a mixed stream, and mixed streams are the common case:

- A homelab `syslog` file holds sshd, sudo, systemd, cron, and firewall lines in one file.
- A Loki selector such as `{job="syslog"}` (ADR-0011) returns every program on every host in one source.
- A collector that writes one file per host, not per program, does the same.

Found in a live walkthrough on 2026-10-11: the demo syslog source runs the generic parser, so `src_ip`, `user`, and the other OCSF columns stay empty and field filters in Simple search match nothing (#112 now warns when that happens). The fix the user can apply today is splitting the stream by program upstream, which a team trying the product on Loki will not do.

A second gap from the same walkthrough: a source's parser cannot be changed after it is created. The only route is delete and re-add, which loses the source id, its group memberships, and its Loki position.

The pieces already exist. Every starter template has a `match` block (`app_name` list, `regex`, `min_confidence`), and `templates/matcher.py` already ranks templates deterministically for discovery (SPEC 3.6). Of the 24 starter templates, 6 match on `app_name` (sshd, sudo, systemd, PAM programs, named, unbound) and 18 on a payload regex (Palo Alto CSV type, CEF, LEEF, ASA, IOS, FortiGate, UniFi, Windows JSON, Snare, Windows DNS).

## Decision

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. Shape | A new parser choice on a source, **Automatic**, beside the template list and Generic. Each line's envelope is parsed once, then the line is routed to one template, or to the generic parser when none fits | One source for one stream, the way people actually collect | Make users split streams upstream |
| 2. Routing rule | Deterministic, first match in a fixed order: (a) templates whose `app_name` list contains the line's syslog APP-NAME/TAG; if several, the one whose `regex` (when present) matches; (b) otherwise templates with a `regex` and no `app_name`, tried in a precomputed order (most specific first: Palo Alto, ASA, IOS, FortiGate, UniFi, Snare, Windows JSON, then CEF, LEEF, JSON-over-syslog last); (c) otherwise the generic parser. No LLM, no per-line scoring | Cheap, predictable, explainable; a line's parser can be shown and reproduced | Score every template per line (slow, nondeterministic under ties) |
| 3. Which templates | Approved templates only: starter plus approved user templates. Drafts never | Same rule as everywhere (rule 4) | |
| 4. Recording the choice | `template_id` and `template_version` already exist per row; Automatic writes the chosen template's id, or empty for generic. `parse_status` unchanged | Every row says how it was parsed; no schema change | |
| 5. Cost and safety | App-name lookup is a dict hit. Regex routing runs at most N compiled patterns (currently 18) with the existing `regex` timeout per match; the order is cached per template set. A line that times out on every pattern goes to generic with `parse_errors` noting it | Bounded per-line cost; backtracking cannot stall ingest | |
| 6. Routing a misfire | If the routed template fails to parse the line (`parse_status=failed`), retry once with the generic parser so `time`, host, and `message` are still filled; record both in `parse_errors` | A wrong guess never loses the basics | Store the failure as is |
| 7. Changing a parser | Admins can change a source's parser (template, Generic, or Automatic) on the Sources page. Audited as `source.parser_change` with old and new. Applies to lines read **after** the change only; stored events keep the parser they were read with | Matches how classification relabelling works (#107); no silent rewrite of history | Re-parse stored events (see row 8) |
| 8. Re-parse history | Not in this ADR. Noted in `docs/BACKLOG.md`: re-parse a source's stored `raw` with its current parser into new partitions, audited, admin only | `raw` is kept so this is possible later; it is a heavier, separate feature | Build now |
| 9. Defaults | New syslog sources (file or Loki) default to **Automatic**. Existing sources keep what they have | Best first experience without changing anyone's current results | Keep Generic as the default |
| 10. Where it shows | Sources page: parser column shows "Automatic" and, in the source detail, a count of lines per routed template over the last 24 h (from the lake, no new state). Search event detail already shows `template_id` | User can see whether routing worked | |

## AI threat mapping

No LLM is involved. Log content selects the parser (an attacker who can write a log line can choose which template parses it, for example by setting a TAG of `sshd`). That is already true of discovery and of single-template sources, since the content decides the fields; routing never grants access, never changes classification, and `raw` is unchanged. ATT&CK T1562.006 (Indicator Blocking) and T1070 apply as before: a spoofed TAG can put misleading values in OCSF columns, which is why `raw` stays the source of truth and the event detail shows it.

## Questions for the owner

1. **Routing rule (row 2):** fixed deterministic order, app name first then regex (recommended), or score every template per line?
2. **Default (row 9):** Automatic for new syslog sources (recommended), or keep Generic and let admins opt in?
3. **History (rows 7 and 8):** a parser change affects new lines only, with re-parse of stored events in the backlog (recommended), or build re-parse now?

## Consequences

- `ingest/` gains a routing payload parser (`payload/auto.py` or a `Router` in `templates/`) built from the template registry; the pipeline interfaces are unchanged (rule 8): Automatic is one `PayloadParser`+`Normalizer` pair that delegates.
- `SourceConfig.template_id` accepts a reserved value `auto` (or a separate `parser` field); additive migration.
- `PATCH /api/sources/{id}` accepts the parser; Sources page edit control; audit action `source.parser_change`.
- Tests: a mixed fixture (sshd, sudo, systemd, cron, filterlog, Palo Alto, CEF in one file) asserting each line's `template_id`; a pathological line that times out every regex; a parser change mid-file affecting only later lines; the same through the fake Loki server.
- SPEC 3.6 and 4 updated, decisions row added, BACKLOG gains re-parse.

## Review outcome

| Question | Answer |
|---|---|
| 1. Routing rule | The recommendation: fixed order, app name first, then payload regex, then the generic parser |
| 2. Default | Automatic for new syslog and JSON sources (file and Loki); existing sources unchanged |
| 3. History | A parser change affects new lines only; re-parsing stored events goes to the backlog |

Implementation notes: Automatic is stored as the reserved parser id `auto` in `template_id`, so no template may use that id. Templates with multiline framing are never routed to, since routing is per line. A user template with a regex is tried before starter templates, and templates with no `vendor` (CEF, LEEF, JSON-over-syslog) are tried last.
