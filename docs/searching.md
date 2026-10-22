# Writing searches that keep working

Saved and scheduled searches outlive the parsers that shaped their data. When a source's parser changes (a new template, a better match after an upgrade, a stream label that now fills in a missing header), the same log line can land in different columns. A search that matched yesterday can quietly return zero today.

## Match text on `raw`, not `message`

| Column | What it holds | Stable across parser changes? |
|---|---|---|
| `raw` | The original line, exactly as received | Yes. Never trimmed or changed (CLAUDE.md rule 5) |
| `message` | Whatever the current parser calls the message: the whole line for a generic parser, often only the free-text part for a specific one | No |
| Parsed columns (`actor_user_name`, `src_endpoint_ip`, `dst_endpoint_hostname`, ...) | Typed fields from the template | Yes, when a template maps them |

Example from a real install: DNS lines first parsed by the generic syslog parser held the whole query in `message`. After an upgrade matched them to the `dns_bind` template, `message` held only the part after the header, and a search with `message LIKE '%query: %example.com%'` dropped to zero.

```sql
-- Breaks when the parser changes
SELECT count(*) FROM events WHERE message LIKE '%Failed password%'

-- Keeps working: the original line
SELECT count(*) FROM events WHERE raw LIKE '%Failed password%'

-- Best when the template maps the field
SELECT count(*) FROM events WHERE dst_endpoint_hostname = 'example.com'
```

The Simple search tab already matches text against `raw` as well as `message`.

## When it happens anyway

When a scheduled search drops to zero right after a source it reads switched parser, its Dashboard panel says so, for example: "Parser changed for dns at 2026-10-21 03:00 UTC (generic_syslog to dns_bind)." Open the search, move text matches to `raw` or to the parsed column, and save it; the schedule asks for a review before it runs the changed search.
