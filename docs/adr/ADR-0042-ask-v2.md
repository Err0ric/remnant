# ADR-0042: Ask v2: type any question, get an answer (local models first)

Status: **Accepted with conditions** 2026-11-02 (project owner). Choices C1 to C4 as proposed; the ADR-0033 narrowing (reviewed `ask` phrasings only) accepted; owner conditions 1 to 5 below. Recorded as SPEC D167. Amends CLAUDE.md rule 4 (Ask queries only) and SPEC 5.3, 5.6, 5.7, and 7.3.

## Context

Ask today (SPEC 5.3, ADR-0008) turns a question into SQL that the person reads and runs. On a real install that is two steps too many for most questions: people want the answer ("12 failed firewall logins today, 9 from one address"), not a query to check. It also leans on the model for everything: a small local model writes the whole query from the schema, which is where it fails most (SPEC 5.7 eval: about 87% exact on a 9B model, lower on 3-4B).

Since Ask shipped, three things make a better path possible without a bigger model:

- The query library (ADR-0033): tested, fixture-checked SQL for the common questions, with parameters.
- Identity resolution (ADR-0029, the identity map): a name, address, or host in a question can be resolved without a model.
- The citation check (Slice 4) and the Explain flow: a pattern for model text that must cite events it was sent.

## Decision (proposed)

### Flow

```
question
  1 Understand   classify (data | know-how), pull out entities and time range
  2 Find query   library match + parameters  (fallback: free SQL, existing self-check loop)
  3 Run          guard, read-only engine, caller's sources, row and time caps   (auto-run)
  4 Answer       headline from the result (deterministic) + short summary citing event ids
```

Steps 1 and 2 try deterministic code first and ask the model only for what code could not settle. Results show as soon as step 3 finishes; step 4 streams after.

