"""Run the Ask accuracy suite against one provider and model (SPEC 5.7).

    uv run python -m evals.nl_queries.run --base-url http://127.0.0.1:11434/v1 \\
        --model llama3.1:8b [--api-key-env OPENAI_API_KEY] [--ids q001,q021] [--out report.json]

Everything runs in-process against a temporary data folder holding only the synthetic
fixture: the real gate (classification, audit), the real Ask agent, the real engine.
The API key is read from the named environment variable, never from the command line.
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI

from app.core.config import load_config
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.engine.duckdb import QueryEngine, QueryScope
from app.llm.agent import AskAgent
from app.main import create_app
from evals.nl_queries.compare import Compare, matches
from evals.nl_queries.fixture import SOURCES, write_lake

SUITE = Path(__file__).parent / "questions.yaml"
ACTOR = "eval-runner"


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    question: str
    sql: str
    compare: Compare = "set"


@dataclass(slots=True)
class CaseResult:
    id: str
    question: str
    executable: bool = False
    exact: bool = False
    check: str | None = None
    attempts: int = 0
    seconds: float = 0.0
    sql: str | None = None
    error: str | None = None
    call_ids: list[str] = field(default_factory=list)


def load_suite(path: Path = SUITE) -> tuple[list[Case], QueryScope]:
    doc = yaml.safe_load(path.read_text("utf-8"))
    cases = [Case(**q) for q in doc["questions"]]
    window = doc["window"]
    scope = QueryScope(
        sources=None,
        start=datetime.fromisoformat(window["start"]),
        end=datetime.fromisoformat(window["end"]),
    )
    return cases, scope


def build_lab(data_dir: Path, trusted_hosts: list[str] | None = None) -> FastAPI:
    env = {"APP__PATHS__DATA_DIR": str(data_dir)}
    if trusted_hosts:
        env["APP__LLM__TRUSTED_LOCAL_HOSTS"] = ",".join(trusted_hosts)
    app = create_app(load_config(Path("missing.yaml"), env))
    write_lake(data_dir / "lake")
    # Synthetic data only, so the sources are cloud_allowed and cloud models can be scored.
    with app.state.meta.connect() as con:
        for source in SOURCES:
            con.execute(
                "INSERT INTO sources (source_id, format, path, classification, created_at)"
                " VALUES (?, 'json', '/eval', 'cloud_allowed', datetime('now'))",
                (source,),
            )
    return app


def run_case(
    agent: AskAgent, engine: QueryEngine, provider_id: str, scope: QueryScope, case: Case
) -> CaseResult:
    out = CaseResult(case.id, case.question)
    reference = engine.run(case.sql, scope)
    started = time.perf_counter()
    try:
        outcome = agent.ask(ACTOR, provider_id, scope, case.question, [], [])
    except AppError as exc:
        out.seconds = round(time.perf_counter() - started, 2)
        out.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return out
    out.seconds = round(time.perf_counter() - started, 2)
    out.sql, out.check, out.attempts = outcome.answer.sql, outcome.check, outcome.attempts
    out.call_ids = outcome.call_ids
    try:
        got = engine.run(outcome.answer.sql, scope)
    except AppError as exc:
        out.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return out
    out.executable = True
    out.exact = matches(
        reference.rows, len(reference.columns), got.rows, len(got.columns), case.compare
    )
    return out


def summarise(results: list[CaseResult], label: str) -> dict[str, Any]:
    n = len(results)
    seconds = [r.seconds for r in results if r.sql is not None]
    return {
        "label": label,
        "questions": n,
        "executable_rate": round(sum(r.executable for r in results) / n, 3) if n else 0.0,
        "exact_rate": round(sum(r.exact for r in results) / n, 3) if n else 0.0,
        "median_seconds": round(statistics.median(seconds), 2) if seconds else None,
        "p90_seconds": round(sorted(seconds)[int(0.9 * (len(seconds) - 1))], 2)
        if seconds
        else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--api-key-env", help="Name of the environment variable holding the key")
    p.add_argument("--trusted-local-host", action="append", default=[])
    p.add_argument("--ids", help="Comma-separated question ids to run")
    p.add_argument("--out", type=Path, help="Write the full JSON report here")
    args = p.parse_args(argv)

    key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not key:
        print(f"{args.api_key_env} is not set", file=sys.stderr)
        return 2
    cases, scope = load_suite()
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c.id in wanted]

    with tempfile.TemporaryDirectory(prefix="ask-eval-") as tmp:
        app = build_lab(Path(tmp), args.trusted_local_host)
        configure_logging("WARNING")  # keep per-call logs out of the progress lines
        store = app.state.providers
        rec = store.add("eval", args.base_url, args.model, key)
        store.update(rec.provider_id, None, None, None, True, None, False)
        results = []
        for case in cases:
            r = run_case(app.state.ask, app.state.engine, rec.provider_id, scope, case)
            mark = "ok   " if r.exact else ("ran  " if r.executable else "fail ")
            print(f"{mark}{r.id} {r.seconds:>6.1f}s  {r.question}", file=sys.stderr)
            results.append(r)

    summary = summarise(results, f"{args.model} @ {args.base_url}")
    print(json.dumps(summary, indent=2))
    if args.out:
        report = {"summary": summary, "results": [asdict(r) for r in results]}
        args.out.write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
