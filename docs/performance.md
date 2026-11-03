# Performance

Measured with `scripts/bench.py` (synthetic syslog through the real ingest path with the Automatic parser, then searches through the real query API), on a 2 vCPU Intel Xeon 2.1 GHz cloud VM with 8 GB RAM:

| Measure | Result |
|---|---|
| Ingest | about 9,600 events/s for one source (854,316 events in 89 s) |
| Storage | 117.7 MB of raw syslog became a 54.1 MB lake (2.2x smaller), raw lines kept |
| Count, group by host, failed logins by IP | 40 to 45 ms |
| Text search in `message` (`ILIKE`) | 270 ms |
| Latest 100 events, all columns | 340 ms |

On a 4 vCPU Proxmox container (AMD Ryzen 9 5950X host, 8 GB RAM), the same run gave about 14,700 events/s; 16 to 19 ms for count, group by host, and failed logins by IP; 96 ms for the text search; and 110 ms for the latest 100 events.

Run it on your own hardware with `cd backend && uv run python ../scripts/bench.py --events 1000000`. A Loki source reads at most 20,000 lines per 30 s poll (about 650 lines/s), well inside the ingest rate.

Investigation pages read many events at once. On a 14 million event lake over 7 days (synthetic network, sign-in, and AI telemetry across 800 people, written straight to Parquet), on a 2 vCPU cloud container:

| Page | Time |
|---|---|
| AI usage | 4.9 s |
| Investigations, AI flow, everyone | 4.4 s |
| Investigations, AI flow, one person | 4.8 s |
| Investigations, one user's lanes | 3.0 s |
| Settings, Identities (suggestions) | 6.4 s |

Each stays under the 20 s query limit; shorter time ranges are proportionally faster.

These page times predate the November 2026 performance work (rollups for closed days, shared caching, reused query instances), which cut most investigation and dashboard pages to 2 seconds or less on a 4 vCPU test install. This table is updated when the synthetic benchmark is re-run.

## Local model

The AI features were tested with Ollama 0.34.1 running `qwen3.5:9b` with Thinking off, on an NVIDIA RTX 3080 (10 GB) passed through to a Proxmox container, on an AMD Ryzen 9 5950X host with 32 GB RAM. Explain and parser drafting use the same model setting and have not been timed. On the Ask suite (100 questions and 10 follow-up conversations, `backend/evals/nl_queries`):

| Prompt | Executable | Exact | Median per question |
|---|---|---|---|
| `ask.v4` (the default), two runs | 99% | 87 to 88% | 2.0 s (p90 3.3 to 3.6 s) |
| `ask.v6` | Not yet measured on this model | | |

Ingest, search, Sigma rules, schedules, and every page's numbers run on the CPU and do not use or need a GPU. Only Ask, Explain, and parser drafting call a model, and a smaller or CPU-only model makes those slower, not the rest. For a CPU-only server with the model on the same machine, see [install/ask-on-cpu.md](install/ask-on-cpu.md). Details, every run, and how to run the suite against your own model: [backend/evals/nl_queries/README.md](backend/evals/nl_queries/README.md).

