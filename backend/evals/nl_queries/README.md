# Ask accuracy suite

100 plain-English questions over a synthetic lake, each with a reference SQL query. It measures how often a model's Ask answer runs (executable) and returns the same result as the reference (exact). Targets for v0.1 (SPEC 5.7): 90% executable and 75% exact on the reference local model.

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

## Scoring

A generated result counts as exact when some of its columns, one for each reference column, hold the same values. Extra columns, a different column order, and aliases are fine. Rows are compared as a multiset, except for `compare: ordered` questions (top N, first event), where order counts. Whole-number floats equal ints, and a UTC-midnight timestamp equals its date.

## Results

Record each run in the PR that changes Ask, and in the table below.

| Model | Provider | Thinking | Executable | Exact | Median s | Date |
|---|---|---|---|---|---|---|
| qwen3.5:9b, `ask.v4` + answer-shape retry (#125), run 2 | Ollama 0.34.1, homelab VM (local), context 16384 | Off (`none`) | 99% | 87% | 2.04 (p90 3.27) | 2026-10-11 |
| qwen3.5:9b, `ask.v4` + answer-shape retry (#125), run 1 | Ollama 0.34.1, homelab VM (local), context 16384 | Off (`none`) | 99% | 88% | 2.04 (p90 3.57) | 2026-10-11 |
| qwen3.5:9b, `ask.v4` | Ollama 0.34.1, homelab VM (local), context 16384 | Off (`none`) | 95% | 85% | 1.98 | 2026-10-11 |
| qwen3.5:9b, `ask.v3` | Ollama 0.34.1, homelab VM (local), context 16384 | Off (`none`) | 100% | 83% | 2.56 (p90 3.73) | 2026-10-11 |
| qwen3.5:9b, `ask.v2` | Ollama 0.34.1, homelab VM (local), default context | Off (`none`) | 96% | 66% | 2.56 (p90 4.21) | 2026-10-11 |
