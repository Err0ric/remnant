# ADR-0032: Optional de-duplication of identical lines from Loki

Status: **Proposed** 2026-10-22. Stopped for owner review; nothing built.

## Context

Real log pipelines can deliver the same line to Loki twice: two collectors on one host (Promtail and Alloy during a migration), a syslog relay that forwards to two receivers that both push to Loki, or one line labelled into two streams (`job="syslog"` and `job="firewall"`). Loki keeps both, because they are different streams.

How the Loki source reads today (`ingest/connectors/loki.py`, ADR-0011):

| Part | Today |
|---|---|
| Position | The newest timestamp read plus the digests of lines read at exactly that nanosecond |
| Line identity | `digest(labels, line)`: the stream labels are part of it |
| Result | Re-reads after a restart or a page boundary are skipped. The same text at the same time in two streams is stored twice |

Stored twice means counts double for that source: Dashboard panels, thresholds, rule matches, AI usage, and entity risk. The raw lines are both genuine records of what Loki held, so dropping one is a choice, not a fix.

## Decision (proposed)

| # | Question | Proposal | Why | Alternative |
|---|---|---|---|---|
| 1 | Default | Off. Every line Loki returns is stored, as today | Nothing is dropped unless an admin decides the duplicates are noise | On by default (silently drops records some installs consider evidence) |
| 2 | Setting | Per Loki source: **Drop identical lines from other streams**, with a window: same nanosecond (default), or up to 1, 5, or 60 seconds apart | Collectors timestamp the same line slightly differently; the admin picks how strict | One global setting (the right answer differs per pipeline) |
| 3 | What "identical" means | The line text exactly as Loki returned it (the future `raw`), ignoring labels, within the window. Never a normalized or trimmed form | `raw` is sacred (rule 5): two lines that differ by a byte are two records | Fuzzy matching (would drop real events) |
| 4 | Where | In the Loki poller, before parsing: a bounded in-memory set of `(window bucket, sha256(line))` for the current poll and the previous window, plus the window's digests kept in the position so a restart does not let a duplicate through | Cheapest point; parsing and storage never see the copy | In the lake after the fact (rewrites Parquet, conflicts with the integrity ledger, ADR-0022) |
| 5 | Accounting | Each dropped line is counted per source (`duplicates_dropped`), shown on Health next to records skipped, and the first drop after enabling writes an audit row `source.dedup_active`. The setting change is audited `source.update` | A dropped line must be visible as a number, never silent | Logging each drop (volume) |
| 6 | Which copy is kept | The first one read in Loki's forward order (time, then stream order). Its labels are the ones in `envelope.loki_labels` | Deterministic and explainable | Merging labels from both (a new, made-up record) |
| 7 | Other sources | Loki only for now. Files, the syslog listener, and OTLP are out of scope | Duplicates there come from configuration the admin controls directly | A generic ingest de-dup stage (bigger change, needs its own ADR) |

## Cost

| Cost | Estimate |
|---|---|
| Memory | One 32-byte digest per line inside the window. Same-nanosecond mode: at most one poll page (1,000 lines). A 60-second window at 2,000 lines/s: about 120,000 digests, about 8 MB with set overhead |
| CPU | One SHA-256 per line, already computed today for the position (labels plus line); this adds one over the line alone. Negligible next to parsing |
| Position size | The window's digests are kept in the checkpoint; capped (for example 50,000) with a warning on Health when the cap is reached, at which point the oldest drop out and a duplicate may get through |
| Correctness risk | A genuine repeated line (the same error logged twice in the same second by one app) is dropped in the wider windows. That is why the default window is the same nanosecond and the setting says so |

## Consequences

- Counts on affected sources become right once enabled; history before enabling keeps its duplicates (no rewrite).
- The integrity ledger and the audit chain are unchanged: dropped lines are never written, so there is nothing to seal.
- Health shows a new number per Loki source.

## Threat model (SPEC section 7)

- New risk: an attacker who can write to Loki sends a crafted copy of a line first, with misleading labels, so the real one is dropped (ATT&CK T1562 Impair Defenses). Mitigation: off by default, the kept copy's labels are visible, drops are counted, and the window defaults to one nanosecond.
- No AI-facing change; no ATLAS impact.

## Tests (when built)

- Same line in two streams at the same nanosecond: one stored, one counted.
- Same line 2 s apart with a 1 s window: both stored; with 5 s: one.
- Lines that differ by one byte: both stored.
- Restart inside the window: the copy is still dropped.
- Off: identical to today.
