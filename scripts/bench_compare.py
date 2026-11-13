#!/usr/bin/env python3
"""Page speed before and after a change (owner rule, 2026-11-08): the same synthetic lake
served by two versions of the app, each page's API calls timed the way the browser makes
them (all at once), several interleaved rounds, medians compared.

    cd backend && uv run python ../scripts/bench_compare.py --before origin/main --after ..

`--before` and `--after` are each a git ref or a checkout folder (its HEAD commit). Both
sides are built the same way: the commit is exported with `git archive` into a temporary
folder, so neither side sees a checkout's own data/, config, frontend build, or other
untracked files; each server imports its own copy (checked at start), runs with the same
environment (no inherited APP__ settings, no web UI), and reads its own copy of the data.
Timed servers do not refresh default views in the background, and the page cache is
emptied before every timed page, so every load is computed in the request on both sides
(a cache answer would time nothing, and one server's refreshes would slow the other).
The lake is built once with the `--before` code (scripts/demo data,
the demo lab's rules and detections, Claude Code telemetry, a loggen volume, Identities
with organization domains and aliases, two saved searches using {{person:...}} and
{{org_domains}}) and kept in `--lake` for a day; each server runs on its own copy. Ask is
timed on its library route with a scripted router that answers at once (not an LLM), so
only the server's own work is timed.

Prints a Markdown table and exits 1 when a page is flagged (owner, 2026-11-08: more than
10% AND at least 100 ms slower, or more than 200 ms slower regardless, in the median,
confirmed by the fastest round or by 10% more server CPU; a page flagged on the first pass is timed again for twice the
rounds first), 2 when it could not measure.
Standard library only, plus the backend's packages for the demo GeoIP file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import devauth

ROOT = Path(__file__).resolve().parents[1]
# One zone per round, never repeated in a run (rounds 0 to 3n+1 for --rounds n up to 8).
ZONES = tuple(f"Etc/GMT{h:+d}" for h in range(-14, 13) if h)
PCT, FLOOR_MS, MS = 10.0, 100.0, 200.0
ROUTER = "Bench router (scripted, not an LLM)"
QUESTION = "Tools used by person in Claude Code"
PERSON_SQL = (
    "SELECT {{person:actor_user_name}} AS person, count(*) AS events FROM events"
    " WHERE time >= {{start}} AND time < {{end}} GROUP BY 1 ORDER BY 2 DESC LIMIT 50"
)
OUTSIDE_SQL = (
    "SELECT {{person:actor_user_name}} AS person, count(*) AS events FROM events"
    " WHERE time >= {{start}} AND time < {{end}} AND actor_user_name LIKE '%@%'"
    " AND NOT list_contains({{org_domains}}, split_part(lower(actor_user_name), '@', 2))"
    " GROUP BY 1 ORDER BY 2 DESC LIMIT 50"
)
LOGS_SQL = (
    "SELECT time, severity_id, source_id, device_hostname, actor_process_name, message,"
    " event_id\nFROM events\nWHERE coalesce(raw ILIKE $p0 ESCAPE '\\' OR message ILIKE $p0"
    " ESCAPE '\\', false)\nORDER BY coalesce(time, time_observed) DESC"
)
COUNTS_SQL = (
    "SELECT source_id, count(*) AS events FROM events GROUP BY source_id ORDER BY source_id"
)
Call = tuple[str, str, Any]  # method, path, JSON body; {start} {end} {tz} filled per round


def pages() -> dict[str, list[Call]]:
    """What each page asks for as it loads (recorded from the browser, 2026-11-08), minus
    the shell's own small calls (meta, auth state, install), which every page shares."""
    week = "start={start}"
    return {
        "Dashboard": [
            ("GET", "/api/alerts?state=open", None),
            ("GET", "/api/ai/watch/summary?days=7&tz={tz}", None),
        ]
        + [
            ("GET", f"/api/dashboard/sections?window=7d&part={p}&tz={{tz}}", None)
            for p in ("identity", "attacks", "detections")
        ]
        + [
            ("GET", p, None)
            for p in (
                "/api/sources",
                "/api/overview",
                "/api/dashboards",
                "/api/schedules",
                "/api/ai/watch/status",
            )
        ],
        "Logs": [
            ("POST", "/api/query", {"sql": COUNTS_SQL}),
            ("POST", "/api/search/compile", {"text": "failed"}),
            (
                "POST",
                "/api/query",
                {"sql": LOGS_SQL, "params": {"p0": "%failed%"}, "start": "{start}"},
            ),
            ("POST", "/api/search/facets", {"text": "failed", "start": "{start}"}),
        ],
        "Logs, saved search with {{person}}": [
            ("POST", "/api/searches/bench_person/run", {"start": "{start}"})
        ],
        "Logs, saved search with {{org_domains}}": [
            ("POST", "/api/searches/bench_outside/run", {"start": "{start}"})
        ],
        "Logs, SQL with {{person}}": [
            (
                "POST",
                "/api/query",
                {
                    "sql": PERSON_SQL.replace("time >= {{start}} AND time < {{end}}", "true"),
                    "start": "{start}",
                },
            )
        ],
        "Ask, library route": [("POST", "/api/ask", {"question": QUESTION, "tz": "{tz}"})],
        "People & devices": [("GET", f"/api/entities/risk?{week}", None)],
        "Person page": [
            ("GET", f"/api/entities/summary?kind=user&value=alice&{week}", None),
            ("GET", "/api/people/alice/timeline?days=7", None),
            ("GET", f"/api/entities/risk?{week}", None),
            ("GET", f"/api/entities/graph?mode=entity&kind=user&value=alice&{week}", None),
        ],
        "Investigate, AI flow": [
            ("GET", f"/api/entities/graph?mode=ai&kind=user&value=alice&{week}", None)
        ],
        "Top bar lookup": [("GET", f"/api/entities/lookup?q=alice&{week}", None)],
        "AI usage": [("GET", f"/api/ai/usage?{week}", None)],
        "Alerts": [("GET", "/api/alerts?state=open", None)],
    }


