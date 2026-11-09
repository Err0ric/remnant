# ADR-0047: Locking the query connection so it cannot write

- Status: Accepted 2026-11-08 (owner); decision D225
- Threat: T2 (SPEC 7). Owner decision 2026-11-08: the connections that run user and model SQL may only read the lake and the rollups, and writes must be impossible from them even if the SQL guard (`engine/guard.py`) were bypassed

## Context

SPEC 5.1 and CLAUDE.md rule 7 said user and model SQL runs on a DuckDB connection opened `read_only=True`. The code did not: every query opened an in-memory connection, defined its views, then set `allowed_directories` to the caller's source folders, `enable_external_access = false`, and `lock_configuration = true`. A security review ran SQL directly on that connection, past the guard: `COPY (SELECT 1) TO '<lake>/source=x/day=y/x.parquet'` succeeded, because DuckDB treats an allowed folder as readable and writable.

What DuckDB 1.5.5 offers, tested in this PR:

| Control | What it does | What it does not do |
|---|---|---|
| `read_only=True` | Refuses writes to the main database | Cannot be used with `:memory:`; with a database file it still allows temporary tables and views, `COPY ... TO`, and overwriting any allowed file |
| `allowed_directories` | Allows every path under a folder | Allows writes there too (the review finding) |
| `allowed_paths` | Allows exactly the listed files; a glob is refused | Allows writes to a listed file. The default `COPY` writes `tmp_<name>` beside the target first and is refused, but `COPY ... (USE_TMP_FILE false)` overwrites a listed file in place |
| `enable_external_access = false` | Refuses every other path, `INSTALL`, `ATTACH` of a file, and `LOAD` from a file | DuckDB adds its own spill folder (`temp_directory`) to the allowed folders, so a `COPY` into the spill folder is possible |
| `lock_configuration = true` | Refuses `SET` and `RESET` of every setting | Nothing more |
| `autoinstall_known_extensions`, `autoload_known_extensions`, `allow_community_extensions`, `allow_persistent_secrets` (all false) | No extension installed or loaded on demand, none from the community, no secret written to disk | Built-in extensions (parquet, json, icu, core functions) stay loaded |

So DuckDB cannot, on its own, make every write impossible on a connection that must read the lake: there is no per-path read-only switch, and the spill folder is always writable.

## Decision

Three layers, each enough to stop a write the other two miss, in the order a query meets them:

| # | Layer | Where | Stops |
|---|---|---|---|
| 1 | The sqlglot guard (unchanged, plus three function families) | `engine/guard.py` | Every statement but one `SELECT`; table functions; file, setting, and catalog functions. Added: `json_execute_serialized_sql` and the `json_*serializ*` functions that feed it, `parquet_*` (footer readers such as `parquet_kv_metadata`), and `*_credentials` and `*secret*` (`load_aws_credentials`) |
| 2 | Statement check with DuckDB's own parser | `_select_only` in `engine/duckdb.py`, on the query's connection, before it runs | Anything DuckDB itself does not parse as exactly one `SELECT`: `COPY` (including `USE_TMP_FILE false` over a listed file and into the spill folder), `CREATE`, `DROP`, `ATTACH` (also `:memory:`), `SET`, acting `PRAGMA`s, `CALL`, `CHECKPOINT`, `VACUUM`, `EXPORT`, `INSTALL`, `LOAD`, several statements. No parser difference between sqlglot and DuckDB can carry a statement past both |
| 3 | Connection lock | `_lock` in `engine/duckdb.py` | The views are built first, then `allowed_paths` is set to the exact files they read (lake files by name, as before; rollup files are now listed by name too, not globbed), with no `allowed_directories`. Then external access off and the configuration locked. With layers 1 and 2 bypassed: no new file can be created anywhere but the spill folder, no file outside the list can be read or listed (`/etc/hostname`, another source's files, a glob of the lake), no `INSTALL`, `LOAD`, `ATTACH` of a file, `EXPORT`, or `SET` |

Every surface that runs user or model SQL (Logs SQL, Search, saved and scheduled searches, exports, Ask, MCP) calls `QueryEngine.run`, which always opens a new locked connection. Kept page instances (D146, `server.query_pool`) run only the app's own page SQL; their files change between queries, so they keep folder access to the lake and rollups, and layer 2 applies to them as to every query.

Metadata pragmas that DuckDB rewrites into a `SELECT` (`PRAGMA database_list`, `SHOW TABLES`) pass layer 2; they read the in-memory catalog only, and layer 1 refuses them anyway.

## Not closed by the connection alone

With both the guard and the statement check bypassed (code running arbitrary SQL on the raw connection):

1. `COPY ... (USE_TMP_FILE false)` can overwrite a file the query's views list (a lake or rollup file of the caller's own scope). The integrity ledger (ADR-0022) reports such a change at the next check.
2. A `COPY` can write into the spill folder (`<data>/tmp/duckdb`), which DuckDB allows for itself. It is outside the lake, never read as data, and emptied at every start.
3. Temporary and in-memory catalog objects can be created or dropped; they live only as long as the connection, which serves one query.

Options considered and not taken:

| Option | Why not |
|---|---|
| `read_only=True` on a per-query copy of an empty database file (measured: about 0.2 ms more per query) | Closes none of the three gaps: temporary objects, `COPY`, and overwriting a listed file all still work. It would only make the old SPEC wording literally true |
| Register a read-only Python filesystem and disable `LocalFileSystem` | Every Parquet read would go through Python: far slower |
| Make lake files read-only on disk (mode 0444 after write) | A real OS-level stop for non-root installs, but it touches ingest, compaction, and retention, and a root container ignores it. Kept as a follow-up for the owner to decide |

## Consequences

- SPEC 5.1 and T2 describe the three layers instead of `read_only=True`; CLAUDE.md rule 7 gets the same wording once this ADR is accepted.
- Rollup views list their files at query time instead of globbing; a rollup file replaced between listing and reading is retried once, as lake files already were (`_vanished`).
- A query that the guard accepts but DuckDB parses as something other than one `SELECT` is now refused with the guard's message. None is known; the eval set and the page queries pass.
- Measured latency (2 vCPU machine shared with other jobs, 90 lake files, 60 interleaved runs, connection included): a count 55 to 61 ms before and 57 to 60 ms after, a GROUP BY 56 to 64 ms before and 66 to 71 ms after, a rollup sum 41 ms before and 38 to 45 ms after. The cost is DuckDB checking each file against `allowed_paths` (a few ms with 90 files; at 1,000 files it stayed within the noise of folder access). The DuckDB-parser check costs about 5 microseconds.

## ATLAS and ATT&CK

AML.T0051.001 (indirect prompt injection that makes generated SQL write or exfiltrate), AML.T0057 (LLM data leakage through file reads), ATT&CK T1059 (command and scripting interpreter) and T1565.001 (stored data manipulation).
