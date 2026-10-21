# ADR-0009: Simple search (no SQL, no AI needed)

Status: **Accepted** 2026-10-11 (reviewed by the project owner: every recommendation accepted).

## Context

The goal is that people can search their logs without writing queries. Today there are two ways to search: SQL, which most analysts do not write day to day, and Ask, which needs an AI provider and a model good enough to write SQL. With no provider (the default on a fresh install, and the case CLAUDE.md rule 1 says must always work) the only way in is SQL, apart from the time range and source chips.

Analysts also arrive with habits from other tools:

| Tool | Language | Shape |
|---|---|---|
| Kibana, Elastic, Wazuh | KQL (Kibana Query Language), Lucene | `field:value`, free text, `AND`/`OR`/`NOT` |
| Graylog | Lucene-style | `field:value`, free text |
| Microsoft Sentinel, Defender, Azure Data Explorer | KQL (Kusto Query Language) | `Table \| where ... \| summarize ... by ...` pipes |
| Splunk | SPL | free text plus `\| stats ... by ...` pipes |

Two languages share the name KQL. The filter style (Kibana, Lucene, Graylog) is small and nearly the same everywhere. The pipe style (Kusto, SPL) is a full analytics language with hundreds of functions and different semantics per product.

A lot of searching is also just "find lines with this text", including on lines that only got an envelope parse (`parse_status=envelope_only`), where the useful part is in `message` and `raw`.

## Decision

| Question | Recommendation | Why | Alternative |
|---|---|---|---|
| 1. A no-SQL, no-AI search | A third Search tab, **Simple**, with one search box. The server compiles what is typed into SQL deterministically (no LLM), shows it under "Show SQL", and runs it on Enter. "Edit as SQL" copies it to the SQL tab | Searching works on every install with zero providers, and the SQL view teaches the schema as people go | Filter chips only (point and click, no box) |
| 2. Syntax | The common filter style from Kibana, Lucene, and Graylog. Bare words and `"quoted phrases"` match `message` or `raw`, case-insensitive. `field:value`, `field:"a b"`, `field:adm*` (wildcards), `field:>=400` (numbers and times), `-field:value` or `NOT`, `AND`, `OR`, parentheses; words next to each other mean AND. Example: `sshd "failed password" -user:root src_ip:203.0.113.*` | Most analysts already type this; it is small enough to implement and test fully | Invent our own syntax |
| 3. Field names | Every column in `core/schema.py` by its full name, plus short aliases for the common ones (`user`, `src_ip`, `dst_ip`, `src_port`, `dst_port`, `host`, `process`, `source`, `severity`), listed in one table next to the schema. A name that is not a column is looked up in `unmapped`, as Sigma does (D32), with a hint shown | Short to type, one source of truth, and fields a template did not map are still searchable | Full column names only |
| 4. Point and click | In an expanded event, each field value gets **Filter for**, **Filter out**, and **Top values**. The first two add `field:"value"` or `-field:"value"` to the box; Top values runs a count by that field over the current search | Most searches start from an event already on screen; no typing at all | |
| 5. Pipe languages (Kusto KQL, SPL) | Not supported as languages. The Ask tab accepts them: paste a Kusto or SPL query and Ask writes the SQL, shown for review and run on click, as with any Ask question. Ask's prompt gains a few translation examples | A partial Kusto or SPL parser would silently return different answers from the real thing, which is worse than a clear "use Ask to translate"; the full grammars are large and product-specific | Build a Kusto subset (`where`, `project`, `summarize count() by`) later, if users ask |
| 6. Aggregation without SQL | v1: Top values (row 4) and the existing Dashboard. No pipes in Simple | Keeps Simple a filter language; counts come from clicks | `\| count by field` and `\| top field` pipes in Simple |
| 7. Where it runs | One compiler in the backend (`search/simple.py`), used by the UI, the CLI (`query --match "..."`), and saved searches. Saved searches store the language, the typed text, and the compiled SQL; runs and schedules use the stored SQL, so a schedule never changes meaning | One implementation, deterministic, matches how Ask searches are saved (SPEC 5.3 step 5) | Compile in the browser |
| 8. Safety | Field names only from the schema allowlist and the alias table; every value is a bound parameter; wildcards become `ILIKE` with `%` and `_` escaped (no regex, so no backtracking); input capped at 2 KB and 50 terms; the compiled SQL still goes through `engine/guard.py` and the per-session `events` view | Log values and typed text never become SQL text; same guardrails as every query | |
| 9. Default tab | Simple the first time; after that, the tab last used on that browser (amends ADR-0008 row 5) | The easiest path is the first one people see | SQL first |

## Questions for the owner

1. **Simple tab (rows 1 and 2):** add Simple search with the Kibana/Lucene-style syntax (recommended)?
2. **Kusto KQL and SPL (row 5):** translate them through Ask (recommended), or plan a Kusto subset parser?
3. **Pipes for counts (row 6):** Top values by click only in v1 (recommended), or add `| count by` and `| top` to Simple?
4. **Default tab (row 9):** Simple first (recommended), or SQL?

## Consequences

- Search page tabs become **Simple**, **Ask in plain English**, **SQL** (Ask hidden from auditors, noted when no provider exists, per ADR-0008).
- New `search/simple.py` with table-driven unit tests (every operator, aliases, `unmapped` fallback, escaping, caps, rejection messages); `POST /api/search/compile` returns the SQL and parameters; the query endpoint accepts parameters.
- Saved search format (SPEC 5.4) gains `language` (`sql` or `simple`) and `text`; existing searches default to `sql`. Additive.
- SPEC 5.2 gains a Simple search section; DESIGN 6.1 shows the three tabs and the field actions.
- Build order: ADR-0008 (Overview, then Ask into Search) and this ADR fit together; the tab strip is built once with all three tabs.

## ATT&CK and ATLAS

Simple search is not AI-facing. The threat is SQL injection through typed text or through log values clicked into a filter (CWE-89); row 8 closes it with an allowlist for names, bound parameters for values, and the existing guard. Row 5 adds translation examples to the Ask prompt only; the Ask tool set, gate, and run-on-click rules are unchanged, so the SPEC 7 ATLAS rows for Ask (AML.T0051.001, AML.T0057) still apply as written.

## Review outcome

| Question | Answer |
|---|---|
| 1. Simple tab | Yes, with the Kibana/Lucene-style syntax |
| 2. Kusto KQL and SPL | Translated through Ask; no parser |
| 3. Pipes for counts | Top values by click only in v1 |
| 4. Default tab | Simple the first time, then the last used |

## Implementation note

Row 7 is stored as `origin.simple_text` on the saved search (next to `origin.ask_prompt`), with `mode` left as `query`, instead of new `language` and `text` fields. It carries the same information, needs no migration (the `mode` column has a CHECK constraint that SQLite can only change by rebuilding the table), and keeps the YAML format additive. Runs and schedules use the stored SQL, as decided.