def ps_time_ms(text: str) -> float:
    """`ps -o time=` ([dd-][hh:]mm:ss[.cc]) in milliseconds."""
    days, _, rest = text.strip().rpartition("-")
    total = 0.0
    for part in rest.split(":"):
        total = total * 60 + float(part)
    return (total + int(days or 0) * 86_400) * 1000


# Signed-in administrator per server started here (D245: no server runs without accounts).
SESSIONS: dict[str, devauth.Session] = {}


class Api:
    def __init__(self, base: str, pid: int | None = None) -> None:
        self.base = base
        self.csrf = ""
        self.pid = pid

    def cpu_ms(self) -> float:
        """The server process's CPU time so far: /proc on Linux, `ps` elsewhere (macOS);
        0 when it cannot be read."""
        try:
            fields = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()
            return (int(fields[11]) + int(fields[12])) * 1000 / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, IndexError):
            pass
        try:
            out = subprocess.run(  # noqa: S603  # fixed arguments, our own child's pid
                ["ps", "-o", "time=", "-p", str(self.pid)],  # noqa: S607  # ps on PATH
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout  # fmt: skip
            return ps_time_ms(out)
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0

    def call(self, method: str, path: str, body: Any = None, timeout: float = 300) -> Any:
        session = SESSIONS.get(self.base)
        if session is None and not self.csrf:
            with urllib.request.urlopen(self.base + "/api/auth/state", timeout=10) as r:  # noqa: S310  # loopback
                self.csrf = json.loads(r.read()).get("csrf_token") or "-"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)  # noqa: S310  # loopback
        req.add_header("Content-Type", "application/json")
        for name, value in (session.headers() if session else {"X-CSRF-Token": self.csrf}).items():
            req.add_header(name, value)
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310  # loopback
            out = res.read()
        return json.loads(out) if out else None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Router(BaseHTTPRequestHandler):
    """Answers Ask's routing call at once with the library query whose example question is
    the question asked (OpenAI-compatible). Scripted, not a model."""

    def do_GET(self) -> None:  # http.server's name
        self._send({"data": [{"id": "bench-router"}]})

    def do_POST(self) -> None:  # same
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        ref = None
        for m in body.get("messages", []):
            try:
                ask = json.loads(m.get("content") or "")
            except ValueError:
                continue
            if isinstance(ask, dict) and "candidates" in ask:
                hits = [c for c in ask["candidates"] if ask["question"] in c.get("questions", [])]
                ref = (hits or ask["candidates"] or [{}])[0].get("ref")
        answer = {"kind": "data", "query": ref, "params": {}}
        msg = {"role": "assistant", "content": json.dumps(answer)}
        self._send({"choices": [{"index": 0, "finish_reason": "stop", "message": msg}]})

    def _send(self, body: dict[str, Any]) -> None:
        out = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args: Any) -> None:
        pass


