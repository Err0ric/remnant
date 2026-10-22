# ADR-0028: One queue per model provider, and "busy" is not "down"

Status: **Accepted** 2026-10-21 (project owner: as proposed; the wait configurable per provider; per-user one-at-a-time limits kept; the health check takes no slot; wait time and busy retries recorded in the `llm_calls` row). Recorded as SPEC D78; threat T60 added.

## Context

An infrastructure admin planning the local model host for a first real install asked for small Ollama servers to run one inference at a time (`OLLAMA_NUM_PARALLEL=1`, little or no queue). On modest hardware two requests in parallel each take several times longer than the same two in a row. A server set up this way answers "busy" while it works on another request: HTTP 503 or 429, Ollama's "server busy", or a refused connection.

Several things here can overlap: two analysts in Ask or Explain, the Ask self-check loop (up to two refinements), a parser draft, Investigations in AI mode, and the provider health check.

How it works today (`llm/provider_http.py`, `llm/gate.py`):

| Answer | Today |
|---|---|
| Any status other than 200 (503, 429, 500) | `ProviderError("Provider returned HTTP 503")`; the gate records `error = provider_error` |
| Connection refused, timeout | `ProviderError("Cannot reach provider: ConnectError")`; `provider_error` |
| Health check (`models()`) failing | The provider shows as not working on AI providers and Health |
| Concurrency | None in the gate. Ask allows one question per user at a time (`api/ask.py`); Explain and parser drafts have no limit |

So a healthy but occupied server reads as broken, and nothing stops the app from sending it two requests at once.

## Decision

| # | Question | Decision | Why | Alternative |
|---|---|---|---|---|
| 1 | Where the limit lives | In the gate (`llm/gate.py`), one queue per provider, around `provider.chat()` only. Every purpose (Ask, Explain, parser draft, investigation summaries) goes through it; nothing can call a provider around it (rule 2 already makes the gate the only path) | One place to enforce and audit | A limit per feature (each would need its own, and they would not see each other) |
| 2 | Setting | `max_concurrent` per provider, 1 to 16. Default **1 for local** providers, **none** (no queue) for cloud. Shown on AI providers with: "1 for a single local GPU or CPU host" | Matches how small local servers are run; cloud APIs handle concurrency themselves | Global setting (wrong when a cloud and a local provider are both configured) |
| 3 | Waiting | First come, first served. A request waits for a free slot up to `wait_budget_s` (default 120, 10 to 600, per provider) | Fair; a budget means a stuck server cannot hold callers forever | Unbounded wait; reject at once when busy |
| 4 | "Busy" answers | HTTP 503 and 429, a body saying the server is busy, and a refused connection on a provider whose last health check passed are retried with exponential backoff and jitter (1 s, 2 s, 4 s, capped at 15 s), honoring `Retry-After`, inside the same budget. Other errors are not retried | These mean "try again", not "broken"; one budget covers queueing and retries so the caller's wait is bounded once | Retrying everything (would repeat real failures) |
| 4a | Re-check before each retry (owner review, 2026-10-21) | Immediately before every re-send: the provider still exists, is enabled, has the same kind and address, and resolves to the same locality; for cloud, the classification check runs again on the same scope and sources. A refusal finishes the same row (`classification_blocked`, `provider_disabled`, `provider_changed`, or `locality_changed`, with the retry count) and nothing is sent. The adapter is built once per call, pinned to the address of the first locality decision, so retries never re-resolve | A retry can go out minutes after the first check; an admin's change in between must win, and DNS must not move data between attempts | Checking once (the gap found in review) |
| 4b | Cloud retries (owner review) | Cloud providers get no automatic busy retries unless `max_concurrent` is set: `provider_busy` with the provider's own `Retry-After`, and the person retries | Fewer automatic re-sends of data to a cloud endpoint, even with the re-check | Retrying cloud by default |
| 5 | Out of budget | New error `provider_busy` (HTTP 503 to the client with `Retry-After`), distinct from `provider_error`. The UI says the model is busy and offers Retry | The analyst learns to wait, the admin does not chase a fault that is not there | Reusing `provider_error` |
| 6 | Cancel | The API handler watches for the browser closing the request and sets a cancel flag the waiting call checks every half second; a cancelled wait leaves the queue at once and is audited with `error = cancelled` | A cancelled request must not keep its place or later run unseen | Ignore cancels (the queue fills with abandoned requests) |
| 7 | Health check | Does not take a slot. A refused connection or 503 during a health check while a call holds a slot reports "Busy" (not "Down") on AI providers and Health | The check must not wait behind inference, nor call a working server broken | Health takes a slot |
| 8 | Per-user limits | Kept as they are: Ask and Explain already allow one request per user at a time | One person cannot fill the queue | |
| 9 | Audit | One `llm_calls` row per request as today, plus two additive columns: `queue_wait_ms` and `busy_retries`. `error` gains `provider_busy` and `cancelled` | Shows whether slowness was the queue or the model | |
| 10 | UI | While a request waits more than 2 seconds, Ask and Explain show "Model busy, waiting for a free slot" with the time waited and Cancel. A small status endpoint per provider (`queued`, `running`) feeds it; it carries no prompt content | The analyst sees why nothing is happening | |
| 11 | Scope | One process (the app is single-process today). Several app processes against one model server would each have their own queue; the guide says to keep the default single process | Matches the deployment | A shared queue in SQLite (not needed yet) |

## Consequences

- Two analysts asking at once get answers one after the other instead of two slow answers, and a busy server no longer shows as broken.
- Callers can wait up to the budget (default 2 minutes) before hearing "busy". The UI shows the wait so it does not look hung.
- Admins with a GPU that can serve more at once raise `max_concurrent`.
- Docs (install, AI providers): recommend `OLLAMA_NUM_PARALLEL=1` and a context of 16k to 32k tokens on small hosts, and say that the app queues requests itself.

## Threat model (SPEC section 7)

| Id | Threat | ATT&CK / ATLAS | Mitigation |
|---|---|---|---|
| T60 | One user, a burst of scheduled summaries, or a loop starves everyone else of the model | ATLAS AML.T0029 Denial of ML Service; ATT&CK T1499 Endpoint Denial of Service | Per-provider queue with a wait budget, per-user one-at-a-time for Ask and Explain, cancels free their place, every wait and retry audited |

Availability only: the queue changes when a call runs, never what is sent. Classification checks, redaction, and the audit row happen before a request enters the queue, exactly as today.

## Tests

Fake provider with one slot: two Ask requests at once, the second waits and succeeds, the provider never sees two at once. 503, 503, 200: succeeds within the budget, `busy_retries = 2`. Busy past the budget: `provider_busy`, UI shows Retry. Cancel while waiting: place freed, row has `cancelled`. Health check during a long call: Busy or OK, never Down. Cloud provider with no `max_concurrent`: unchanged.

