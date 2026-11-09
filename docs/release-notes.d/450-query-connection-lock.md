### Query connections can read only the files a query needs (2026-11-08)

- Every query from Logs, Search, saved and scheduled searches, exports, Ask, and MCP now runs on a connection that may open only the exact lake and rollup files its views read. No new file can be written in the lake, the rollups, or anywhere else, even by SQL that got past the query check.
- DuckDB's own parser now checks that a query is a single SELECT before it runs, as a second check after the existing one.
- Extensions are no longer installed or loaded on demand by a query, and persistent secrets are off.
- Queries using `json_execute_serialized_sql`, `json_serialize_sql`, `parquet_kv_metadata` or another `parquet_*` function, or `load_aws_credentials` are refused.
- What you will notice: nothing visible; searches and pages work as before.
- What changes for existing installs: nothing to do. A saved search or Ask query that used one of the functions above now fails with "Function not allowed"; query speed is unchanged.