# Run in the server process before the app starts: it must import the copy it was started
# for (the shared venv can hold an editable install of another checkout), and a timed
# server does not refresh default views in the background (REMNANT_BENCH_NO_REFRESH).
BOOT = """
import os, sys
from pathlib import Path
import app
want = Path(os.environ["REMNANT_BENCH_APP"]).resolve()
got = Path(app.__file__).resolve().parent
if got != want:
    print(f"bench: this server imported the app from {got}, not {want}", file=sys.stderr, flush=True)
    raise SystemExit(70)
print(f"bench: app from {got}", file=sys.stderr, flush=True)
if os.environ.get("REMNANT_BENCH_NO_REFRESH") == "1":
    import app.main
    if not hasattr(app.main, "REFRESH_EVERY_S"):
        print("bench: cannot turn off background refresh (app.main.REFRESH_EVERY_S)", file=sys.stderr)
        raise SystemExit(70)
    app.main.REFRESH_EVERY_S = 10.0**9
from app.launch import run
raise SystemExit(run())
"""
WRONG_APP = 70


def serve(
    code: Path, data: Path, lake: Path, port: int, log: Path, python: str = sys.executable,
    static: Path | None = None, refresh: bool = True,
) -> subprocess.Popen[bytes]:  # fmt: skip
    roots = ",".join(str(lake / d) for d in ("logs", "vol", "lab"))
    # The same environment for every server: nothing inherited from APP__ variables.
    env = {k: v for k, v in os.environ.items() if not k.startswith("APP__")} | {
        "PYTHONPATH": str(code / "backend"), "APP__SERVER__HOST": "127.0.0.1",
        "APP__SERVER__PORT": str(port), "APP__PATHS__DATA_DIR": str(data),
        "APP__PATHS__ALLOWED_ROOTS": roots, "APP__PATHS__RULE_ROOTS": str(lake / "rules"),
        "APP__ENRICHMENT__PLACE_DOCUMENTATION_RANGES": "true",
        "REMNANT_BENCH_APP": str(code / "backend" / "app"),
        "REMNANT_BENCH_NO_REFRESH": "0" if refresh else "1",
    }  # fmt: skip
    if static is not None:
        env["APP__SERVER__STATIC_DIR"] = str(static)
    cmd = [python, "-c", BOOT]
    with log.open("ab") as out:
        proc = subprocess.Popen(cmd, cwd=code / "backend", env=env, stdout=out, stderr=out)  # noqa: S603  # fixed command
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            why = "failed its start check" if proc.returncode == WRONG_APP else "exited"
            raise RuntimeError(f"server from {code} {why}; see {log}")
        try:
            base = f"http://127.0.0.1:{port}"
            Api(base).call("GET", "/api/auth/state", timeout=3)
            session = devauth.sign_in(base, data, env, code / "backend", python)
            if session is not None:
                SESSIONS[base] = session
            return proc
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    proc.terminate()
    raise RuntimeError(f"server from {code} did not answer; see {log}")