### Decisions

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | Auto-run (owner decision) | Ask runs its query without a click when it passes the guard (rule 7: read-only connection, `sqlglot` allowlist, no external access), on the caller's `events` view (rule 13), with Ask's caps: 1,000 rows shown, 30 s timeout, and the page's time range unless the question names another (at most 90 days). Each run writes the same audit row as any query (rule 14) with purpose `ask` and the library id or `generated` (condition 2). The SQL is shown collapsed under "How I got this". Setting `ask.auto_run` (default `true`); `false` restores click-to-run. The CLI keeps `Run? [y/N]` unless `--yes` | Running a guarded read-only query has no side effect beyond cost; the guard and the view are what make it safe, not the click | Click-to-run (today) |
| 2 | What stays approve-first | Everything else in rule 4: parser drafts, saved-search creation, schedules, alert changes, any write. Suggested checks (row 9) run on click. Free text from the model is never parsed for commands | Owner: auto-run is for Ask queries only | |
| 3 | CLAUDE.md rule 4 | Reworded: "Nothing the LLM returns is executed automatically, except an Ask query that passes the guard and runs read-only on the caller's view (ADR-0042, setting `ask.auto_run`). SQL is displayed; parser drafts stay in `drafts/` until approved; free text is never parsed for commands." SPEC 5.3 item 3 changes to match (the old `ask.auto_run` meaning, cloud-allowed sources only, is replaced) | Rule and spec agree in the same PR | |
| 4 | Routing (step 1) | Deterministic first: addresses, emails, host names known to the lake, people in the identity map, and time phrases ("today", "this week", "since Monday", "last 24 hours") are parsed in code. The model gets one short, zero-tool call (`ask_route.v1`) returning `{kind: data or knowhow, intent, entities, time}` only for what code did not settle. Under 400 prompt tokens before the question | Small models classify well and write SQL badly; a short prompt keeps CPU latency down | One big prompt that does everything |
| 5 | Library first (step 2) | Candidates: library queries whose `requires` match the viewer's templates (ADR-0033 row 3), ranked by a keyword and synonym score in code (the semantic layer's vocabulary), top 8 sent to the model with id, name, `why`, and parameter names. The model returns `{query_id, params}` or `none`. Parameters are then validated in code (an address must parse, a person must resolve, a time must be a time) | A tested query beats generated SQL; validation catches a wrong fill before it runs | Embeddings (a second model to ship and run) |
| 6 | Library additions | Each library query may add `answer` (a headline template from result columns, "{n} failed logins") and `ask` (2 to 5 example phrasings for ranking and the eval). `why` stays display-only for people; `ask` phrasings are the only library text sent to a model, and they are reviewed in the pack PR like the SQL | ADR-0033 row 6 says library text is never sent to a model; this narrows that to reviewed example phrasings, which are not data | Sending `why` too |
| 7 | Fallback | No library match: the existing Ask agent (two tools, `get_schema` and `preview_query`, self-check loop with up to two refinements). Its SQL auto-runs under row 1 and is labeled "Generated query (not from the library)" | The fallback is today's tested path | Refusing questions the library cannot answer |
| 8 | Data answers (step 4) | The headline is written by code from the result (`answer` template, or "N rows" with the first columns) and is never model text. The model (`ask_answer.v1`, zero tools) gets the question and up to 20 result rows under `data` (values capped at 300 characters, `event_id` kept where the query returns it) and returns `{claims: [{text, event_ids}]}`, at most 5. Every claim must cite at least one event id that was in the rows sent; a claim that does not is **removed** and the answer says "1 statement removed: it cited no events". For aggregate queries without event ids, code runs an evidence query (up to 10 matching events per top group, through the guard) and those ids are what the model may cite | Owner: "the model never mixes uncited claims into a data answer". Removing, not labeling, is the stricter reading | Labeling uncited claims "unverified" as Explain does |
| 9 | Know-how answers (owner decision) | Model knowledge (`ask_knowhow.v1`, zero tools, no log data sent at all): plain text or up to 7 short bullets, under a fixed label **General guidance, not from your logs**, no citations. Then 1 to 3 suggested checks, each a library query id with parameters (validated as in row 5) or, with no fit, nothing. Checks run on click, not automatically. This is the one labeled exception to "every AI claim cites event ids"; recorded in SPEC section 1 and 7.3 | The question is not about the data; sending no data also means nothing can leak and nothing in the logs can steer the answer | Refusing know-how questions |
| 10 | Mixed questions | A question that is both ("why is the VPN slow, and did anyone fail to log in?") is split by the router into a data part and a know-how part, shown as two blocks, each with its own rules. The data block never contains know-how text | Keeps row 8 true | One combined answer |
| 11 | Multi-step (slice 3) | For "anything weird with dana@example.com this week?": the router picks up to `ask.max_steps` library queries (default 4) for that entity and window; code runs them in turn; the answer step gets each result (20 rows each, labeled by query) and writes claims that cite events. Each query and its result is listed under "How I got this" | Bounded, inspectable; each step is a tested query | An open agent loop |
| 12 | Follow-ups (slice 4) | A follow-up refines the previous turn: the router sees the previous turn's query id, parameters, and time (not its rows) and returns changed parameters or a different query; free-SQL turns use today's refinement path. Up to 3 earlier turns, as today | Small context, deterministic diffs ("only failures" becomes a parameter change) | Sending earlier results |
| 13 | Tools | No new tools. Ask keeps exactly `get_schema` and `preview_query`, used only in the fallback (row 7). Route, answer, and know-how are new zero-tool purposes. Rule 3 is unchanged in substance; its list of zero-tool purposes gains `ask_route`, `ask_answer`, `ask_knowhow` | Owner: tool changes need a spec change; this design needs none | A `run_library_query` tool (the model would choose when to run) |
| 14 | Gate and classification | Every call goes through `llm/gate.py` with the sources it carries declared: route and know-how declare none (no log data; the question itself is user text); answer declares the sources of the rows it sends, so a cloud provider is blocked when any is `local_only` (6.2) and redaction applies as today. Every call is an `llm_calls` row with its purpose | Same rules as Explain | |
| 15 | Local models first (owner decision) | Fresh installs only enable local providers (unchanged). Prompts are written and measured for 3-4B and 7-9B quantized models on CPU: route under 400 prompt tokens, answer under 2,500. Output lengths capped (route 120 tokens, answer 400). Cloud and frontier models stay opt-in per install | The common install has no GPU | |
| 16 | UI (owner decision, DESIGN.md) | An Ask panel on the Search page and as a slide-over from anywhere (Ctrl+K "Ask"; "Séance" stays a palette alias only, rule 12). A large question box at the top. Each turn is a block, not a bubble: the question as a heading; the answer as text or short bullets; the results table; a collapsed **How I got this** (query, library id or "generated", sources read, rows, time taken, model and provider badge). Follow-ups stack below. People, addresses, hosts, and services in answers are entity links (the existing `EntityLink`). Progress: Understanding, Finding the right query, Running, Writing the answer; the table appears before the summary | Owner brief | |
| 17 | Measure | The eval (SPEC 5.7) gains "answered correctly": right rows (as today) and a right headline (the answer template's numbers match the reference). A know-how set (about 30 questions) is checked for the label, no citations, no event ids, and no log facts (no address, person, or count that is not in the question). The owner's 10 to 20 real questions become a second set **only after rewriting with synthetic names and addresses**; the real wording stays out of both repositories | Measured, not assumed; synthetic data only | |
| 18 | Benchmark | `scripts/bench_ask.py` on a 4 vCPU CPU-only box with 2 or 3 small local models (one 3-4B, one or two 7-9B, quantized, for example from the Qwen and Llama families) and on one modest GPU: median and p90 time to first rows and to the full answer, and accuracy on both sets. Results and a model and hardware recommendation go in `backend/evals/nl_queries/README.md` and the install guide | Owner brief | |

### Owner choices (2026-11-02)

| # | Question | Decided |
|---|---|---|
| C1 | Uncited claims in a data answer (row 8) | Remove them and say so |
| C2 | Auto-run row cap (row 1) | 1,000 rows shown (the guard's 10,000 cap still applies to export) |
| C3 | Who may use auto-run | Admins and analysts (auditors have no Ask) |
| C4 | No provider configured | Ask says it needs a model and still offers library checks found by keyword |

### Owner conditions (2026-11-02)

| # | Condition | Where |
|---|---|---|
| 1 | Slice 1 is split: **1a** auto-run plus the new Ask panel and slide-over on today's Ask agent; **1b** deterministic routing, library match, and parameters; **1c** the answer step (code headline, cited claims, evidence query). Each ships separately and is measured | Thin slices below |
| 2 | Auto-run queries write audit rows like any query (rule 14), with purpose `ask` and the library id or `generated` | 1a |
| 3 | The turn shows how the question was routed (data or general guidance) with a one-click switch to the other path ("Treated as general guidance. Check your data instead?"). Misroutes are in the eval | 1b, 2 |
| 4 | Setting `ask.summarize` (default on): off shows only the code headline and the results table, with no answer-step model call. Both modes benchmarked on the 4 vCPU CPU-only box | 1c, row 18 |
| 5 | When the active provider is cloud, the panel shows "Your question is sent to <provider>" under the question box: route and know-how calls declare no sources, so values pasted into a question are not blocked by classification | 1a |

## Thin slices

| Slice | Scope | Done when |
|---|---|---|
| 1a | Auto-run on today's Ask agent (guarded, caller's view, caps, audit rows with purpose `ask` and `generated`); the new Ask panel on Search and the slide-over (Ctrl+K "Ask"): question box, turn blocks, results table, collapsed "How I got this", progress steps, cloud notice (condition 5); `ask.auto_run` off restores click-to-run | Panel tests (auto-run, no run when off, SQL collapsed, cloud notice, auditor has no Ask); eval re-run per model with time to first rows |
| 1b | Deterministic routing, library match, code-validated parameters, route shown with a one-click switch (condition 3); free SQL as the fallback | Eval: library hit rate, "answered correctly" on rows, misroutes |
| 1c | Answer step: code headline, cited claims (uncited removed, C1), evidence query; `ask.summarize` (condition 4) | Eval "answered correctly" on headline; benchmark with summarize on and off |
| 2 | Know-how answers with label and suggested checks | Know-how set passes the label and no-log-facts checks |
| 3 | Multi-step (up to N library queries) | Multi-step questions in the eval |
| 4 | Follow-ups that refine the previous turn | 10 follow-up conversations re-scored |

## As built

- Slice 1b (2026-11-02): routing calls are recorded in `llm_calls` under purpose `ask` with prompt `ask_route.v1`, not a new purpose: the purpose column is a closed set on an append-only table, and adding a value means rebuilding it. The prompt reference tells routing apart from SQL writing. People, addresses, and machines named in a question filter the library query's output columns (`user`, `address`, `host`, ...) as bound parameters; an email also matches its bare login and the identity map's aliases, and How I got this lists every name matched. A library query that cannot filter on a named entity is not used and the agent writes the SQL instead. Follow-ups still go to the agent (slice 4). A general-guidance route returns no query; until slice 2 the panel offers "Check your data instead".
- Slice 1c (2026-11-02): the headline is code (`app/search/ask_summary.py`); the answer call (`app/llm/ask_summary.py`, prompt `ask_answer.v1`) is audited under purpose `ask`, as routing is. Rows for it are kept server-side from the run, never sent back by the client. Statements are removed when they cite no sent row, or any id that was not sent. Output cap 600 tokens (row 15 said 400). **Proposed, pending review:** the evidence query for aggregates (row 8) is not built; a result without `event_id` gets the headline and rows only (D171).
- Benchmark (owner, 2026-11-03): the CPU-only run on a shared 4 vCPU box (condition 4, row 18) is dropped; the work install already runs its model on a separate machine. `ask.summarize` on and off is measured in the formal run on the GPU hardware once it arrives, against the model that runs there (`evals.nl_queries.side_by_side`).

## Consequences

- Most answers come from tested library SQL, so accuracy rises with the library, not only with the model. Library packs gain `answer` and `ask` fields and need phrasings in review.
- Auto-run moves cost, not risk: a heavy generated query now runs without a look. The guard's timeout, the row cap, and the time cap bound it; queries run on the existing queue (ADR-0028), one Ask run per user at a time.
- The know-how exception is visible and bounded: a fixed label, no log data sent, no citations, and checks that run only on click.
- Three new prompt files and purposes in `llm_calls`; `ask.v6` stays for the fallback.

## ATLAS / ATT&CK

| Threat | ATLAS | Control |
|---|---|---|
| Instructions in log values steer the answer (rows sent in step 4) or the query (preview rows in the fallback) | AML.T0051.001 | Rows under `data` with the system prompt saying `data` may hold instructions to ignore (rule 5.2); the answer has zero tools; claims must cite sent ids; the headline is code, not model text |
| Instructions in log values steer an auto-run query into something expensive | AML.T0029 (denial of service) | Only the fallback sees rows before writing SQL (5 preview rows); guard, timeout, row and time caps; the model queue limits one run per user |
| Result rows sent to a cloud model | AML.T0057 | Gate classification over the rows' sources; `local_only` blocks cloud; redaction as configured |
| A confident but false know-how answer read as fact about the install | T4 (SPEC 7.1) | Fixed label "General guidance, not from your logs"; no data sent; suggested checks are tested library queries run on click |
| A wrong library parameter (a different person or address) | T4 | Parameters validated and resolved in code; the resolved values are shown in "How I got this" |

ATT&CK: unchanged; Ask answers questions over the same detections and library queries.
