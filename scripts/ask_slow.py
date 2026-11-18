#!/usr/bin/env python3
"""Ask with a slow model behind a proxy that gives up (owner, 2026-11-17; D269, D270).

On the work install a reverse proxy ended an Ask at about 120 s with a 504 and the page
said "Can't reach the server". This is that setup scaled down to seconds: the stand-in
model (`screenshots/stand_in_model.py`) writes the query in SQL_DELAY_S and stalls the
summary for SUMMARY_DELAY_S, past the server's `ask.model_timeout_s` (MODEL_TIMEOUT_S);
the proxy below forwards to the app and answers 504 to any Ask request that takes longer
than PROXY_TIMEOUT_S. The browser check first asks a question whose summary comes in time
(DONE) and fails when the steps line, the headline, or the table moves as the summary
arrives; then it asks one whose summary stalls (QUESTION) through the proxy and passes when the progress
steps show, the table appears, the summary says it timed out with the table still there,
and no 5xx or "Can't reach the server" reaches the page. A control call to the old
synchronous summary endpoint through the same proxy must get the proxy's 504, so the
check cannot pass because the proxy never gave up.

`smoke.py` runs it as Admin and Analyst on the server it starts (`--lake`; `--ask-only`
runs just this step). Standard library only, besides Playwright in the browser check.
"""

from __future__ import annotations

import http.client
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROXY_TIMEOUT_S = 2.0  # the proxy's limit for Ask (120 s on the work install)
OTHER_TIMEOUT_S = 60.0  # for every other request
SQL_DELAY_S = 0.5  # the query call: well inside every limit
SUMMARY_DELAY_S = 9.0  # the summary call: past the model time limit
MODEL_TIMEOUT_S = 5  # ask.model_timeout_s on the server under test (its minimum)
PROVIDER = "Slow stand-in model (not an LLM)"
DONE = "Which events came in last?"  # summarized in time
QUESTION = "Which events came in last, with their ids?"  # its summary stalls (STALL)
STALL = "with their ids"
SQL = "SELECT event_id, time, source_id, message FROM events ORDER BY time DESC LIMIT 5"
TIMED_OUT = "The model took too long to summarize. Results are above."
NEVER = ("Can't reach the server", "The request took too long", "The server is busy", "Gateway")
WAIT_MS = 45_000


class Proxy(ThreadingHTTPServer):
    """A reverse proxy with a time limit: each request goes to `upstream`, and a request
    with no answer within `timeout_s` gets a 504 page, as nginx gives with
    proxy_read_timeout. Counts the requests it gave up on."""

    daemon_threads = True
    request_queue_size = 128  # a page opens many connections at once (the default is 5)

    def __init__(self, upstream: str, timeout_s: float = PROXY_TIMEOUT_S) -> None:
        host, port = upstream.removeprefix("http://").rstrip("/").split(":")
        self.upstream = (host, int(port))
        self.timeout_s = timeout_s
        self.gave_up: list[str] = []
        super().__init__(("127.0.0.1", 0), _Forward)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> Proxy:
        threading.Thread(target=self.serve_forever, name="ask-proxy", daemon=True).start()
        return self


class _Forward(BaseHTTPRequestHandler):
    server: Proxy
    protocol_version = "HTTP/1.1"

    def _forward(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        # The browser's Host goes on, as a reverse proxy sends it, so the app's same-origin
        # check sees the address the page was opened at.
        headers = {k: v for k, v in self.headers.items() if k.lower() != "connection"}
        # The scaled limit is for Ask's own requests: on a loaded test machine a page's first
        # load can take longer than 2 s, which a real limit of 120 s never meets.
        ask = self.path.startswith("/api/ask")
        limit = self.server.timeout_s if ask else OTHER_TIMEOUT_S
        conn = http.client.HTTPConnection(*self.server.upstream, timeout=limit)
        try:
            conn.request(self.command, self.path, body or None, headers)
            res = conn.getresponse()
            data = res.read()
        except OSError as exc:  # TimeoutError is one: 504, as nginx; anything else 502
            self.server.gave_up.append(f"{self.command} {self.path}")
            late = isinstance(exc, TimeoutError)
            page = b"<html><body><h1>%d Gateway</h1></body></html>" % (504 if late else 502)
            self.send_response(504 if late else 502)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        finally:
            conn.close()
        self.send_response(res.status, res.reason)
        for k, v in res.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _forward

    def log_message(self, *args: Any) -> None:
        pass


def start_model(port: int) -> subprocess.Popen[bytes]:
    """The stand-in model, slow on the summary, answering every question with SQL."""
    cmd = [
        sys.executable, str(HERE / "screenshots" / "stand_in_model.py"), "--port", str(port),
        "--sql-delay", str(SQL_DELAY_S), "--summary-delay", str(SUMMARY_DELAY_S), "--sql", SQL,
        "--stall-on", STALL,
    ]  # fmt: skip
    proc = subprocess.Popen(cmd)  # noqa: S603  # a sibling script, fixed arguments
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1).close()  # noqa: S310  # loopback
            return proc
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("the stand-in model did not start")


