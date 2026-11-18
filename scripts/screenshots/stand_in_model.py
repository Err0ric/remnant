#!/usr/bin/env python3
"""A scripted stand-in for a model, for the README screenshots only. It is not an LLM.

    python3 scripts/screenshots/stand_in_model.py --port 8091

Speaks just enough of the OpenAI-compatible chat API (/v1/models, /v1/chat/completions)
for Ask and Explain on the demo data (`make demo`):

- Ask: always answers the same question (QUESTION below) with the same SQL, so the page
  shows a real round trip through the gate, the guard, the preview, and Run.
- Ask's answer: reads the rows of that query (under the `data` key) and states what they
  show, citing the event ids of the rows it is about.
- Explain: reads the events it was sent (under the `data` key, as every provider gets
  them) and states counts with the event ids it was given, so the citation check passes
  on real ids. It never invents an id.

The provider is added in Remnant under a name that says what it is (see capture.py), so
a screenshot never passes this off as a real model. Stdlib only.

`--sql-delay` and `--summary-delay` make it slow on purpose (seconds before the query
answer and before the summary answer), so a test can see Ask's progress steps and its
summary time limit (D270; scripts/ask_slow.py); with `--stall-on TEXT` only a question
holding TEXT waits `--summary-delay`, and others get their summary after FAST_S. `--sql`
answers with other SQL, for a lake other than the demo's.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODEL = "scripted-demo"
FAST_S = 1.5  # a summary that is not stalled (--stall-on): long enough to be seen running
QUESTION = "Did any address that failed SSH passwords this week sign in to Microsoft 365?"
SQL = """SELECT event_id, time, actor_user_name, src_endpoint_ip, status_id, message
FROM events
WHERE source_id = 'm365_signin'
  AND time >= now() - INTERVAL 7 DAY
  AND src_endpoint_ip IN (SELECT src_endpoint_ip FROM events
                          WHERE source_id = 'linux_sshd' AND status_id = 2)
ORDER BY status_id, time DESC
LIMIT 6"""
ASK = {
    "sql": SQL,
    "explanation": (
        "Microsoft 365 sign-ins in the last 7 days from any address that also failed an SSH"
        " password. Successful sign-ins (status 1) come first."
    ),
    "assumptions": ["A failed SSH password is a linux_sshd event with status Failure (2)."],
}


def events_in(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events in the data message, wherever they sit under `data`."""
    found: list[dict[str, Any]] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if "event_id" in v:
                found.append(v)
            else:
                for x in v.values():
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for m in messages:
        try:
            walk(json.loads(m.get("content") or ""))
        except (ValueError, TypeError):
            continue
    return found


def explain(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"claims": [{"text": "No events were sent.", "event_ids": []}]}
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_source[str(e.get("source_id"))].append(e)
    claims = []
    for source, rows in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        failed = [r for r in rows if r.get("status_id") == 2]
        ok = [r for r in rows if r.get("status_id") == 1]
        ips = Counter(str(r.get("src_endpoint_ip")) for r in rows if r.get("src_endpoint_ip"))
        users = Counter(str(r.get("actor_user_name")) for r in rows if r.get("actor_user_name"))
        if failed:
            top = ", ".join(ip for ip, _ in ips.most_common(3))
            claims.append({
                "text": f"{len(failed)} failed {source} events from {len(ips)} addresses ({top}), trying {len(users)} different accounts.",
                "event_ids": [str(r["event_id"]) for r in failed[:6]],
            })  # fmt: skip
        for r in ok[:2]:
            claims.append({
                "text": f"A successful {source} event for {r.get('actor_user_name')} from {r.get('src_endpoint_ip')}, an address that also failed.",
                "event_ids": [str(r["event_id"])],
            })  # fmt: skip
    return {"claims": claims[:6] or [{"text": f"{len(events)} events.", "event_ids": [str(events[0]["event_id"])]}]}  # fmt: skip


def summarize(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask's answer step: statements about the rows of SQL above, citing their event ids."""
    data: dict[str, Any] = {}
    for m in messages:
        try:
            body = json.loads(m.get("content") or "")
        except (ValueError, TypeError):
            continue
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            data = body["data"]
    cols = [str(c) for c in data.get("columns") or []]
    rows = [dict(zip(cols, r, strict=False)) for r in data.get("rows") or [] if isinstance(r, list)]
    claims = []
    for r in [r for r in rows if r.get("status_id") == 1][:2]:
        who, ip = r.get("actor_user_name"), r.get("src_endpoint_ip")
        text = f"{who} signed in to Microsoft 365 from {ip}, an address that also failed SSH"
        text += " passwords."
        claims.append({"text": text, "event_ids": [str(r["event_id"])]})
    failed = [r for r in rows if r.get("status_id") == 2]
    if failed:
        users = Counter(str(r.get("actor_user_name")) for r in failed)
        ips = list(Counter(str(r.get("src_endpoint_ip")) for r in failed))
        named = ", ".join(ips) if len(ips) <= 5 else "including " + ", ".join(ips[:3])
        text = f"{len(failed)} failed Microsoft 365 sign-ins from {len(ips)} addresses that also"
        text += f" failed SSH passwords ({named}) tried {len(users)} accounts."
        claims.append({"text": text, "event_ids": [str(r["event_id"]) for r in failed]})
    if not claims and rows and rows[0].get("event_id"):  # rows of another lake: one statement
        first = rows[0]
        text = f"The first of these {len(rows)} events came from {first.get('source_id')}."
        claims.append({"text": text, "event_ids": [str(first["event_id"])]})
    return {"claims": claims}


class Handler(BaseHTTPRequestHandler):
    # Set from the command line in main(), or by a test that serves this handler itself.
    sql = SQL
    sql_delay = 0.0
    summary_delay = 0.0
    stall_on = ""

    def _send(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802  # http.server's name
        self._send({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self) -> None:  # noqa: N802  # same
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        messages = body.get("messages") or []
        system = " ".join(
            str(m.get("content")) for m in messages if m.get("role") == "system"
        ).lower()
        events = events_in(messages)
        if "sql query" in system:
            time.sleep(self.sql_delay)
            answer = {**ASK, "sql": self.sql}
        elif "summarize the result of a query" in system:
            text = json.dumps(messages)
            stall = not self.stall_on or self.stall_on in text
            time.sleep(self.summary_delay if stall else FAST_S)
            answer = summarize(messages)
        else:
            answer = explain(events)
        try:
            self._send({
                "id": "demo", "object": "chat.completion", "model": MODEL,
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            })  # fmt: skip
        except (BrokenPipeError, ConnectionResetError):
            pass  # the server gave up on a slow answer (its model time limit)

    def log_message(self, *args: Any) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--sql-delay", type=float, default=0.0, help="seconds before the SQL")
    ap.add_argument("--summary-delay", type=float, default=0.0, help="seconds before a summary")
    ap.add_argument("--sql", default=SQL, help="the SQL to answer every question with")
    ap.add_argument("--stall-on", default="", help="only a question with this text waits")
    args = ap.parse_args()
    Handler.sql, Handler.stall_on = args.sql, args.stall_on
    Handler.sql_delay, Handler.summary_delay = args.sql_delay, args.summary_delay
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
