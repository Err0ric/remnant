"""Measure how many SigmaHQ rules the DuckDB backend compiles (Slice 4 DoD, ADR-0006).

Usage, from backend/:
    git clone --depth 1 --branch r2026-07-01 https://github.com/SigmaHQ/sigma /tmp/sigma
    uv run python ../scripts/sigma_compile_rate.py /tmp/sigma/rules linux windows

A rule counts only if `detect/rules.compile_rule` accepts it (conversion, Windows channel
narrowing, query guard) and its condition executes in DuckDB against an empty table with
the real events columns (so a binder or type error is a failure, not a success).
Prints the rate per folder and the most common reasons a rule failed.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import duckdb

from app.core.schema import COLUMNS
from app.detect.rules import compile_rule


def reason(exc: Exception) -> str:
    text = str(exc).split(" (while converting")[0].split("\n")[0]
    return f"{type(exc).__name__}: {text[:90]}"


def empty_events() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:", config={"enable_external_access": False})
    cols = ", ".join(f'"{c.name}" {c.duckdb_type}' for c in COLUMNS)
    con.execute(f"CREATE TABLE events ({cols})")
    return con


def measure(folder: Path) -> dict[str, object]:
    con = empty_events()
    ok = 0
    failures: Counter[str] = Counter()
    files = sorted(folder.rglob("*.yml"))
    for path in files:
        try:
            # compile_rule() converts, adds Windows narrowing, and passes the guard.
            rule = compile_rule(path.read_bytes())
            query = f"SELECT event_id FROM events WHERE {rule.condition}"  # noqa: S608
            con.execute(query).fetchall()
            ok += 1
        except Exception as exc:  # every failure is counted, none stops the run
            failures[reason(exc)] += 1
    total = len(files)
    return {
        "folder": folder.name,
        "rules": total,
        "compiled": ok,
        "rate": round(ok / total, 4) if total else 0.0,
        "top_failures": failures.most_common(10),
    }


def main(argv: list[str]) -> int:
    root = Path(argv[1])
    results = [measure(root / name) for name in argv[2:]]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
