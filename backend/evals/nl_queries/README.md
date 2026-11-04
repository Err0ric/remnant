# Ask accuracy suite

100 plain-English questions, plus 10 follow-up conversations (`f001` to `f010`), over a synthetic lake, each with a reference SQL query. It measures how often a model's Ask answer runs (executable) and returns the same result as the reference (exact). Targets for v0.1 (SPEC 5.7): 90% executable and 75% exact on the reference local model.

## Data

`fixture.py` builds about 2,100 events across four sources with fixed seeds:

| Source | Shaped like | OCSF classes |
|---|---|---|
| `linux_auth` | OpenSSH 9 and sudo 1.9 through rsyslog, plus 15 headerless kernel lines | 3002 Authentication, 3003 Authorize Session |
| `fw_edge` | A generic key=value edge firewall, one port scanner | 4001 Network Activity |
| `dns` | A resolver query log with response codes in `unmapped` | 4003 DNS Activity |
| `edr` | Process-start telemetry from five workstations | 1007 Process Activity |

All values are synthetic. Public addresses come only from RFC 5737 ranges, internal ones from `10.0.0.0/8`, and every host, user and domain name is invented (`example.*` domains). OCSF columns are filled in directly, so the suite tests the model's SQL, not the parsers.

## Run it

```
cd backend
uv run python -m evals.nl_queries.run --base-url http://127.0.0.1:11434/v1 --model llama3.1:8b --out report.json
# reasoning models (qwen3.5, deepseek-r1): --thinking none, the same as Thinking Off in AI providers
uv run python -m evals.nl_queries.run --base-url http://127.0.0.1:11434/v1 --model qwen3.5:9b --thinking none --out qwen35-9b.json
# cloud: the key comes from an environment variable, never the command line
OPENAI_API_KEY=... uv run python -m evals.nl_queries.run --base-url https://api.openai.com/v1 \
    --model gpt-4o-mini --api-key-env OPENAI_API_KEY
```

The run is in-process and uses a temporary data folder. It goes through the real gate (classification and the `llm_calls` audit) and the real Ask agent with its self-check. The sources are marked cloud allowed because the data is synthetic.

## Follow-ups and prompt versions

Follow-up cases carry `history`: the earlier questions and their reference SQL, sent as the
conversation so far, the way the Search bar's Refine sends it. They cover "show me all of these
for alice", "break that down by host", "count them", "what about successful ones", and person
names logged in other forms (`Steve` as `steve.jones@example.com`, `Steve.Jones@example.com`,
`CORP\steve.jones` in the `idp_signin` source).

Compare prompt versions on the same model:

```
uv run python -m evals.nl_queries.run --base-url http://127.0.0.1:11434/v1 --model qwen3.5:9b \
    --thinking none --prompt ask.v4 --out v4.json
uv run python -m evals.nl_queries.run --base-url http://127.0.0.1:11434/v1 --model qwen3.5:9b \
    --thinking none --prompt ask.v5 --out v5.json
# follow-ups only, to iterate quickly
uv run python -m evals.nl_queries.run ... --prompt ask.v5 --ids f001,f002,f003,f004,f005,f006,f007,f008,f009,f010
```

`ask.v6` (2026-10-22) is `ask.v5` with one rule changed: match text on `raw` or a parsed column,
never on `message`, whose meaning depends on the parser (D84; `message` stays right for DNS
events, where it is the queried name). Not yet run on the homelab model; compare with:

```
uv run python -m evals.nl_queries.run --base-url http://<ollama-host>:11434/v1 --model qwen3.5:9b \
    --thinking none --prompt ask.v5 --out v5.json
uv run python -m evals.nl_queries.run --base-url http://<ollama-host>:11434/v1 --model qwen3.5:9b \
    --thinking none --prompt ask.v6 --out v6.json
```

The server uses `llm.ask_prompt` (compose `ASK_PROMPT`, default `ask.v4`). Switch only when the
newer version scores at least as well overall on your model.

## Scoring

A generated result counts as exact when some of its columns, one for each reference column, hold the same values. Extra columns, a different column order, and aliases are fine. Rows are compared as a multiset, except for `compare: ordered` questions (top N, first event), where order counts. Whole-number floats equal ints, and a UTC-midnight timestamp equals its date.

## Routing (ADR-0042 slice 1b)

By default the runner asks each question the way Ask does now: routed first (one short model call), the library query run when one fits, the SQL agent otherwise; follow-ups go to the agent. It also runs the 20 general know-how questions in `knowhow.yaml`, which must be routed as know-how. The summary adds:

| Field | Meaning |
|---|---|
| `exact_rate`, `executable_rate` | Data questions only: right rows, as before |
| `data_sent_to_knowhow` | Data questions routed as general guidance (a misroute: the person gets no answer from their logs) |
| `knowhow_sent_to_data` | Know-how questions routed as data questions (a misroute: SQL for a question that is not about the logs) |
| `library_rate` | Share of data questions answered by a library query instead of generated SQL |
| `median_first_rows_seconds`, `p90_first_rows_seconds` | From the question to rows on screen with auto-run |

