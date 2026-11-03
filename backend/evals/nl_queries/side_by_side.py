"""Two or more models on the whole Ask suite, side by side, in one command (owner, 2026-11-02).

    uv run python -m evals.nl_queries.side_by_side --base-url http://<ollama-host>:11434
    # defaults: --models qwen3.5:4b,qwen3.5:9b --thinking none, answer step measured

For each model: the data questions (rows right or wrong), the general-guidance set (routes
right or wrong), and Ask's answer step on every result with event ids. Prints one table:
accuracy, misroutes both ways, time to first rows (what `ask.summarize: false` gives) and
to the full answer (summaries on), and what the citation check kept and removed. Each
model's full JSON report goes to `--out-dir`.

Runs in-process against a temporary folder holding only the synthetic fixture, exactly as
`evals.nl_queries.run` does. Only the model calls leave this machine.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import configure_logging
from evals.nl_queries.run import (
    CaseResult,
    build_lab,
    load_knowhow,
    load_suite,
    run_routed,
    summarise,
)

MODELS = "qwen3.5:4b,qwen3.5:9b"


def api_url(base: str) -> str:
    """The OpenAI-compatible root: Ollama's address with or without `/v1`."""
    base = base.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def missing_models(base: str, models: list[str], key: str | None) -> list[str]:
    """Models the server does not list, so a typo or an unpulled model fails at once
    instead of after 130 errors. Raises httpx.HTTPError when the server is unreachable."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    res = httpx.get(f"{base}/models", headers=headers, timeout=15.0)
    res.raise_for_status()
    have = {str(m.get("id")) for m in res.json().get("data", []) if isinstance(m, dict)}
    return [m for m in models if m not in have and f"{m}:latest" not in have]


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def _secs(median: float | None, p90: float | None) -> str:
    return "n/a" if median is None else f"{median:.1f} s / {p90:.1f} s"


ROWS: list[tuple[str, Any]] = [
    ("Rows run (data questions)", lambda s: _pct(s["executable_rate"])),
    ("Right rows (accuracy)", lambda s: _pct(s["exact_rate"])),
    (
        "Data questions sent to guidance",
        lambda s: f"{s['data_sent_to_knowhow']} of {s['questions'] - s['knowhow_questions']}",
    ),
    (
        "Guidance questions sent to data",
        lambda s: f"{s['knowhow_sent_to_data']} of {s['knowhow_questions']}",
    ),
    ("Answered from the library", lambda s: _pct(s["library_rate"])),
    (
        "First rows, median / p90",
        lambda s: _secs(s["median_first_rows_seconds"], s["p90_first_rows_seconds"]),
    ),
    (
        "Full answer, median / p90",
        lambda s: _secs(s["median_answer_seconds"], s["p90_answer_seconds"]),
    ),
    ("Summaries shown", lambda s: str(s["summaries_shown"])),
    ("No summary: nothing cited", lambda s: str(s["summaries_none"])),
    ("No summary: rows had no event ids", lambda s: str(s["summaries_no_event_ids"])),
    ("Statements kept / removed", lambda s: f"{s['claims_kept']} / {s['claims_removed']}"),
    ("Errors", lambda s: str(s["errors"])),
]


def table(summaries: dict[str, dict[str, Any]]) -> str:
    """A Markdown table, one column per model, ready to paste into the README or a PR."""
    names = list(summaries)
    lines = [
        "| | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for label, cell in ROWS:
        lines.append(f"| {label} | " + " | ".join(cell(summaries[m]) for m in names) + " |")
    return "\n".join(lines)


def run_model(
    base: str,
    model: str,
    key: str | None,
    thinking: str | None,
    answer: bool,
    trusted: list[str],
    ids: set[str] | None,
) -> tuple[dict[str, Any], list[CaseResult]]:
    cases, scope = load_suite()
    cases += load_knowhow()
    if ids:
        cases = [c for c in cases if c.id in ids]
    results: list[CaseResult] = []
    with tempfile.TemporaryDirectory(prefix="ask-eval-") as tmp:
        app = build_lab(Path(tmp), trusted)
        configure_logging("WARNING")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        store = app.state.providers
        rec = store.add("eval", base, model, key)
        store.update(rec.provider_id, None, None, None, True, None, False, reasoning=thinking)
        for i, case in enumerate(cases, 1):
            r = run_routed(app, rec.provider_id, scope, case, answer=answer)
            mark = (
                "route"
                if r.misroute
                else "ok   "
                if r.exact
                else "ran  "
                if r.executable
                else "fail "
            )
            print(f"[{model} {i}/{len(cases)}] {mark}{r.id} {r.seconds:>6.1f}s", file=sys.stderr)
            results.append(r)
    label = f"{model}, thinking {thinking or 'default'}, routed" + (
        ", answer step" if answer else ""
    )
    return summarise(results, label), results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--base-url", required=True, help="Ollama or any OpenAI-compatible server")
    p.add_argument("--models", default=MODELS, help=f"Comma-separated (default {MODELS})")
    p.add_argument(
        "--thinking",
        choices=["none", "low", "medium", "high", "default"],
        default="none",
        help="Sent as reasoning_effort; none is Thinking Off (default), as Ask is set up",
    )
    p.add_argument(
        "--no-answer",
        action="store_true",
        help="Skip the answer step: only what ask.summarize: false gives",
    )
    p.add_argument("--api-key-env", help="Name of the environment variable holding a key")
    p.add_argument("--trusted-local-host", action="append", default=[])
    p.add_argument("--ids", help="Comma-separated question ids, for a quick check")
    p.add_argument("--out-dir", type=Path, default=Path("ask-eval"), help="JSON reports here")
    args = p.parse_args(argv)

    key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not key:
        print(f"{args.api_key_env} is not set", file=sys.stderr)
        return 2
    base = api_url(args.base_url)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    try:
        missing = missing_models(base, models, key)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Cannot list models at {base}: {exc}", file=sys.stderr)
        return 2
    if missing:
        print(
            f"Not on {base}: {', '.join(missing)}. Pull them first, for example:", file=sys.stderr
        )
        for m in missing:
            print(f"  ollama pull {m}", file=sys.stderr)
        return 2
    thinking = None if args.thinking == "default" else args.thinking
    ids = set(args.ids.split(",")) if args.ids else None
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, dict[str, Any]] = {}
    for model in models:
        summary, results = run_model(
            base, model, key, thinking, not args.no_answer, args.trusted_local_host, ids
        )
        summaries[model] = summary
        report = {"summary": summary, "results": [asdict(r) for r in results]}
        path = args.out_dir / f"{model.replace(':', '-').replace('/', '-')}.json"
        path.write_text(json.dumps(report, indent=2))
        print(f"Wrote {path}", file=sys.stderr)
    print(table(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
