# Ask on a CPU-only server

A common first setup is one 4 vCPU, 8 GB machine with no GPU running both the app (the [systemd install](team-vm.md#b-systemd-service)) and a small local model for Ask. This page covers that case: installing Ollama next to the app, which model to pick, how to split the memory, and what speed to expect.

Everything except Ask, Explain, and parser drafting runs without a model. A slow model makes those three slower and nothing else.

## 1. Install Ollama on the same machine

```bash
curl -fsSL https://ollama.com/install.sh | sh     # installs ollama.service, listening on 127.0.0.1:11434
sudo systemctl edit ollama
```

In the override that opens, add:

```ini
[Service]
# Ask's prompt (schema, examples, and previews) needs more than Ollama's default context.
Environment=OLLAMA_CONTEXT_LENGTH=16384
# One question at a time and one model in memory: on 8 GB there is room for no more.
Environment=OLLAMA_NUM_PARALLEL=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
# Keep the model loaded between questions; loading it from disk takes seconds on every miss.
Environment=OLLAMA_KEEP_ALIVE=24h
# Ollama's own memory limit, so a model can never push the app out (see the table below).
MemoryMax=4500M
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
ollama pull qwen3.5:4b
```

Ollama listens on loopback only, which is what you want here: the app reaches it on the same machine and nothing else can.

Then in the app, **Settings > AI providers > Add provider**: OpenAI-compatible, URL `http://127.0.0.1:11434/v1`, model `qwen3.5:4b`, **Thinking** set to **Off**, then **Test** (it shows the **Local** badge) and **Enable**.

## 2. Pick the model and split the memory

**Prefer adding RAM over lowering the app budget.** A lower budget makes every page section and search smaller for everyone, all the time; more RAM costs nothing at query time. With 12 or 16 GB, keep the app at the split below and give the model its own room:

| Machine | App (`APP__SERVER__MEMORY_LIMIT_MB`, unit limits) | App query memory | Model and Ollama limit | Left for the system |
|---|---|---|---|---|
| 12 GB | `4096`; `MemoryHigh=4500M`, `MemoryMax=5G` | 819 MB per page section, up to 1639 MB per search | `qwen3.5:4b`, `MemoryMax=4500M` | about 2.5 GB |
| 16 GB | `4096`; `MemoryHigh=4500M`, `MemoryMax=5G` | 819 MB per page section, up to 1639 MB per search | `qwen3.5:4b` with room to spare, or `qwen3.5:9b` (6.6 GB) with `MemoryMax=8G` | about 3 GB with 9B |

Set the budget explicitly even with more RAM: the automatic budget is 75% of the machine (9216 MB on 12 GB), which leaves the model too little. If adding RAM is not possible, use one of the 8 GB splits below.


The app sizes query memory from its memory budget (D58, D80). On startup it prints the budget and the split, for example:

```
Memory budget: 4096 MB (...)
Query memory: 819 MB per page section, up to 1639 MB for a search or export; ...
```

The model needs its own share of the same 8 GB, so the app's budget has to come down from the automatic 75% of the machine. Two splits fit:

| | A. Better answers (recommended) | B. More query memory |
|---|---|---|
| Model | `qwen3.5:4b` (3.3 GB download) | `qwen3.5:2b` (1.9 GB as `2b-q4_K_M`) |
| Ollama while loaded | about 4 GB (`MemoryMax=4500M`) | about 2.5 GB (`MemoryMax=3G`) |
| App budget (`APP__SERVER__MEMORY_LIMIT_MB`) | `3072` | `4096` |
| App query memory (startup line) | 614 MB per page section, up to 1230 MB per search | 819 MB per page section, up to 1639 MB per search |
| App unit (`remnant.service`) | `MemoryHigh=3500M`, `MemoryMax=4G` | `MemoryHigh=4500M`, `MemoryMax=5G` |
| Left for the system | about 0.5 GB | about 0.5 GB |

Why `qwen3.5:4b` for A: it is the largest Qwen 3.5 size that fits next to the app on 8 GB, from the same family as the 9B model Ask was tuned and measured on, so the prompts and the Thinking setting carry over. Larger models write better SQL, and the 9B model's results are the best guide available until the 4B is measured. The 9B model the [Ask results](../performance.md#local-model) were measured with (6.6 GB) does not fit next to the app on 8 GB. Neither 4B nor 2B has been through the Ask suite yet; see [Measure it](#4-measure-it) to run it on your own machine before you rely on either.

Choose B if your searches over long time ranges are slow or fail for memory, and Ask is used rarely. A query that needs more than its share still finishes: it spills to `data/tmp/duckdb` and runs slower.

To apply a split, set the budget in `/etc/remnant/remnant.env` and the limits in the unit, then restart both:

```bash
sudo sed -i 's/^# APP__SERVER__MEMORY_LIMIT_MB=.*/APP__SERVER__MEMORY_LIMIT_MB=3072/' /etc/remnant/remnant.env
sudo systemctl edit remnant      # [Service] MemoryHigh=3500M and MemoryMax=4G
sudo systemctl restart remnant ollama
journalctl -u remnant -b | grep -E "Memory budget|Query memory"
```

## 3. What speed to expect

These are estimates for 4 modern vCPUs, not measurements. Replace them with your own numbers from step 4.

| Step | Estimate with `qwen3.5:4b` |
|---|---|
| First question after the model loads | 1 to 2 minutes: Ollama reads the whole prompt (about 4,000 tokens of schema and examples) once |
| Later questions, Ask writes the query | 20 to 40 seconds: the shared start of the prompt is reused, so most of the time is writing the SQL and explanation |
| Later questions that match a library query | 5 to 15 seconds: one short routing call (about 500 tokens), then the library query runs on the CPU like any search |
| Rows after the query is written | The same as a search in Query mode |

`qwen3.5:2b` should be roughly twice as fast, with less accurate queries.

Practical settings for a CPU box:

- Keep **Thinking** off. On a CPU, thinking tokens can add minutes.
- Leave `ask.auto_run` on (the default; `APP__ASK__AUTO_RUN`): rows appear as soon as the query is written, without a second wait for a click.
- When the Ask summary setting ships (`ask.summarize`, ADR-0042 slice 1c), turn it off here: Ask then shows the headline and the rows and skips the extra model call that writes the answer, which on a CPU is the slowest part. Until then, each question that is not a library match makes one call that writes both the query and its explanation.
- Saved searches and the query library answer common questions without a model call beyond routing, so adding your team's frequent questions there is the biggest speed-up on a CPU.

## 4. Measure it

Run the Ask suite against the model on this machine (it uses fixture data, not your logs):

```bash
cd /opt/remnant/backend
sudo -u remnant .venv/bin/python -m evals.nl_queries.run \
  --base-url http://127.0.0.1:11434/v1 --model qwen3.5:4b --out qwen35-4b-cpu.json
```

The report gives executable and exact rates, time to first rows, and routing mistakes in both directions. Run it once with the app idle and note the numbers; the [benchmark plan](../../backend/evals/nl_queries/README.md) lists the CPU-only run this page's estimates should be replaced with.
