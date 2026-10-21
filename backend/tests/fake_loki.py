"""A fake Loki query_range endpoint for tests: no network, controllable contents."""

import json
from dataclasses import dataclass, field
from urllib.parse import parse_qs

import httpx


@dataclass
class FakeLoki:
    entries: list[tuple[int, str, dict[str, str]]] = field(default_factory=list)
    calls: list[httpx.Request] = field(default_factory=list)
    status: int = 200

    def add(self, ns: int, line: str, **labels: str) -> None:
        self.entries.append((ns, line, labels or {"job": "syslog"}))

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if self.status != 200:
            return httpx.Response(self.status, text="nope")
        q = {k: v[0] for k, v in parse_qs(req.url.query.decode()).items()}
        start, end, limit = int(q["start"]), int(q["end"]), int(q["limit"])
        assert q["direction"] == "forward"
        found = sorted(
            (e for e in self.entries if start <= e[0] < end), key=lambda e: (e[0], e[1])
        )[:limit]
        streams: dict[str, dict[str, object]] = {}
        for ns, line, labels in found:
            key = json.dumps(labels, sort_keys=True)
            s = streams.setdefault(key, {"stream": labels, "values": []})
            s["values"].append([str(ns), line])  # type: ignore[union-attr]  # list
        body = {
            "status": "success",
            "data": {"resultType": "streams", "result": list(streams.values())},
        }
        return httpx.Response(200, json=body)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