def add_provider(api: Any, port: int) -> None:
    """The stand-in as an enabled provider, by its own name (`api` is bench_compare.Api)."""
    base_url = f"http://127.0.0.1:{port}/v1"
    mine = [p for p in api.call("GET", "/api/providers") if p.get("name") == PROVIDER]
    if not mine:
        mine = [api.call("POST", "/api/providers", {"name": PROVIDER, "base_url": base_url, "model": "scripted-demo"})]  # fmt: skip
    api.call("PATCH", f"/api/providers/{mine[0]['provider_id']}", {"enabled": True, "base_url": base_url})  # fmt: skip


def grant(api: Any, username: str, source_id: str = "volume_web") -> None:
    """One source for `username` through a group, so an Analyst's question has rows (a
    smoke install's Analyst has none otherwise)."""
    groups = [g for g in api.call("GET", "/api/groups") if g["name"] == "Ask check"]
    group = groups[0] if groups else api.call("POST", "/api/groups", {"name": "Ask check"})
    user = [u for u in api.call("GET", "/api/users") if u["username"] == username][0]
    gid = group["group_id"]
    api.call("PUT", f"/api/groups/{gid}/sources", {"source_ids": [source_id]})
    api.call("PUT", f"/api/groups/{gid}/members", {"user_ids": [user["user_id"]]})


def _tops(turn: Any) -> dict[str, float]:
    """Where the steps, the headline (the answer's first line), and the table start."""

    def top(loc: Any) -> float:
        return float(loc.bounding_box()["y"])

    return {
        "steps line": top(turn.get_by_role("list", name="Progress")),
        "headline": top(turn.locator("p.font-semibold").first),
        "table": top(turn.get_by_role("table", name="Results")),
    }


def check(page: Any, proxy: str, csrf: str) -> list[str]:
    """Ask through the proxy as the signed-in person of `page`; what went wrong, in words."""
    bad: list[str] = []
    seen_5xx: list[str] = []
    page.on("response", lambda r: seen_5xx.append(f"{r.status} {r.url}") if r.status >= 500 else None)  # fmt: skip
    trail: list[str] = []  # what the page met, said when a step does not come
    page.on("requestfailed", lambda r: trail.append(f"failed {r.url} {r.failure}"))
    page.on("console", lambda m: trail.append(f"console {m.text[:120]}") if m.type == "error" else None)  # fmt: skip
    turn = page.get_by_role("region", name=f"Question: {QUESTION}")
    done = page.get_by_role("region", name=f"Question: {DONE}")
    moved: list[str] = []
    try:
        page.goto(proxy + "/ask-ai")
        page.get_by_role("textbox", name="Question").wait_for(timeout=WAIT_MS)
        for control, option in (("Time", "7 days"), ("Model", PROVIDER)):
            page.get_by_role("combobox", name=control, exact=True).click()
            page.get_by_role("listbox").get_by_role("option", name=option, exact=True).click()
        # First a question summarized in time: nothing above the table, nor the table,
        # moves when the summary arrives (designer, PR 658).
        page.get_by_role("textbox", name="Question").fill(DONE)
        page.get_by_role("button", name="Ask", exact=True).click()
        done.get_by_role("list", name="Progress").get_by_text("Summarizing…").wait_for(timeout=WAIT_MS)  # fmt: skip
        before = _tops(done)
        done.get_by_role("list", name="Summary").wait_for(timeout=WAIT_MS)
        after = _tops(done)
        moved = [f"ask: the {k} moved {after[k] - v:+.0f} px when the summary arrived" for k, v in before.items() if abs(after[k] - v) > 0.5]  # fmt: skip
        page.get_by_role("textbox", name="Question").fill(QUESTION)
        with page.expect_response(lambda r: r.url.endswith("/api/ask/jobs")) as submitted:
            page.get_by_role("button", name="Refine", exact=True).click()
        job = submitted.value.json().get("job_id", "")
        turn.get_by_role("list", name="Progress").wait_for(timeout=WAIT_MS)
        turn.get_by_role("table", name="Results").wait_for(timeout=WAIT_MS)
        turn.get_by_role("list", name="Progress").get_by_text("Summarizing").wait_for(timeout=WAIT_MS)  # fmt: skip
        turn.get_by_text(TIMED_OUT).wait_for(timeout=WAIT_MS)
    except Exception as exc:  # noqa: BLE001  # a Playwright timeout: say which step
        shot = Path(tempfile.gettempdir()) / f"ask-slow-{time.monotonic_ns()}.png"
        page.screenshot(path=str(shot), full_page=True)
        return [f"ask: {str(exc).splitlines()[0][:160]} (page: {shot}; {trail[:4]})"]
    bad += moved
    if not turn.get_by_role("table", name="Results").is_visible():
        bad.append("ask: the table went away when the summary timed out")
    text = page.inner_text("body")
    bad += [f"ask: the page says '{w}'" for w in NEVER if w in text]
    bad += [f"ask: a {s} reached the page" for s in seen_5xx]
    # The control: the old synchronous summary call through the same proxy outlasts it.
    ask_id = page.request.get(f"{proxy}/api/ask/jobs/{job}").json()["ask"]["ask_id"]
    old = page.request.post(f"{proxy}/api/ask/{ask_id}/answer", headers={"X-CSRF-Token": csrf})
    if old.status != 504:
        bad.append(f"ask: the control call got {old.status}, not the proxy's 504")
    return bad