def stop(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()


# Each count below is a POST, and since #469 the server records every non-GET request in
# its built-in server_events source, so counting those would never hold still.
SETTLE_SQL = "SELECT count(*) FROM events WHERE source_id <> 'server_events'"
SETTLE_LIMIT_S = 600  # a copied lake: only files its copy picks up
BUILD_SETTLE_LIMIT_S = 3600  # a new lake: ingest of the whole build


def settle(api: Api, name: str, limit_s: int = SETTLE_LIMIT_S) -> int:
    """Wait until ingest stops adding events: the same count for 30 s (four reads 10 s
    apart). Two reads 5 s apart stopped a full-size build at 383,000 of 482,000 events,
    and each server then ingested the rest while it was being timed. The bench's own
    requests are not counted. Still changing after `limit_s`: fail with the counts,
    never wait on."""
    seen: list[int] = []
    start = time.monotonic()
    said = start
    while time.monotonic() - start < limit_s:
        n = int(api.call("POST", "/api/query", {"sql": SETTLE_SQL})["rows"][0][0])
        seen = [*seen[-3:], n]
        if len(seen) == 4 and len(set(seen)) == 1 and n > 0:
            return n
        if time.monotonic() - said >= 60:
            print(f"settling {name}: {n:,} events", file=sys.stderr)
            said = time.monotonic()
        time.sleep(10)
    raise RuntimeError(
        f"{name} server still adding events after {limit_s // 60} min; last counts {seen}"
    )


def build(code: Path, lake: Path, events: int, router: int, log: Path, shape: float = 0.0) -> int:
    shutil.rmtree(lake, ignore_errors=True)
    for d in ("data", "logs", "vol", "lab", "rules"):
        (lake / d).mkdir(parents=True)
    scripts = code / "scripts"

    def run(*a: object) -> None:
        cmd = [sys.executable, *map(str, a)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, cwd=code / "backend")  # noqa: S603  # our own scripts

    run(scripts / "demo/generate.py", lake / "logs")
    run(scripts / "loggen.py", "--out", lake / "vol", "--backfill", events, "--rate", 0, "--seed", 7)  # fmt: skip
    port = free_port()
    proc = serve(code, lake / "data", lake, port, log)
    try:
        url = f"http://127.0.0.1:{port}"
        # Both sign in with the account `serve` made, which is in this lake's data folder,
        # not the demo's (D245): without --data a rebuild of the lake stopped here.
        run(scripts / "demo/load.py", "--url", url, "--logs", lake / "logs", "--data", lake / "data")  # fmt: skip
        run(scripts / "demo_lab.py", "--url", url, "--logs", lake / "lab", "--rules", lake / "rules", "--data", lake / "data")  # fmt: skip
        api = Api(url)
        for sid, fmt, sub, glob in (("volume_syslog", "syslog", "syslog", "**/*.log"), ("volume_web", "json", "apps", "*.jsonl")):  # fmt: skip
            api.call("POST", "/api/sources", {"source_id": sid, "format": fmt, "path": str(lake / "vol" / sub), "glob": glob, "template_id": "auto"})  # fmt: skip
        api.call("PUT", "/api/identities/domains", {"domains": ["example.com", "example.org"]})
        people = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan", "judy"]  # fmt: skip
        pairs = [("userpass-alice", "alice"), ("userpass-bob", "bob"), ("approle-ci", "carol"), ("svc_deploy", "dave"), ("svc_backup", "erin"), ("apikey_00", "grace"), ("dana", "judy")]  # fmt: skip
        pairs += [(f"user{i:03d}.ext@example.net", people[i % 10]) for i in range(200)]
        for alias, person in pairs:
            api.call("PUT", "/api/identities/aliases", {"alias": alias, "person": person})
        for sid, name, sql in (("bench_person", "Events per person", PERSON_SQL), ("bench_outside", "Outside accounts", OUTSIDE_SQL)):  # fmt: skip
            api.call("POST", "/api/searches", {"id": sid, "name": name, "sql": sql, "visibility": "shared"})  # fmt: skip
        api.call("POST", "/api/providers", {"name": ROUTER, "base_url": f"http://127.0.0.1:{router}/v1", "model": "bench-router"})  # fmt: skip
        point_router(api, router)
        if shape:  # opt-in: a real-shaped week of sign-ins and DNS beside it (owner item 2)
            env = {**os.environ, "PYTHONPATH": str(code / "backend")}
            gen = ROOT / "scripts" / "fixtures" / "real_shape.py"
            cmd = [sys.executable, str(gen), "--lake", str(lake / "data" / "lake"), "--scale", str(shape)]  # fmt: skip
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, cwd=code / "backend", env=env)  # noqa: S603  # fmt: skip
        n = settle(api, "build", BUILD_SETTLE_LIMIT_S)
    finally:
        stop(proc)
    kept = {"events": n, "loggen": events, "shape": shape, "at": time.time()}
    (lake / "built.json").write_text(json.dumps(kept))
    return n