The fixture's sources are mostly synthetic templates that no library pack requires, so `library_rate` on this suite is low by design; it measures that routing does not hurt the agent path. `--no-routing` runs the agent alone, as before slice 1b, for comparison.

## Routing synonyms

`synonyms.yaml` holds one question per form of a term people use for the same thing (logins, log-ins, sign-ins, signins, authentications; Microsoft, M365, Office 365, O365, Entra, Azure AD; firewall, Palo Alto, PAN, PAN-OS; VPN, GlobalProtect; Claude Code, Claude, coding agent, AI agent, agents, Cowork; accessing, touching, opening), each naming the library query it should reach (D191). The test suite checks that the ranker puts that query first for every question, with no model (`tests/unit/test_ask_synonyms.py`). With a model, `--synonyms` checks the whole route:

```
uv run python -m evals.nl_queries.run --base-url http://127.0.0.1:11434/v1 --model qwen3.5:9b --synonyms
```

It prints `ok` or `MISS` per question and exits 1 when any question missed its query.

## Two models side by side (one command)

```
cd backend
uv run python -m evals.nl_queries.side_by_side --base-url http://<ollama-host>:11434
```

Defaults: `--models qwen3.5:4b,qwen3.5:9b`, `--thinking none` (Thinking Off, as Ask is set up), and Ask's answer step measured (slice 1c). It checks first that the server lists every model and stops with the `ollama pull` lines when one is missing. Each model runs the whole suite in turn (data questions, follow-ups, and the know-how set), then one Markdown table prints, a column per model:

| Row | Meaning |
|---|---|
| Rows run, Right rows (accuracy) | `executable_rate`, `exact_rate` on the data questions |
| Data questions sent to guidance, Guidance questions sent to data | Misroutes both ways |
| Answered from the library | `library_rate` |
| First rows, median / p90 | What a person waits with `ask.summarize: false` |
| Full answer, median / p90 | With summaries on: first rows plus the answer step |
| Summaries shown; No summary: nothing cited; No summary: rows had no event ids | What the citation rule did with each result |
| Statements kept / removed | Statements that cited sent rows, and those removed |

Full JSON reports go to `--out-dir` (default `./ask-eval`), one per model. `--no-answer` skips the answer step, `--ids` runs a few questions for a quick check, and `--models` takes any list. A full run of two models is about 270 questions; on a CPU-only box expect hours, not minutes.

### Benchmark plan (owner, 2026-11-03)

The formal run is on the GPU hardware once it arrives, against the model that runs there: one `side_by_side` run gives accuracy, misroutes, and time to first rows and to the full answer (`ask.summarize` on and off). The CPU-only run on a shared 4 vCPU box and the 4B against 9B comparison as a work decision are dropped: the work install already uses a local model on a separate machine.

## Results

Record each run in the PR that changes Ask, and in the table below. Every homelab run below used Ollama in a Proxmox container with an NVIDIA RTX 3080 (10 GB) passed through, on an AMD Ryzen 9 5950X host with 32 GB RAM. Latency depends mostly on the GPU; results (executable, exact) depend on the model and prompt, not the hardware. Rows dated before 2026-10-15 were measured on the 100 single questions, before the follow-ups and the `idp_signin` source were added; rerun `ask.v4` on the current suite to compare with `ask.v5`.

| Model | Provider | Thinking | Executable | Exact | Median s | Date |
|---|---|---|---|---|---|---|
| qwen3.5:9b, `ask.v4` + answer-shape retry (#125), run 2 | Ollama 0.34.1, homelab RTX 3080 10 GB (local), context 16384 | Off (`none`) | 99% | 87% | 2.04 (p90 3.27) | 2026-10-11 |
| qwen3.5:9b, `ask.v4` + answer-shape retry (#125), run 1 | Ollama 0.34.1, homelab RTX 3080 10 GB (local), context 16384 | Off (`none`) | 99% | 88% | 2.04 (p90 3.57) | 2026-10-11 |
| qwen3.5:9b, `ask.v4` | Ollama 0.34.1, homelab RTX 3080 10 GB (local), context 16384 | Off (`none`) | 95% | 85% | 1.98 | 2026-10-11 |
| qwen3.5:9b, `ask.v3` | Ollama 0.34.1, homelab RTX 3080 10 GB (local), context 16384 | Off (`none`) | 100% | 83% | 2.56 (p90 3.73) | 2026-10-11 |
| qwen3.5:9b, `ask.v2` | Ollama 0.34.1, homelab RTX 3080 10 GB (local), default context | Off (`none`) | 96% | 66% | 2.56 (p90 4.21) | 2026-10-11 |