def point_router(api: Api, port: int) -> None:
    """Ask's provider is the scripted router, wherever it listens this run."""
    mine = [p for p in api.call("GET", "/api/providers") if p.get("name") == ROUTER]
    for p in mine:
        body = {"base_url": f"http://127.0.0.1:{port}/v1", "enabled": True}
        api.call("PATCH", f"/api/providers/{p['provider_id']}", body)


def export(ref: str, tmp: Path, name: str) -> tuple[Path, str]:
    """A clean copy of a commit (a ref, or a checkout folder's HEAD), the same way for both
    sides: `git archive` into tmp/name. Returns the folder and the commit."""
    folder = (Path(ref) / ".git").exists()
    git = ["git", "-C", str(Path(ref) if folder else ROOT)]
    rev = "HEAD" if folder else ref
    sha = subprocess.run([*git, "rev-parse", "--verify", f"{rev}^{{commit}}"], check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603  # fixed command  # fmt: skip
    if folder and subprocess.run([*git, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip():  # noqa: S603  # same  # fmt: skip
        print(f"{name}: {ref} has uncommitted changes; only its commit {sha[:12]} is measured", file=sys.stderr)  # fmt: skip
    out = tmp / name
    out.mkdir()
    tar = subprocess.Popen([*git, "archive", "--format=tar", sha], stdout=subprocess.PIPE)  # noqa: S603  # same
    subprocess.run(["tar", "-x", "-C", str(out)], stdin=tar.stdout, check=True)  # noqa: S603, S607  # same
    if tar.wait() != 0:
        raise RuntimeError(f"git archive {sha} failed")
    if (out / "backend" / "config" / "app.yaml").exists() or (out / "frontend" / "dist").exists():
        raise RuntimeError(f"{name}: the commit holds a config or a web build; not a clean copy")
    return out, sha


def fill(v: Any, values: dict[str, str]) -> Any:
    if isinstance(v, str):
        for k, x in values.items():
            v = v.replace("{" + k + "}", urllib.parse.quote(x) if v.startswith("/api/") else x)
        return v
    if isinstance(v, dict):
        return {k: fill(x, values) for k, x in v.items()}
    return v


def time_page(api: Api, calls: list[Call], values: dict[str, str]) -> tuple[float, list[str]]:
    errors: list[str] = []

    def one(c: Call) -> None:
        try:
            api.call(c[0], fill(c[1], values), fill(c[2], values), timeout=120)
        except (OSError, urllib.error.URLError) as exc:
            errors.append(f"{c[0]} {c[1].split('?')[0]}: {getattr(exc, 'code', exc)}")

    threads = [threading.Thread(target=one, args=(c,)) for c in calls]
    t = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return (time.perf_counter() - t) * 1000, errors


Times = dict[str, dict[str, list[float]]]
KEYS = ("before", "after", "before_cpu", "after_cpu")


def medians(t: dict[str, list[float]], kind: str = "") -> tuple[float, float]:
    return statistics.median(t["before" + kind]), statistics.median(t["after" + kind])


def measure(
    sides: dict[str, Api], wanted: dict[str, list[Call]], rounds: int, first: int, times: Times
) -> list[str]:
    """Time each page on both servers, alternating which goes first; round `first` only
    warms up. Each round asks with a new time zone and start, so no cache answers."""
    failures: list[str] = []
    now = datetime.now(UTC)
    for r in range(first, first + rounds + 1):
        values = {
            "start": (now - timedelta(days=7, seconds=r)).isoformat().replace("+00:00", "Z"),
            "tz": ZONES[r % len(ZONES)],  # one per round, so no key repeats
        }
        order = ("before", "after") if r % 2 == 0 else ("after", "before")
        for page, calls in wanted.items():
            for side in order:
                # Any successful change empties the page cache (`clear_on_change`); a
                # query does. So this load is computed, not answered from an earlier
                # round or page.
                sides[side].call("POST", "/api/query", {"sql": "SELECT 1"})
                cpu = sides[side].cpu_ms()
                ms, errors = time_page(sides[side], calls, values)
                failures += [f"{side} {page}: {e}" for e in errors]
                if r > first:
                    times[page][side].append(ms)
                    times[page][f"{side}_cpu"].append(sides[side].cpu_ms() - cpu)
    return failures


def judge(t: dict[str, list[float]]) -> str:
    """A page is flagged when its median wall time breaks the owner's rule and something
    other than the machine's load confirms it: its fastest round breaks the rule too (a
    slower path or a lock wait slows every round), or the server spent more than 10% more
    CPU on it. Load from other work on a shared machine only adds wall time, moving the
    median but rarely every round and not this server's CPU."""
    if not flag(*medians(t)):
        return ""
    cb, ca = medians(t, "_cpu")
    if flag(min(t["before"]), min(t["after"])) or (cb > 0 and ca > cb * (1 + PCT / 100)):
        return "SLOWER"
    return ""


def flag(before: float, after: float) -> str:
    """The owner's rule (2026-11-08): measure at the page level; flag a page only if it is
    more than 10% AND at least 100 ms slower, or more than 200 ms slower regardless."""
    d = after - before
    if d > MS or (d >= FLOOR_MS and before > 0 and d / before * 100 > PCT):
        return "SLOWER"
    return ""


def main() -> int:
    # A stop (the queue's timeout, a person's kill) still runs the cleanup below, so no
    # server outlives the bench.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--before", default="origin/main", help="git ref or checkout folder")
    ap.add_argument("--after", default="HEAD", help="git ref or checkout folder")
    ap.add_argument("--rounds", type=int, default=5, help="timed rounds after one warm-up")
    # Full size (owner, 2026-11-08): with the demo data this is a lake of about 481,000
    # events, the size #445 was measured on; costs that grow with the lake show up.
    ap.add_argument("--events", type=int, default=400_000, help="loggen events in the lake")
    ap.add_argument("--lake", type=Path, default=ROOT / "data" / "bench" / "lake")
    # Off by default, so the queue's lake stays the documented one. 1 adds about 1.9M
    # sign-ins and 5.7M DNS queries over 7 days (scripts/fixtures/real_shape.py, 2.7 GB);
    # use its own --lake, since each side copies the data folder.
    ap.add_argument("--real-shape", type=float, default=0.0, metavar="SCALE",
                    help="add a real-shaped week of sign-ins and DNS at this scale")  # fmt: skip
    ap.add_argument("--rebuild", action="store_true", help="build the lake even if one is kept")
    ap.add_argument("--only", action="append", default=[], help="pages to time (default all)")
    ap.add_argument("--json", type=Path, help="also write the medians here")
    args = ap.parse_args()
    lake: Path = args.lake.resolve()
    tmp = Path(tempfile.mkdtemp(prefix="bench-compare-"))
    cleanups: list[Callable[[], None]] = [lambda: shutil.rmtree(tmp, ignore_errors=True)]
    procs: list[subprocess.Popen[bytes]] = []
    log = tmp / "servers.log"
    if 3 * args.rounds + 2 > len(ZONES):
        print(f"--rounds is at most {(len(ZONES) - 2) // 3}", file=sys.stderr)
        return 2
    try:
        before, before_sha = export(args.before, tmp, "before")
        after, after_sha = export(args.after, tmp, "after")
        print(f"before: {args.before} at {before_sha[:12]}; after: {args.after} at {after_sha[:12]}", file=sys.stderr)  # fmt: skip
        built = lake / "built.json"
        kept = json.loads(built.read_text()) if built.is_file() else {}
        # A kept lake counts only if it is a day old at most and the size asked for.
        fresh = (
            time.time() - kept.get("at", 0) < 86400 and kept.get("loggen") == args.events
            and kept.get("shape", 0.0) == args.real_shape
        )  # fmt: skip
        router = ThreadingHTTPServer(("127.0.0.1", 0), Router)
        router_port = int(router.server_address[1])
        threading.Thread(target=router.serve_forever, daemon=True).start()
        if args.rebuild or not fresh:
            t = time.monotonic()
            n = build(before, lake, args.events, router_port, log, args.real_shape)
            print(f"lake: {n:,} events, built in {time.monotonic() - t:.0f} s", file=sys.stderr)
        sides: dict[str, Api] = {}
        for name, code in (("before", before), ("after", after)):
            shutil.copytree(lake / "data", tmp / f"data-{name}")
            port = free_port()
            procs.append(serve(code, tmp / f"data-{name}", lake, port, log, refresh=False))
            sides[name] = Api(f"http://127.0.0.1:{port}", procs[-1].pid)
            point_router(sides[name], router_port)
        # Both copies settle (a copy picks up files whose checkpoint names the lake's own
        # data folder) and must hold the same events, or the two sides time different work.
        counts = {name: settle(api, name) for name, api in sides.items()}
        if counts["before"] != counts["after"]:
            raise RuntimeError(f"the two servers hold different events: {counts}")
        print(f"servers: {counts['after']:,} events each; load average {os.getloadavg()[0]:.2f}", file=sys.stderr)  # fmt: skip
        wanted = {k: v for k, v in pages().items() if not args.only or k in args.only}
        times: Times = {p: {k: [] for k in KEYS} for p in wanted}
        failures = measure(sides, wanted, args.rounds, 0, times)
        # A page flagged once is timed again for twice the rounds and judged on all of
        # them, so a burst of load from something else on the machine is not a flag.
        again = {p: wanted[p] for p, t in times.items() if judge(t)}
        if again and not failures:
            failures = measure(sides, again, args.rounds * 2, args.rounds + 1, times)
        if failures:
            print("Calls failed:\n" + "\n".join(sorted(set(failures))), file=sys.stderr)
            return 2
        rows, breach = [], False
        print(
            "| Page | Before ms | After ms | Change ms | Change % | Server CPU ms (median) | Flag |"
        )
        print("|---|---|---|---|---|---|---|")
        for page, t in times.items():
            b, a = medians(t)
            cb, ca = medians(t, "_cpu")
            f = judge(t)
            breach = breach or bool(f)
            pct = (a - b) / b * 100 if b else 0.0
            rows.append({"page": page, "before_ms": round(b), "after_ms": round(a), "before_cpu_ms": round(cb), "after_cpu_ms": round(ca), "flag": f})  # fmt: skip
            print(f"| {page} | {b:.0f} | {a:.0f} | {a - b:+.0f} | {pct:+.1f}% | {cb:.0f} to {ca:.0f} | {f} |")  # fmt: skip
        print(f"\nMedians of {args.rounds} interleaved rounds after a warm-up ({3 * args.rounds} for"
              f" a page flagged on the first pass); flag: more than {PCT:.0f}% and at least"
              f" {FLOOR_MS:.0f} ms slower, or more than {MS:.0f} ms slower, in the median, confirmed"
              f" by the fastest round or by {PCT:.0f}% more server CPU.")  # fmt: skip
        print(f"Before {before_sha[:12]}, after {after_sha[:12]}, each a clean export; {counts['after']:,}"
              f" events; load average {os.getloadavg()[0]:.2f} at the end.")  # fmt: skip
        if args.json:
            args.json.write_text(json.dumps(rows, indent=1))
        return 1 if breach else 0
    except (RuntimeError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as exc:
        print(f"bench could not run: {exc}", file=sys.stderr)
        return 2
    finally:
        for p in procs:
            stop(p)
        for c in reversed(cleanups):
            c()


if __name__ == "__main__":
    raise SystemExit(main())
